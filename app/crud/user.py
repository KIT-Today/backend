from sqlmodel import Session, select
from app.models.tables import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash

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