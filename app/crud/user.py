# app/crud/user.py
# [추가] S3 삭제 함수 임포트
from app.services.s3_service import delete_image_from_s3
# [추가] anyio 임포트 (동기 함수인 delete_image_from_s3를 비동기로 돌리기 위해)
import anyio
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.models.tables import User, UserPreference, PushMessage, Diary, EmotionAnalysis, Medal, Achievement
from app.schemas.user import UserCreate, UserPreferenceUpdate, UserInfoUpdate
from app.core.security import get_password_hash
from sqlalchemy import func, desc

# 1. 이메일로 유저 찾기 (중복 가입 방지 & 로그인 시 사용)
async def get_user_by_email(db: AsyncSession, email: str):
    statement = select(User).where(User.email == email)
   
    result = await db.exec(statement)
    return result.first()

# 2. 유저 생성하기 (수동 회원가입용)
async def create_user(db: AsyncSession, user_in: UserCreate):
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=user_in.email,
        password=hashed_password,
        nickname=user_in.nickname,
        provider="LOCAL",
        provider_id=None
    )
    db.add(db_user)
    await db.commit()  
    await db.refresh(db_user) 
    return db_user

# 3. SNS 유저 생성하기 (카카오 로그인 등)
async def create_sns_user(db: AsyncSession, email: str, nickname: str, provider: str, provider_id: str):
    db_user = User(
        email=email,
        password=None,
        nickname=nickname,
        provider=provider,
        provider_id=provider_id
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

# 4. 🎨 취향 정보 등록 및 수정 (Upsert 패턴)
async def create_or_update_preference(session: AsyncSession, user_id: int, pref_in: UserPreferenceUpdate):
    statement = select(UserPreference).where(UserPreference.user_id == user_id)
    result = await session.exec(statement)
    preference = result.first()

    if not preference:
        preference = UserPreference(user_id=user_id, **pref_in.model_dump())
        session.add(preference)
    else:
        preference.is_active = pref_in.is_active
        preference.is_outdoor = pref_in.is_outdoor
        preference.is_social = pref_in.is_social
        preference.preferred_tags = pref_in.preferred_tags
        session.add(preference)
        
    await session.commit()
    await session.refresh(preference)
    return preference

# 5. ⚙️ 기본 정보 수정 (닉네임, 알림 설정) + 토큰 삭제 로직
async def update_user_info(session: AsyncSession, user_id: int, user_in: UserInfoUpdate):
    user = await session.get(User, user_id)
    if not user:
        return None

    if user_in.nickname is not None:
        user.nickname = user_in.nickname

    # 페르소나 변경 로직
    if user_in.persona is not None:
        user.persona = user_in.persona
    
    if user_in.is_push_enabled is not None:
        user.is_push_enabled = user_in.is_push_enabled
        if user_in.is_push_enabled is False:
            user.fcm_token = None

    if user_in.fcm_token is not None:
        user.fcm_token = user_in.fcm_token        
            
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

# 6. 🗑️ 회원 탈퇴 (삭제)
async def delete_user(session: AsyncSession, user_id: int):
    # 1. 유저 조회
    user = await session.get(User, user_id)
    if not user:
        return False

    # -------------------------------------------------------------
    # [추가된 로직] S3 이미지 삭제
    # DB에서 유저가 삭제되면(Cascade) 일기 데이터도 사라져서 URL을 알 수 없게 됩니다.
    # 따라서 DB 삭제 전에 먼저 일기 목록을 조회해서 S3 파일을 지워야 합니다.
    # -------------------------------------------------------------
    
    # 2. 유저의 모든 일기 조회
    statement = select(Diary).where(Diary.user_id == user_id)
    result = await session.exec(statement)
    diaries = result.all()

    # 3. 일기 하나하나 확인하며 이미지 삭제
    for diary in diaries:
        if diary.image_url:
            # S3 삭제 함수(boto3)는 동기 방식이라 서버가 멈출 수 있으므로,
            # anyio.to_thread.run_sync를 사용해 비동기적으로 처리합니다.
            try:
                await anyio.to_thread.run_sync(delete_image_from_s3, diary.image_url)
            except Exception as e:
                # 이미지가 없거나 에러가 나도 회원 탈퇴는 진행되어야 하므로 로그만 찍고 넘어감
                print(f"⚠️ S3 이미지 삭제 실패 (무시하고 진행): {e}")

    # -------------------------------------------------------------

    # 4. DB 데이터 삭제 
    # (User 모델에 설정된 cascade="all, delete-orphan" 덕분에 DB 내의 일기, 출석 등은 자동 삭제됨)
    await session.delete(user)
    await session.commit()
    
    return True

# 7. 앱 처음 화면에 랜덤 문구 조회
async def get_random_splash_message(db: AsyncSession):
    statement = (
        select(PushMessage)
        .where(PushMessage.category == "SPLASH")
        .order_by(func.random())
        .limit(1)
    )
    result = await db.exec(statement)
    return result.first()

# 8. 메달 체크 로직 (전 일기에서 비해 normal이 나온 경우)
async def check_and_award_recovery_medal(session: AsyncSession, user_id: int):
    """
    번아웃 상태(EE, DP, PA_LOW)에서 NORMAL로 개선 시 메달 수여 (비동기 버전)
    """
    # 1. 최근 감정 분석 결과 2개 조회
    statement = (
        select(EmotionAnalysis)
        .join(Diary)
        .where(Diary.user_id == user_id)
        .order_by(desc(EmotionAnalysis.created_at))
        .limit(2)
    )
    # await로 실행하고 결과 받기
    result_emotions = await session.exec(statement)
    results = result_emotions.all()

    if len(results) < 2:
        return None

    current = results[0]   # 이번 분석
    previous = results[1]  # 직전 분석

    # 2. 상태 개선 조건 체크 (Burnout -> NORMAL)
    burnout_states = ["EE", "DP", "PA_LOW"]
    if previous.mbi_category in burnout_states and current.mbi_category == "NORMAL":
        
        # 3. 메달 마스터 정보 가져오기
        # await session.exec(...)
        medal_stmt = select(Medal).where(Medal.medal_code == "RECOVERY_LIGHT")
        medal_result = await session.exec(medal_stmt)
        medal = medal_result.first()
        
        if not medal: return None

        # 4. 중복 획득 방지 (UniqueConstraint 준수)
        check_stmt = select(Achievement).where(
            Achievement.user_id == user_id,
            Achievement.medal_id == medal.medal_id
        )
        already_has_result = await session.exec(check_stmt)
        already_has = already_has_result.first()

        # 5. 아직 없는 메달일 때만 획득 처리
        if not already_has:
            new_achievement = Achievement(
                user_id=user_id,
                medal_id=medal.medal_id,
                is_read=False
            )
            session.add(new_achievement)
            await session.commit() # await 필수!
            return medal
            
    return None