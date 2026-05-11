# app/api/interaction.py (또는 diary.py 내부에 추가)
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from app.api.deps import get_current_user
from app.models.tables import User, InteractionList
from app.schemas.interaction import PlanBRequest, PlanBResponse
from app.services.ai_services import request_plan_b_analysis_from_ai

router = APIRouter()

@router.post("/plan-b", response_model=PlanBResponse)
async def process_plan_b_interaction(
    req: PlanBRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    [Plan B] 프론트에서 텍스트를 받아 AI 분석 후, 결과를 DB에 저장하고 프론트로 반환합니다.
    """
    # 1. AI 서버로 데이터 전송 및 결과 받아오기
    ai_result = await request_plan_b_analysis_from_ai(
        user_id=current_user.user_id,
        text=req.text,
        timestamp=req.timestamp
    )

    # 2. 받아온 결과를 DB에 저장 (InteractionList 테이블)
    new_interaction = InteractionList(
        user_id=current_user.user_id,
        sentiment=ai_result.get("sentiment", "NONE"),
        sentiment_score=ai_result.get("sentiment_score", 0.0),
        intensity=ai_result.get("intensity", 0),
        game_event=ai_result.get("game_event", "NONE")
    )
    
    db.add(new_interaction)
    await db.commit()
    await db.refresh(new_interaction)

    # 3. 프론트엔드로 최종 결과 반환
    return PlanBResponse(
        user_id=str(current_user.user_id),
        sentiment=new_interaction.sentiment,
        sentiment_score=new_interaction.sentiment_score,
        intensity=new_interaction.intensity,
        game_event=new_interaction.game_event
    )