import os
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import jwt  # PyJWT 라이브러리 사용
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# [수정] .env에서 값 가져오기 (없을 경우를 대비해 기본값 설정)
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_WEEKS = int(os.getenv("ACCESS_TOKEN_EXPIRE_WEEKS", 2))

# 비밀번호 해싱 도구 (Bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    
    # 한국 시간 (KST = UTC + 9시간) 설정
    KST = timezone(timedelta(hours=9))
    expire = datetime.now(KST) + timedelta(weeks=ACCESS_TOKEN_EXPIRE_WEEKS)
    
    to_encode.update({"exp": expire})
    
    # JWT 생성
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt