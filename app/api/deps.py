from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession # [변경] AsyncSession 사용
import jwt
from app.core.security import SECRET_KEY, ALGORITHM
from database import get_session
from app.models.tables import User

security = HTTPBearer()

# [변경] async def로 선언
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_session) # [변경] AsyncSession
) -> User:
    
    token = credentials.credentials
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명이 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        
        if user_id is None:
            raise credentials_exception
            
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise credentials_exception

    # [변경] 비동기 조회 (await db.get)
    user = await db.get(User, user_id)
    if user is None:
        raise credentials_exception
        
    return user