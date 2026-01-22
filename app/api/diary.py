# app/api/diary.py
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlmodel import Session

from database import get_session
from app.api.deps import get_current_user
from app.models.tables import User
from app.schemas.diary import DiaryCreate, DiaryRead, DiaryUpdate
from app.crud import diary as crud_diary

router = APIRouter()

# 1. 일기 등록 (POST /diaries/)
@router.post("/", response_model=DiaryRead)
def create_diary(
    diary_in: DiaryCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기를 등록합니다. (자동으로 출석 처리됨)
    """
    return crud_diary.create_diary(db, diary_in, current_user.user_id)

# 2. 일기 목록 조회 (GET /diaries/)
@router.get("/", response_model=List[DiaryRead])
def read_diaries(
    skip: int = 0,
    limit: int = 10,
    year: Optional[int] = Query(None, description="필터링할 연도 (예: 2026)"),
    month: Optional[int] = Query(None, description="필터링할 월 (예: 1)"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    내 일기 목록을 최신순으로 조회합니다.
    - year만 입력: 해당 연도 전체
    - year + month 입력: 해당 연도의 특정 월
    - 둘 다 미입력: 전체 일기 (페이징)
    """
    return crud_diary.get_diaries(
        db, 
        user_id=current_user.user_id, 
        skip=skip, 
        limit=limit, 
        year=year, 
        month=month
    )

# 3. 일기 상세 조회 (GET /diaries/{diary_id})
@router.get("/{diary_id}", response_model=DiaryRead)
def read_diary(
    diary_id: int = Path(..., description="조회할 일기 ID"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기 상세 내용을 조회합니다.
    (감정 분석 결과나 솔루션이 있으면 같이 나오고, 없으면 비어서 나옵니다)
    """
    return crud_diary.get_diary(db, diary_id, current_user.user_id)

# 4. 일기 수정 (PATCH /diaries/{diary_id})
@router.patch("/{diary_id}", response_model=DiaryRead)
def update_diary(
    diary_in: DiaryUpdate,
    diary_id: int = Path(..., description="수정할 일기 ID"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기 내용을 수정합니다. (보낸 필드만 수정됨)
    """
    return crud_diary.update_diary(db, diary_id, diary_in, current_user.user_id)

# 5. 일기 삭제 (DELETE /diaries/{diary_id})
@router.delete("/{diary_id}")
def delete_diary(
    diary_id: int = Path(..., description="삭제할 일기 ID"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기를 삭제합니다. 연관된 분석 데이터도 함께 삭제됩니다.
    """
    return crud_diary.delete_diary(db, diary_id, current_user.user_id)