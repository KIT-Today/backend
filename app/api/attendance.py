# app/api/attendance.py
from typing import List
from fastapi import APIRouter, Depends
from sqlmodel import Session

from database import get_session 
from app.api.deps import get_current_user 

from app.schemas.attendance import AttendanceRead
from app.crud import attendance as crud_attendance
from app.models.tables import User

router = APIRouter()

@router.get("/", response_model=List[AttendanceRead])
def read_attendance(
    year: int,
    month: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    특정 연/월의 출석 기록을 조회합니다.
    Query Params:
      - year: 2026
      - month: 1
    """
    attendances = crud_attendance.get_monthly_attendance(
        db, user_id=current_user.user_id, year=year, month=month
    )
    return attendances

# 출석 등록 기능 테스트.. 아직 일기등록 기능이 없어서... 일단 이것만...
@router.post("/test", response_model=None)
def test_create_attendance(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    [테스트용] 강제로 출석 체크를 실행합니다.
    나중에 일기 API가 만들어지면 이 함수는 삭제하세요.
    """
    print(f"🔥 TEST: User {current_user.user_id} 출석 시도 중...")
    
    # 우리가 만든 로직 함수 호출!
    att = crud_attendance.create_attendance(db, user_id=current_user.user_id)
    
    return {"msg": "출석 체크 완료!", "date": att.att_date, "streak": current_user.current_streak}