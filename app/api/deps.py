from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # [변경] 도구 변경
from sqlmodel import Session
import jwt
from app.core.security import SECRET_KEY, ALGORITHM
from database import get_session
from app.models.tables import User

# 복잡한 로그인 방식 대신, 단순하게 "헤더에 있는 토큰"을 가져오는 방식 사용
security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security), # 입력받는 방식 변경
    db: Session = Depends(get_session)
) -> User:
    
    # 토큰 문자열만 쏙 꺼냅니다. (Bearer 글자 제외됨)
    token = credentials.credentials
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명이 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 토큰 해독 (나머지는 기존과 동일)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        
        if user_id is None:
            raise credentials_exception
            
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception
        
    return user