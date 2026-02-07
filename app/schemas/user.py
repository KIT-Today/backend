# app/schemas/user.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

# 1. 회원가입할 때 받을 데이터 (Request)
class UserCreate(BaseModel):
    email: str
    password: str
    nickname: str

# 2. 로그인할 때 받을 데이터 (Request)
class UserLogin(BaseModel):
    email: str
    password: str

# 3. SNS 로그인할 때 받을 데이터 (Request)
class SNSLogin(BaseModel):
    token: str # 프론트엔드가 카카오에서 받아온 액세스 토큰

# 4. 로그인 성공 시 돌려줄 데이터 (Response)
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    nickname: str

# 5. 취향 정보 등록/수정할 때 받을 데이터 (Request)
# 프론트에서 이 정보를 보내면 저장하거나 수정합니다.
class UserPreferenceUpdate(BaseModel):
    # ORM 모드 설정 (이게 있어야 DB 객체를 바로 변환 가능)
    model_config = ConfigDict(from_attributes=True)

    is_active: bool       # 활동적(True) / 정적(False)
    is_outdoor: bool      # 실외(True) / 실내(False)
    is_social: bool       # 함께(True) / 혼자(False)
    preferred_tags: Optional[List[str]] = [] # 선택사항 (없으면 빈 리스트)

# 6. 기본 회원 정보 수정할 때 받을 데이터 (Request)
# 닉네임이나 알림 설정만 쏙 골라서 바꿀 수 있게 Optional로 처리했습니다.
class UserInfoUpdate(BaseModel):
    # 사용자 정보를 수정하고 나서 수정된 정보를 리턴해줄 때, 만약 UserInfoUpdate모델을 그대로 응답 스키마로 쓴다면 문제가 될 수 어서 미리 달아두는 것이 좋다.
    model_config = ConfigDict(from_attributes=True) 

    nickname: Optional[str] = None
    is_push_enabled: Optional[bool] = None
    fcm_token: Optional[str] = None  # 토큰도 갱신할 수 있음.
    persona: Optional[int] = None # 페르소나 변경 가능하도록!


# 7. 앱 처음 화면 문구 응답 전용
class SplashMessageRead(BaseModel):
    msg_content: str   

# 8. 프로필 조회 시 메달 목록
class MedalInfo(BaseModel):
    # 여기도 DB에서 가져온 Achievement 객체를 변환해야 하므로 필요
    model_config = ConfigDict(from_attributes=True)

    achieve_id: int
    medal_name: str
    medal_explain: str
    earned_at: datetime
    is_read: bool

# 9. 내 정보 상세 조회 시 돌려줄 데이터 (Response)
# 프론트엔드 마이페이지에 뿌려줄 정보들의 집합입니다.
class UserProfileResponse(BaseModel):
    # User 객체에서 데이터를 뽑아와야 하므로 필요
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    nickname: str
    current_streak: int      # 연속 출석일 (성취감용)
    is_push_enabled: bool    # 알림 설정 상태 (토글 버튼용)
    
    # 취향 정보도 같이 내려줍니다. (UserPreferenceUpdate 구조 재사용)
    # 아직 취향 설정을 안 했으면 null일 수 있으니 Optional 처리
    preference: Optional[UserPreferenceUpdate] = None

    # 획득한 메달 목록과 읽지 않은 알림 여부
    achievements: List[MedalInfo] = []
    has_unread_medals: bool = False
    # 페르소나의 정보도 제공! 
    persona: Optional[int] = None