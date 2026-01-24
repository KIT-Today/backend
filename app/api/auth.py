# app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from database import get_session
import requests

from app.schemas.user import UserCreate, UserLogin, SNSLogin, TokenResponse
from app.crud import user as crud_user
from app.core.security import verify_password, create_access_token

from app.api.deps import get_current_user
from app.models.tables import User

# 주소 앞에 /auth가 자동으로 붙습니다. (예: /auth/signup)
router = APIRouter()

# 1. 📝 수동 회원가입 (Local Sign-up)
@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(user_in: UserCreate, db: Session = Depends(get_session)):
    # 1-1. 이미 가입된 이메일인지 확인
    user = crud_user.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
    
    # 1-2. 가입 진행 (DB 저장)
    new_user = crud_user.create_user(db, user_in)
    
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
def login(user_in: UserLogin, db: Session = Depends(get_session)):
    # 2-1. 이메일로 유저 찾기
    user = crud_user.get_user_by_email(db, email=user_in.email)
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
def kakao_login(sns_in: SNSLogin, db: Session = Depends(get_session)):
    # 3-1. 프론트가 준 토큰으로 카카오 서버에 "이 사람 누구야?" 물어보기
    kakao_user_url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {sns_in.token}"}
    
    try:
        response = requests.get(kakao_user_url, headers=headers)
        response.raise_for_status() # 에러 발생 시 예외 처리
    except Exception:
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
    user = crud_user.get_user_by_email(db, email=email)
    
    if not user:
        # [Case A] 신규 유저 -> 자동 회원가입
        user = crud_user.create_sns_user(db, email, nickname, "KAKAO", kakao_id)
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

# 4. 🌏 구글 로그인 (Google Login)
@router.post("/google", response_model=TokenResponse)
def google_login(sns_in: SNSLogin, db: Session = Depends(get_session)):
    google_user_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    response = requests.get(google_user_url, params={"access_token": sns_in.token})
    
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="유효하지 않은 구글 토큰입니다.")
    
    user_info = response.json()
    
    google_id = user_info.get("id")
    email = user_info.get("email")
    nickname = user_info.get("name", "GoogleUser")
    
    if not email:
        raise HTTPException(status_code=400, detail="구글 계정에 이메일 정보가 없습니다.")

    user = crud_user.get_user_by_email(db, email=email)
    
    if not user:
        user = crud_user.create_sns_user(db, email, nickname, "GOOGLE", google_id)
    
    access_token = create_access_token({"user_id": user.user_id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "email": user.email,
        "nickname": user.nickname
    }

# 5. 🌏 네이버 로그인 (Naver Login)
@router.post("/naver", response_model=TokenResponse)
def naver_login(sns_in: SNSLogin, db: Session = Depends(get_session)):
    naver_user_url = "https://openapi.naver.com/v1/nid/me"
    headers = {"Authorization": f"Bearer {sns_in.token}"}
    
    response = requests.get(naver_user_url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="유효하지 않은 네이버 토큰입니다.")
    
    user_info = response.json()
    
    naver_response = user_info.get("response")
    if not naver_response:
        raise HTTPException(status_code=400, detail="네이버 응답 형식이 올바르지 않습니다.")
        
    naver_id = naver_response.get("id")
    email = naver_response.get("email")
    nickname = naver_response.get("nickname", "NaverUser")
    
    if not email:
        raise HTTPException(status_code=400, detail="네이버 계정에 이메일 정보가 없습니다.")

    user = crud_user.get_user_by_email(db, email=email)
    
    if not user:
        user = crud_user.create_sns_user(db, email, nickname, "NAVER", naver_id)
    
    access_token = create_access_token({"user_id": user.user_id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "email": user.email,
        "nickname": user.nickname
    }

# 6. 🙋‍♀️ 내 정보 보기 (프로필 조회)
# 이 기능은 앱 실행 시 '자동 로그인' 처리를 위해 필수입니다!
@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "nickname": current_user.nickname,
    }