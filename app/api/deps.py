# app/api/deps.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel.ext.asyncio.session import AsyncSession 
import jwt
from app.core.security import SECRET_KEY, ALGORITHM
from database import get_session
# User뿐만 아니라 관계된 모델(Achievement)도 로딩 옵션을 위해 필요할 수 있음
from app.models.tables import User, Achievement 
# 관계 데이터를 미리 로딩하기 위한 도구들
from sqlalchemy.orm import selectinload 
from sqlmodel import select 

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_session)
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

    # ------------------------------------------------------------------
    # [변경 핵심] 단순히 db.get을 쓰면 관계 데이터(취향, 업적)를 못 가져옵니다.
    # selectinload를 사용해 한 번에 묶어서 가져옵니다.
    # ------------------------------------------------------------------
    statement = (
        select(User)
        .where(User.user_id == user_id)
        .options(
            selectinload(User.preference),  # 취향 정보 로딩
            # 업적을 가져오고, 그 업적에 달린 메달 정보까지 연쇄적으로 로딩
            selectinload(User.achievements).selectinload(Achievement.medal)
        )
    )
    
    result = await db.exec(statement)
    user = result.first()
    # ------------------------------------------------------------------

    if user is None:
        raise credentials_exception
        
    return user