# app/schemas/activity.py
from sqlmodel import SQLModel

# 활동 목록 조회 응답 (기본키 + 내용 + 카테고리)
class ActivityRead(SQLModel):
    activity_id: int
    act_content: str
    act_category: str
    is_active: bool
    is_outdoor: bool
    is_social: bool