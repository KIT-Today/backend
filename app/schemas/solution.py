from typing import Optional
from sqlmodel import SQLModel

# 수정할 때 받을 데이터 (둘 다 Optional이라서 하나만 보내도 됩니다)
class SolutionUpdate(SQLModel):
    is_selected: Optional[bool] = None
    is_completed: Optional[bool] = None

# 응답으로 줄 데이터 (기존 SolutionLogRead와 비슷하지만, 필요시 분리)
class SolutionRead(SQLModel):
    log_id: int
    diary_id: int
    activity_id: int
    ai_message: Optional[str]
    is_selected: bool
    is_completed: bool