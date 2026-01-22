from sqlmodel import Session, select
from app.models.tables import User, UserPreference, PushMessage
from app.schemas.user import UserCreate, UserPreferenceUpdate, UserInfoUpdate
from app.core.security import get_password_hash
from sqlalchemy import func

# 1. 이메일로 유저 찾기 (중복 가입 방지 & 로그인 시 사용)
def get_user_by_email(db: Session, email: str):
    statement = select(User).where(User.email == email)
    # first()는 결과가 있으면 객체를, 없으면 None을 반환합니다.
    return db.exec(statement).first()

# 2. 유저 생성하기 (수동 회원가입용)
def create_user(db: Session, user_in: UserCreate):
    # 비밀번호를 그냥 넣지 않고, 반드시 '암호화'해서 넣습니다.
    hashed_password = get_password_hash(user_in.password)
    
    db_user = User(
        email=user_in.email,
        password=hashed_password,
        nickname=user_in.nickname,
        provider="LOCAL",       # 수동 가입이므로 provider는 LOCAL
        provider_id=None        # SNS ID는 없음
    )
    
    db.add(db_user)     # DB에 추가할 준비
    db.commit()         # 실제 저장 (Commit)
    db.refresh(db_user) # 저장된 정보(ID 등)를 다시 받아옴
    return db_user

# 3. SNS 유저 생성하기 (카카오 로그인 등)
def create_sns_user(db: Session, email: str, nickname: str, provider: str, provider_id: str):
    db_user = User(
        email=email,
        password=None,      # SNS 계정은 비밀번호가 없음 (NULL)
        nickname=nickname,
        provider=provider,  # 예: "KAKAO"
        provider_id=provider_id # 예: "123456789"
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# 4. 🎨 취향 정보 등록 및 수정 (Upsert 패턴)
def create_or_update_preference(session: Session, user_id: int, pref_in: UserPreferenceUpdate):
    """
    사용자의 취향 정보를 등록하거나 수정합니다.
    이미 정보가 있으면 수정(Update), 없으면 새로 등록(Insert) 합니다.
    """
    # 1. 이 유저의 취향 정보가 이미 있는지 확인
    statement = select(UserPreference).where(UserPreference.user_id == user_id)
    preference = session.exec(statement).first()

    if not preference:
        # [CASE 1] 없음 -> 새로 만들기 (Create)
        preference = UserPreference(user_id=user_id, **pref_in.dict())
        session.add(preference)
    else:
        # [CASE 2] 있음 -> 기존 내용 수정하기 (Update)
        preference.is_active = pref_in.is_active
        preference.is_outdoor = pref_in.is_outdoor
        preference.is_social = pref_in.is_social
        preference.preferred_tags = pref_in.preferred_tags
        session.add(preference)
        
    session.commit()
    session.refresh(preference) # DB에 저장된 최신 값을 다시 불러옴
    return preference

# 5. ⚙️ 기본 정보 수정 (닉네임, 알림 설정) + 토큰 삭제 로직
def update_user_info(session: Session, user_id: int, user_in: UserInfoUpdate):
    """
    사용자의 닉네임이나 알림 설정을 수정합니다.
    알림 설정을 끄면(False), FCM 토큰도 함께 삭제합니다.
    """
    user = session.get(User, user_id)
    if not user:
        return None

    # 1. 닉네임 수정 요청이 들어왔다면 변경
    if user_in.nickname is not None:
        user.nickname = user_in.nickname
    
    # 2. 알림 설정 수정 요청이 들어왔다면 변경
    if user_in.is_push_enabled is not None:
        user.is_push_enabled = user_in.is_push_enabled
        
        # 🚨 [중요 로직] 알림을 껐다면(False), 토큰도 삭제(NULL)
        if user_in.is_push_enabled is False:
            user.fcm_token = None

    # 3. 토큰 갱신 로직 (알림 다시 켤 때 사용)
    # 프론트엔드가 토큰을 같이 보내줬다면, 그 값으로 업데이트합니다.
    if user_in.fcm_token is not None:
        user.fcm_token = user_in.fcm_token        
            
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

# 6. 🗑️ 회원 탈퇴 (삭제)
def delete_user(session: Session, user_id: int):
    """
    사용자 계정을 삭제합니다.
    Models에서 설정한 cascade 옵션 덕분에, 
    이 유저가 쓴 일기, 취향 정보 등이 자동으로 같이 삭제됩니다.
    """
    user = session.get(User, user_id)
    if user:
        session.delete(user)
        session.commit()
        return True
    return False

# 7. 앱 처음 화면에 랜덤 문구 조회
def get_random_splash_message(db: Session):
    """
    category가 'SPLASH'인 문구 중 무작위로 하나를 반환합니다.
    """
    statement = (
        select(PushMessage)
        .where(PushMessage.category == "SPLASH")
        .order_by(func.random()) # DB에서 바로 랜덤하게 섞기
        .limit(1)                # 딱 1개만 가져오기
    )
    result = db.exec(statement).first()
    return result