# app/api/activity.py
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from database import get_session
from app.models.tables import Activity
from app.schemas.activity import ActivityRead

router = APIRouter()

@router.get("/", response_model=List[ActivityRead])
async def read_all_activities(
    db: AsyncSession = Depends(get_session)
):
    """
    DB에 저장된 모든 활동(Activity) 목록을 조회합니다.
    (AI 서버 학습용 & 프론트엔드 표시용)
    """
    # 사용 가능한(is_enabled=True) 활동만 조회
    statement = select(Activity).where(Activity.is_enabled == True)
    result = await db.exec(statement)
    return result.all()