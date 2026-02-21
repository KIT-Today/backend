from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete
from sqlalchemy.orm import selectinload

from app.models.tables import Diary, EmotionAnalysis, SolutionLog
from app.schemas.diary import DiaryCreate, DiaryUpdate
from app.crud.attendance import create_attendance # 위에서 수정한 비동기 함수
from app.services.s3_service import delete_image_from_s3

import anyio

from typing import Optional
from datetime import datetime, timedelta

# 1. 일기 생성 (비동기)
async def create_diary(db: AsyncSession, diary_in: DiaryCreate, user_id: int, image_url: Optional[str] = None) -> Diary:
    try:
        # 1. 일기 데이터 준비
        db_diary = Diary.model_validate(diary_in, update={"user_id": user_id, "image_url": image_url})
        db.add(db_diary)

        # 2. 출석 체크 호출 (비동기 함수이므로 await 필수!)
        await create_attendance(db, user_id=user_id)

        # 3. 커밋
        await db.commit() 
        await db.refresh(db_diary) 

        # 기존: await db.refresh(db_diary) -> 수동 할당 (불안정함)
        # 변경: 관계 데이터(emotion_analysis, solution_logs)도 같이 리프레시합니다.
        #       새로 만든 일기라 당연히 DB에는 데이터가 없지만, 
        #       SQLAlchemy가 "없음(None/Empty)" 상태를 비동기로 안전하게 로딩해줍니다.
        await db.refresh(db_diary, attribute_names=["emotion_analysis", "solution_logs"])
        
    except Exception as e:
        await db.rollback() # 에러 발생 시 롤백도 await
        print(f"🚨 DB 처리 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail="일기 저장 및 출석 처리 중 오류가 발생했습니다.")

    return db_diary

# 2. 일기 상세 조회 (비동기)
async def get_diary(db: AsyncSession, diary_id: int, user_id: int) -> Diary:
    # [안전] selectinload를 사용하므로 MissingGreenlet 오류가 발생하지 않습니다.
    statement = (
        select(Diary)
        .where(Diary.diary_id == diary_id)
        .where(Diary.user_id == user_id)
        .options(
            selectinload(Diary.emotion_analysis),
            # solution_logs를 가져올 때, 그 안의 activity 정보도 같이 로딩해라!
            selectinload(Diary.solution_logs).selectinload(SolutionLog.activity)
        )
    )
    result = await db.exec(statement)
    diary = result.first()
    
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없습니다.")
    return diary

# 3. 일기 목록 조회 (비동기)
async def get_diaries(
    db: AsyncSession, 
    user_id: int, 
    skip: int = 0, 
    limit: int = 10, 
    year: Optional[int] = None, 
    month: Optional[int] = None
) -> list[Diary]:
    
    statement = select(Diary).where(Diary.user_id == user_id)

    if year:
        if month:
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            statement = statement.where(Diary.created_at >= start_date).where(Diary.created_at < end_date)
        else:
            start_date = datetime(year, 1, 1)
            end_date = datetime(year + 1, 1, 1)
            statement = statement.where(Diary.created_at >= start_date).where(Diary.created_at < end_date)
    
    # 목록 조회 시에도 관계 데이터를 미리 로딩해야 스키마 에러가 안 납니다!
    statement = statement.options(
        selectinload(Diary.emotion_analysis),
        selectinload(Diary.solution_logs).selectinload(SolutionLog.activity)
    )

    statement = statement.order_by(Diary.created_at.desc()).offset(skip).limit(limit)
    
    result = await db.exec(statement) 
    return result.all()

# 4. 일기 수정 (비동기)
async def update_diary_with_image(
    db: AsyncSession, 
    db_diary: Diary, 
    diary_in: DiaryUpdate, 
    image_url: Optional[str]
) -> tuple[Diary, bool]:
    
    is_content_changed = False
    if (diary_in.content is not None and diary_in.content != db_diary.content) or \
       (diary_in.keywords is not None and diary_in.keywords != db_diary.keywords):
        is_content_changed = True

    if is_content_changed:
        # ORM이 cascade="all, delete-orphan"으로 자동 삭제해주므로 직접 delete 쿼리를 날릴 필요가 없습니다.
        # 부모 객체에서 관계만 끊어주면 SQLAlchemy가 알아서 처리합니다.
        
        db_diary.emotion_analysis = None
        
        # 리스트 형태의 관계는 새로 []를 할당하기보다 .clear()로 비워주는 것이 
        # SQLAlchemy가 변경 사항을 추적하는 데 훨씬 안전합니다.
        db_diary.solution_logs.clear()

    # 2. 일기 정보 업데이트
    update_data = diary_in.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(db_diary, key, value)
    
    # 이미지 URL이 있으면 업데이트
    if image_url:
        db_diary.image_url = image_url
    
    db.add(db_diary)
    # 3. 커밋 (이 순간 db_diary의 모든 속성이 만료됨!)
    await db.commit() 

   
    # [최적화 포인트] 상황에 따라 Refresh 전략을 다르게 가져갑니다.
    if is_content_changed:
        # A. 내용이 바뀌었다면? -> 분석 결과는 이미 지웠으니 DB에서 가져올 필요가 없음!
        # 기본 정보(수정된 내용, 날짜 등)만 리프레시합니다.
        await db.refresh(db_diary) 
        
        # 그리고 관계 데이터는 빈 값으로 세팅 (쿼리 절약 성공!)
        db_diary.emotion_analysis = None
        db_diary.solution_logs = []
        
    else:
        # B. 사진만 바뀌었다면? -> 분석 결과가 살아있음.
        # 기존 분석 결과를 유지하기 위해 명시적으로 같이 로딩합니다.
        await db.refresh(db_diary, attribute_names=["emotion_analysis", "solution_logs"])

    return db_diary, is_content_changed

# 5. 일기 삭제 (비동기)
async def delete_diary(db: AsyncSession, diary_id: int, user_id: int):
    # 내부 함수 호출 시 await , 내부 함수 호출 (get_diary에서 이미 로딩하므로 안전)
    db_diary = await get_diary(db, diary_id, user_id)

    if db_diary.image_url:
        # [핵심] run_sync를 사용하여 별도 스레드에서 실행
        # 첫 번째 인자: 실행할 함수 이름 (괄호 없이)
        # 두 번째 인자: 그 함수에 들어갈 파라미터
        await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
    
    await db.delete(db_diary) # delete 자체는 await 필요 없음(add와 비슷), 하지만 commit은 필수
    await db.commit() 
    
    return {"message": "일기가 삭제되었습니다."}

# 6. 14일 일기 최근 데이터 조회 (이미 비동기임, 그대로 유지)
async def get_recent_diaries_for_ai(db: AsyncSession, user_id: int, days: int = 14):
    two_weeks_ago = datetime.now() - timedelta(days=days)
    # [참고] 여기서는 selectinload를 안 썼지만 괜찮습니다.
    # AI 서버로 보낼 때는 emotion_analysis나 solution_logs 같은 관계 데이터를 안 보내고
    # 오직 content, keywords 같은 기본 컬럼만 쓰기 때문입니다.
    statement = (
        select(Diary)
        .where(Diary.user_id == user_id)
        .where(Diary.created_at >= two_weeks_ago)
        .order_by(Diary.created_at.desc())
    )
    result = await db.exec(statement)
    return result.all()