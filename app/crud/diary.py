# app/crud/diary.py
from fastapi import HTTPException
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.models.tables import Diary
from app.schemas.diary import DiaryCreate, DiaryUpdate
from app.crud.attendance import create_attendance # 이미 만든 출석 함수
from app.services.s3_service import delete_image_from_s3

from typing import Optional
from datetime import datetime

# 1. 일기 생성 (+ 출석 체크 + AI 분석 트리거 위치)
def create_diary(db: Session, diary_in: DiaryCreate, user_id: int, image_url: Optional[str] = None) -> Diary:
    # (1) DB 저장
    db_diary = Diary.model_validate(diary_in, update={"user_id": user_id, "image_url": image_url})
    db.add(db_diary)
    db.commit()
    db.refresh(db_diary)

    # (2) 출석 체크 (일기 저장 성공 시에만)
    try:
        create_attendance(db, user_id=user_id)
    except Exception as e:
        print(f"⚠️ 출석 처리 중 오류 (일기는 저장됨): {e}")

    # (3) [AI 서버로 분석 요청 보내기]
    # 실제 AI 서버 URL이 생기면 여기에 적으세요.
    ai_url = "http://ai-server-ip:8000/analyze" 
    
    payload = {
        "diary_id": db_diary.diary_id,
        "content": db_diary.content
    }
    
    # 지금은 실제 전송은 주석 처리하고 로그만 찍습니다.
    # try:
    #     requests.post(ai_url, json=payload, timeout=1)
    # except Exception as e:
    #     print(f"AI 요청 실패: {e}")
        
    print(f"🚀 [To AI Server] 일기(ID: {db_diary.diary_id}) 분석 요청 전송! (내용: {db_diary.content[:10]}...)")

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

    # S3에 이미지가 있다면 삭제
    if db_diary.image_url:
        delete_image_from_s3(db_diary.image_url)
    
    # DB 모델에 cascade="all, delete-orphan"이 걸려 있으므로
    # 부모(Diary)만 지우면 자식(Emotion, Solution)도 자동 삭제됨
    db.delete(db_diary)
    db.commit()
    
    return {"message": "일기가 삭제되었습니다."}