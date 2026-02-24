# app/api/auth.py
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession 
from database import get_session
import httpx # requests는 동기 방식이고, httpx는 비동기 방식.

from app.schemas.user import UserCreate, UserLogin, SNSLogin, TokenResponse, EmailRequest, EmailVerifyRequest 
from app.crud import user as crud_user
from app.core.security import verify_password, create_access_token

from app.api.deps import get_current_user
from app.models.tables import User, EmailVerification
from app.services.email_service import generate_verification_code, send_verification_email

# 주소 앞에 /auth가 자동으로 붙습니다. (예: /auth/signup)
router = APIRouter()

# 1. 📝 수동 회원가입 (Local Sign-up)
@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(user_in: UserCreate, db: AsyncSession = Depends(get_session)): 

    # [추가] 이메일 인증이 완료된 상태인지 확인!
    verification = await db.get(EmailVerification, user_in.email)
    if not verification or not verification.is_verified:
         raise HTTPException(status_code=400, detail="이메일 인증이 완료되지 않았습니다.")

    # 1-1. 이미 가입된 이메일인지 확인
    user = await crud_user.get_user_by_email(db, email=user_in.email) 
    if user:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
    
    # 1-2. 가입 진행 (DB 저장)
    new_user = await crud_user.create_user(db, user_in) 

    # [추가] 가입 완료 후 인증 데이터 삭제 (DB 정리)
    await db.delete(verification)
    await db.commit()
    
    # 1-3. 우리 앱 전용 토큰 발급
    access_token = create_access_token({"user_id": new_user.user_id})
    
    # 1-4. 응답 (토큰 + 유저정보)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_user.user_id,
        "email": new_user.email,
        "nickname": new_user.nickname
    }

# 2. 🔐 수동 로그인 (Local Login)
@router.post("/login", response_model=TokenResponse)
async def login(user_in: UserLogin, db: AsyncSession = Depends(get_session)): 
    # 2-1. 이메일로 유저 찾기
    user = await crud_user.get_user_by_email(db, email=user_in.email) 
    if not user:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
    
    # 2-2. 비밀번호 검증 (Local 유저인지도 체크하면 좋음)
    if not verify_password(user_in.password, user.password):
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    
    # 2-3. 토큰 발급
    access_token = create_access_token({"user_id": user.user_id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "email": user.email,
        "nickname": user.nickname
    }

# 3. 🌏 카카오 로그인 (Kakao Login)
@router.post("/kakao", response_model=TokenResponse)
async def kakao_login(sns_in: SNSLogin, db: AsyncSession = Depends(get_session)): 
    # 3-1. 프론트가 준 토큰으로 카카오 서버에 "이 사람 누구야?" 물어보기
    kakao_user_url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {sns_in.token}"}
    
    # [변경] httpx.AsyncClient 사용
    async with httpx.AsyncClient() as client:
        response = await client.get(kakao_user_url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="유효하지 않은 카카오 토큰입니다.")
    
    user_info = response.json()
    
    # 3-2. 카카오 응답에서 정보 추출
    kakao_id = str(user_info.get("id"))
    kakao_account = user_info.get("kakao_account")
    email = kakao_account.get("email")
    nickname = kakao_account.get("profile", {}).get("nickname", "KakaoUser")
    
    if not email:
        raise HTTPException(status_code=400, detail="카카오 계정에 이메일 정보가 없습니다. (동의 항목 확인 필요)")

    # 3-3. 우리 DB에 이메일이 있는지 확인
    user = await crud_user.get_user_by_email(db, email=email) 
    
    if not user:
        # [Case A] 신규 유저 -> 자동 회원가입
        user = await crud_user.create_sns_user(db, email, nickname, "KAKAO", kakao_id) 
    else:
        # [Case B] 기존 유저 -> 로그인 (필요 시 여기서 정보 업데이트 로직 추가 가능)
        pass

    # 3-4. 우리 앱 전용 토큰 발급 (카카오 토큰 아님!)
    access_token = create_access_token({"user_id": user.user_id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "email": user.email,
        "nickname": user.nickname
    } 

# 4. 🙋‍♀️ 내 정보 보기 (프로필 조회)
@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    # 미접속 일수 계산 로직
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).date()
    
    calc_inactive_days = 0
    if current_user.last_att_date:
        calc_inactive_days = max(0, (today - current_user.last_att_date).days)

    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "nickname": current_user.nickname,
        "inactive_days": calc_inactive_days,
    }

# 5. 📧 이메일 인증번호 전송 요청 (추가됨)
@router.post("/email/request")
async def request_email_verification(
    req: EmailRequest, 
    db: AsyncSession = Depends(get_session)
):
    # 이미 가입된 이메일인지 체크
    user = await crud_user.get_user_by_email(db, email=req.email)
    if user:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")

    code = generate_verification_code() # 6자리 생성

    # DB에 저장 (Upsert)
    verification = await db.get(EmailVerification, req.email)
    if not verification:
        verification = EmailVerification(email=req.email, code=code)
    else:
        verification.code = code
        verification.is_verified = False # 재요청했으니 인증 초기화
        verification.created_at = datetime.now()
    
    db.add(verification)
    await db.commit()

    # 이메일 전송
    await send_verification_email(req.email, code)

    return {"message": "인증 번호가 전송되었습니다. 이메일을 확인해주세요."}

# 6. ✅ 이메일 인증번호 검증 (추가됨)
@router.post("/email/verify")
async def verify_email_code(
    req: EmailVerifyRequest,
    db: AsyncSession = Depends(get_session)
):
    verification = await db.get(EmailVerification, req.email)
    
    if not verification:
        raise HTTPException(status_code=400, detail="인증 요청 기록이 없습니다.")

    if verification.code != req.code:
        raise HTTPException(status_code=400, detail="인증 번호가 일치하지 않습니다.")

    # 3분(180초) 제한 체크
    time_diff = datetime.now() - verification.created_at
    if time_diff.total_seconds() > 180: 
        raise HTTPException(status_code=400, detail="인증 시간이 만료되었습니다. 다시 요청해주세요.")

    # 인증 성공 처리
    verification.is_verified = True
    db.add(verification)
    await db.commit()

    return {"message": "이메일 인증이 완료되었습니다."}