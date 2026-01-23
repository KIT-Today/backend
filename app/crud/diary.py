# app/crud/diary.py
from fastapi import HTTPException
from sqlmodel import Session, select, delete
from sqlalchemy.orm import selectinload

from app.models.tables import Diary, EmotionAnalysis, SolutionLog
from app.schemas.diary import DiaryCreate, DiaryUpdate
from app.crud.attendance import create_attendance # 이미 만든 출석 함수
from app.services.s3_service import delete_image_from_s3

from typing import Optional
from datetime import datetime

# 1. 일기 생성 (+ 출석 체크 + AI 분석 트리거 위치)
def create_diary(db: Session, diary_in: DiaryCreate, user_id: int, image_url: Optional[str] = None) -> Diary:
    try:
        # 1. 일기 데이터를 프론트가 넘겨준 db에 담습니다.
        db_diary = Diary.model_validate(diary_in, update={"user_id": user_id, "image_url": image_url})
        db.add(db_diary)

        # 2. 출석 데이터도 같은 db에 담습니다. 
        # (create_attendance 함수 내부에서도 같은 db 세션을 써야 합니다!)
        create_attendance(db, user_id=user_id)

        # 3. [중요] 여기서 딱 한 번만 (Commit)! 
        # 이제서야 실제 DB에 일기와 출석이 동시에 기록됩니다.
        db.commit()
        
        # 4. 저장된 정보를 다시 확인합니다.
        db.refresh(db_diary)
        
    except Exception as e:
        # 5. 장바구니에 담다가 하나라도 문제가 생기면 (예: 출석체크 에러)
        # 담았던 것들을 전부 비워버리고(Rollback) 실제 DB에는 아무것도 남기지 않습니다.
        db.rollback()
        print(f"🚨 DB 처리 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail="일기 저장 및 출석 처리 중 오류가 발생했습니다.")

# (주의) AI 분석 요청은 여기서 하지 않고, api/diary.py 라우터에서 BackgroundTasks로 수행합니다.
    return db_diary

# 2. 일기 상세 조회 (관계 데이터 포함)
def get_diary(db: Session, diary_id: int, user_id: int) -> Diary:
    statement = (
        select(Diary)
        .where(Diary.diary_id == diary_id)
        .where(Diary.user_id == user_id)
        .options(
            # 연관된 분석 결과와 솔루션을 같이 가져옴 (없으면 비워둠)
            selectinload(Diary.emotion_analysis),
            selectinload(Diary.solution_logs)
        )
    )
    diary = db.exec(statement).first()
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없습니다.")
    return diary

# 3. 일기 목록 조회
# year와 month를 Optional[int] = None으로 받습니다.
def get_diaries(
    db: Session, 
    user_id: int, 
    skip: int = 0, 
    limit: int = 10, 
    year: Optional[int] = None, 
    month: Optional[int] = None
) -> list[Diary]:
    
    # 1. 기본 쿼리: 내 일기 가져오기
    statement = select(Diary).where(Diary.user_id == user_id)

    # 2. 연도와 월
    if year:
        if month:
            # Case A: 연도 + 월 존재 -> "그 연도의 그 달" (예: 2026년 1월)
            start_date = datetime(year, month, 1)
            
            # 다음 달 계산
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
                
            statement = statement.where(Diary.created_at >= start_date).where(Diary.created_at < end_date)
            
        else:
            # Case B: 연도만 존재 -> "그 연도 전체" (예: 2026년 1월 ~ 12월)
            start_date = datetime(year, 1, 1)
            end_date = datetime(year + 1, 1, 1)
            
            statement = statement.where(Diary.created_at >= start_date).where(Diary.created_at < end_date)
    
    # 3. 공통 로직: 최신순 정렬 + 페이징 (skip, limit)
    # 월별 조회라도 일기가 100개일 수 있으니 페이징은 유지하는 게 좋습니다.
    statement = statement.order_by(Diary.created_at.desc()).offset(skip).limit(limit)
    
    return db.exec(statement).all()

# 4. 일기 수정
def update_diary_with_image(
    db: Session, 
    db_diary: Diary, 
    diary_in: DiaryUpdate, 
    image_url: Optional[str]
) -> tuple[Diary, bool]: # 변경 여부를 알려주기 위해 튜플 반환
    """
    전달받은 필드들만 골라서 업데이트하고, 내용 변경 여부를 반환합니다.
    """
    # (1) 내용이나 키워드가 실제로 바뀌었는지 확인 (AI 재분석 필요성 판단) - 이미지는 변경만!
    is_content_changed = False
    if (diary_in.content is not None and diary_in.content != db_diary.content) or \
       (diary_in.keywords is not None and diary_in.keywords != db_diary.keywords):
        is_content_changed = True

    # (2) 내용이 바뀌었다면 기존의 감정 분석과 솔루션 로그를 삭제 (데이터 정합성)
    if is_content_changed:
        db.exec(delete(EmotionAnalysis).where(EmotionAnalysis.diary_id == db_diary.diary_id))
        db.exec(delete(SolutionLog).where(SolutionLog.diary_id == db_diary.diary_id))

    # (3) [사용자님이 찾으시던 기능] 전달받은 필드들만 골라서 업데이트
    # exclude_unset=True: 프론트에서 실제로 보내온 필드만 딕셔너리로 만듦
    update_data = diary_in.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(db_diary, key, value)
    
    # (4) 이미지 URL 반영
    db_diary.image_url = image_url
    
    # (5) DB 저장
    db.add(db_diary)
    db.commit()
    
    return db_diary, is_content_changed

# 5. 일기 삭제 (연쇄 삭제)
def delete_diary(db: Session, diary_id: int, user_id: int):
    db_diary = get_diary(db, diary_id, user_id)

    # S3에 이미지가 있다면 삭제
    if db_diary.image_url:
        delete_image_from_s3(db_diary.image_url)
    
    # DB 모델에 cascade="all, delete-orphan"이 걸려 있으므로
    # 부모(Diary)만 지우면 자식(Emotion, Solution)도 자동 삭제됨
    db.delete(db_diary)
    db.commit()
    
    return {"message": "일기가 삭제되었습니다."}