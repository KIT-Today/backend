# app/crud/diary.py
from fastapi import HTTPException
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.models.tables import Diary
from app.schemas.diary import DiaryCreate, DiaryUpdate
from app.crud.attendance import create_attendance # 이미 만든 출석 함수

from typing import Optional
from datetime import datetime

# 1. 일기 생성 (+ 출석 체크 + AI 분석 트리거 위치)
def create_diary(db: Session, diary_in: DiaryCreate, user_id: int) -> Diary:
    # (1) DB 저장
    db_diary = Diary.model_validate(diary_in, update={"user_id": user_id})
    db.add(db_diary)
    db.commit()
    db.refresh(db_diary)

    # (2) 출석 체크 (일기 저장 성공 시에만)
    try:
        create_attendance(db, user_id=user_id)
    except Exception as e:
        print(f"⚠️ 출석 처리 중 오류 (일기는 저장됨): {e}")

    # (3) [AI 모델 연결 위치] 
    # 나중에 여기에 analyze_diary(db_diary.content) 같은 함수를 호출해서
    # EmotionAnalysis 테이블에 결과를 저장하는 코드를 넣으면 됩니다.
    
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
def update_diary(db: Session, diary_id: int, diary_in: DiaryUpdate, user_id: int) -> Diary:
    db_diary = get_diary(db, diary_id, user_id) # 존재 확인

    update_data = diary_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_diary, key, value)
    
    # created_at은 수정하지 않음!
    
    db.add(db_diary)
    db.commit()
    db.refresh(db_diary)
    return db_diary

# 5. 일기 삭제 (연쇄 삭제)
def delete_diary(db: Session, diary_id: int, user_id: int):
    db_diary = get_diary(db, diary_id, user_id)
    
    # DB 모델에 cascade="all, delete-orphan"이 걸려 있으므로
    # 부모(Diary)만 지우면 자식(Emotion, Solution)도 자동 삭제됨
    db.delete(db_diary)
    db.commit()
    
    return {"message": "일기가 삭제되었습니다."}