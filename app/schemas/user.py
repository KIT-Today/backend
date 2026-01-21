from pydantic import BaseModel
from typing import Optional

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