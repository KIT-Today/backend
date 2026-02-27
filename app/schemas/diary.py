# app/schemas/diary.py
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel
from pydantic import model_validator # [중요] 여기서 가져옴

# --- [하위 모델] 읽기 전용 (AI 분석 결과) 조회 응답 (백엔드 -> 프론트) ---
class EmotionAnalysisRead(SQLModel):
    primary_emotion: str
    primary_score: float
    mbi_category: str
    ai_message: Optional[str] = None #프론트에게 AI메시지 전달
    emotion_probs: Dict[str, Any]

class SolutionLogRead(SQLModel):
    log_id: int
    activity_id: int
    act_content: str
    is_selected: bool
    is_completed: bool

    # DB 객체를 직접 수정하지 않고, 필요한 내용만 딕셔너리에 담아 반환
    @model_validator(mode='before')
    @classmethod
    def map_activity_content(cls, v: Any) -> Any:
        # 들어온 데이터가 딕셔너리가 아니라 DB 객체(SolutionLog)일 때만 처리
        if getattr(v, '__class__', None) and v.__class__.__name__ == 'SolutionLog':
            # activity 데이터가 있으면 가져오고, 없으면 빈칸("")으로 처리해서 에러 방지
            act_content = v.activity.act_content if getattr(v, 'activity', None) else ""
            
            # Pydantic이 안전하게 읽을 수 있도록 파이썬 딕셔너리 형태로 만들어서 넘겨줌
            return {
                "log_id": v.log_id,
                "activity_id": v.activity_id,
                "act_content": act_content,
                "is_selected": v.is_selected,
                "is_completed": v.is_completed,
            }
        return v

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
    image_url: Optional[str] = None 
    created_at: datetime

    # 분석 결과가 존재하는지 여부를 프론트가 쉽게 알게 함 -- 이거 추가함
    is_analyzed: bool = False
    
    # [관계 데이터] 없으면 null 또는 빈 리스트로 나감
    emotion_analysis: Optional[EmotionAnalysisRead] = None 
    solution_logs: List[SolutionLogRead] = []

    # SQLModel 객체를 넘길 때 분석 데이터가 있으면 True로 설정하는 로직 -- 이거 추가함
    @model_validator(mode='after')
    def set_analyzed_status(self):
        self.is_analyzed = self.emotion_analysis is not None
        return self

# # --- AI 분석 결과 수신용 (AI 서버 -> 백엔드) ---    
# # 추천 솔루션 하나하나를 정의하는 작은 모델
# class AIRecommendation(SQLModel):
#     activity_id: int  # 솔루션 ID

# (수정 후)
class AIRecommendation(SQLModel):
    act_content: str       # LLM이 생성한 엑티비티 내용
    act_category: str      # (선택) LLM이 분류해 준 카테고리
    # 🚀 AI가 이 액티비티의 성향을 분석해서 같이 넘겨주도록 추가!
    is_active: bool
    is_outdoor: bool
    is_social: bool

# 전체 결과 (리스트로 받도록 변경)
class AIAnalysisResult(SQLModel):
    diary_id: int
    
    # 1) 감정 분석 결과
    primary_emotion: str
    primary_score: float
    mbi_category: str
    emotion_probs: Dict[str, Any]
    # AI 서버는 결과 꾸러미에 AI메시지를 담아 줍니다.
    ai_message: str
    
    # 2) 추천 솔루션 정보
    recommendations: List[AIRecommendation]