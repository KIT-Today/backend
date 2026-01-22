from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel
from pydantic import model_validator # [중요] 여기서 가져옴

# --- [하위 모델] 읽기 전용 (AI 분석 결과) 조회 응답 (백엔드 -> 프론트) ---
class EmotionAnalysisRead(SQLModel):
    primary_emotion: str
    primary_score: float
    mbi_category: str
    emotion_probs: Dict[str, Any]

class SolutionLogRead(SQLModel):
    log_id: int
    ai_message: Optional[str]
    is_selected: bool
    is_completed: bool

# --- [메인 모델] 일기 ---

# 1. 기본 속성
class DiaryBase(SQLModel):
    input_type: str  # 'TEXT', 'KEYWORD', 'HYBRID'
    content: Optional[str] = None
    keywords: Optional[Dict[str, Any]] = None

# 2. 생성 요청 (프론트 -> 백엔드)
class DiaryCreate(DiaryBase):
    # [수정 포인트] mode='after'를 쓰고, self로 접근합니다.
    @model_validator(mode='after')
    def validate_content_or_keywords(self):
        # self.content와 self.keywords로 내 값을 직접 확인합니다.
        if not self.content and not self.keywords:
            raise ValueError("일기 내용(content)이나 키워드(keywords) 중 하나는 반드시 입력해야 합니다.")
        return self

# 3. 수정 요청 (프론트 -> 백엔드)
class DiaryUpdate(SQLModel):
    input_type: Optional[str] = None
    content: Optional[str] = None
    keywords: Optional[Dict[str, Any]] = None

# 4. 조회 응답 (백엔드 -> 프론트)
class DiaryRead(DiaryBase):
    diary_id: int
    user_id: int
    created_at: datetime
    
    # [관계 데이터] 없으면 null 또는 빈 리스트로 나감
    emotion_analysis: Optional[EmotionAnalysisRead] = None 
    solution_logs: List[SolutionLogRead] = []

# --- AI 분석 결과 수신용 (AI 서버 -> 백엔드) ---    
class AIAnalysisResult(SQLModel):
    diary_id: int
    
    # 1) 감정 분석 결과
    primary_emotion: str
    primary_score: float
    mbi_category: str
    emotion_probs: Dict[str, Any]
    
    # 2) 추천 솔루션 정보
    activity_id: int  # 솔루션 ID
    ai_message: str   # AI 메시지