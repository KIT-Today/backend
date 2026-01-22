# 1. FastAPI 관련 도구들
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path

# 2. DB 관련 도구들
from sqlmodel import Session, func, select # func, select 꼭 필요함!
from database import get_session

# 3. 인증 관련
from app.api.deps import get_current_user

# 4. 모델(Tables) & 스키마(Schemas)
from app.models.tables import User, Diary, EmotionAnalysis, SolutionLog # 테이블들
from app.schemas.diary import (
    DiaryCreate, 
    DiaryRead, 
    DiaryUpdate, 
    AIAnalysisResult # 아까 만든 AI용 스키마
)
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

# 6. AI가 분석 끝나면 호출할 콜백 API
@router.post("/analysis-callback")
def receive_ai_result(
    result: AIAnalysisResult,
    db: Session = Depends(get_session)
):
    """
    [AI 서버 전용] AI가 분석을 마치면 이 API를 호출해서 결과를 저장합니다.
    """
    print(f"📩 [From AI Server] 분석 결과 도착! (Diary ID: {result.diary_id})")

    # 1. 일기 찾기
    diary = db.get(Diary, result.diary_id)
    if not diary:
        return {"msg": "Diary not found"}
    
    # [A] 감정 분석 결과 저장
    # 일기 개수 체크 (3개 미만이면 번아웃 'NONE' 처리)
    count_statement = select(func.count(Diary.diary_id)).where(Diary.user_id == diary.user_id)
    diary_count = db.exec(count_statement).one()

    final_mbi = result.mbi_category
    if diary_count < 3:
        final_mbi = "NONE" # 데이터 부족 시 NONE으로 덮어쓰기

    emotion = EmotionAnalysis(
        diary_id=diary.diary_id,
        primary_emotion=result.primary_emotion,
        primary_score=result.primary_score,
        mbi_category=final_mbi,
        emotion_probs=result.emotion_probs
    )
    db.add(emotion)

  
    # [B] 솔루션 저장 
    # (1) 저장: 리스트(recommendations)를 하나씩 꺼내서 저장
    for rec in result.recommendations:
        new_solution = SolutionLog(
            diary_id=diary.diary_id,
            activity_id=rec.activity_id, # 리스트 안에 있는 id
            ai_message=rec.ai_message,   # 리스트 안에 있는 message
            is_selected=False,
            is_completed=False
        )
        db.add(new_solution)
    
    # 최종 저장 (한 번만 하면 됨)
    db.commit()
    
    return {"msg": "Analysis & Solutions saved successfully"}