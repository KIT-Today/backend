# app/schemas/interaction.py
from pydantic import BaseModel
from typing import Optional

# 1. 프론트엔드 -> 백엔드 (요청 받을 때)
class PlanBRequest(BaseModel):
    text: str         # 일기 본문
    timestamp: str    # ISO 8601 형식의 문자열

# 2. 백엔드 <-> AI 서버 및 프론트엔드 (응답 주고받을 때)
class PlanBResponse(BaseModel):
    user_id: str      # AI 서버 명세가 string이므로 str로 정의
    sentiment: str
    sentiment_score: float
    intensity: int
    game_event: str