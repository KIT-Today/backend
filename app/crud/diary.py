from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete
from sqlalchemy.orm import selectinload

from app.models.tables import Diary, EmotionAnalysis, SolutionLog
from app.schemas.diary import DiaryCreate, DiaryUpdate
from app.crud.attendance import create_attendance # 위에서 수정한 비동기 함수
from app.services.s3_service import delete_image_from_s3

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

        # MissingGreenlet 에러 방지 (필수!)
        # 방금 만든 일기라 당연히 분석 결과와 솔루션이 없습니다.
        # FastAPI가 응답을 만들 때 DB 조회를 시도하지 않도록 빈 값을 수동으로 채워줍니다.
        db_diary.emotion_analysis = None
        db_diary.solution_logs = []

        # 3. 커밋
        await db.commit() 
        await db.refresh(db_diary) 
        
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
        # delete 실행 시 await
        await db.exec(delete(EmotionAnalysis).where(EmotionAnalysis.diary_id == db_diary.diary_id))
        await db.exec(delete(SolutionLog).where(SolutionLog.diary_id == db_diary.diary_id))

        # 메모리 상의 객체 초기화 
        # DB에서는 지웠지만, db_diary 객체는 여전히 과거의 분석 결과를 기억하고 있을 수 있습니다.
        # 응답 시 "분석 결과 없음(None)"으로 정확히 나가도록 명시적으로 비워줍니다.
        db_diary.emotion_analysis = None
        db_diary.solution_logs = []

    update_data = diary_in.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(db_diary, key, value)
    
    db_diary.image_url = image_url
    
    db.add(db_diary)
    await db.commit() 
    
    return db_diary, is_content_changed

# 5. 일기 삭제 (비동기)
async def delete_diary(db: AsyncSession, diary_id: int, user_id: int):
    # 내부 함수 호출 시 await , 내부 함수 호출 (get_diary에서 이미 로딩하므로 안전)
    db_diary = await get_diary(db, diary_id, user_id)

    if db_diary.image_url:
        # S3 삭제는 네트워크 작업이므로 여기서 바로 호출해도 되지만, 
        # 만약 S3 서비스가 동기 함수라면 나중에 anyio.to_thread로 감싸는 게 좋습니다.
        # 일단은 기존 로직 유지
        delete_image_from_s3(db_diary.image_url)
    
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