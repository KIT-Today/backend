# app/schemas/user.py
from pydantic import BaseModel
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
    is_active: bool       # 활동적(True) / 정적(False)
    is_outdoor: bool      # 실외(True) / 실내(False)
    is_social: bool       # 함께(True) / 혼자(False)
    preferred_tags: Optional[List[str]] = [] # 선택사항 (없으면 빈 리스트)

# 6. 기본 회원 정보 수정할 때 받을 데이터 (Request)
# 닉네임이나 알림 설정만 쏙 골라서 바꿀 수 있게 Optional로 처리했습니다.
class UserInfoUpdate(BaseModel):
    nickname: Optional[str] = None
    is_push_enabled: Optional[bool] = None
    fcm_token: Optional[str] = None  # 토큰도 갱신할 수 있음.


# 7. 앱 처음 화면 문구 응답 전용
class SplashMessageRead(BaseModel):
    msg_content: str   

# 8. 프로필 조회 시 메달 목록
class MedalInfo(BaseModel):
    achieve_id: int
    medal_name: str
    medal_explain: str
    earned_at: datetime
    is_read: bool

# 9. 내 정보 상세 조회 시 돌려줄 데이터 (Response)
# 프론트엔드 마이페이지에 뿌려줄 정보들의 집합입니다.
class UserProfileResponse(BaseModel):
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