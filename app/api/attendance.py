from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession # [변경]

from database import get_session 
from app.api.deps import get_current_user 

from app.schemas.attendance import AttendanceRead
from app.crud import attendance as crud_attendance
from app.models.tables import User

router = APIRouter()

@router.get("/", response_model=List[AttendanceRead])
async def read_attendance( # [변경] async def
    year: int,
    month: int,
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    """
    특정 연/월의 출석 기록을 조회합니다.
    Query Params:
      - year: 2026
      - month: 1
    """
    # [변경] await 추가 (crud 함수가 async이므로)
    attendances = await crud_attendance.get_monthly_attendance(
        db, user_id=current_user.user_id, year=year, month=month
    )
    return attendances