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
