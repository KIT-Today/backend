# app/api/user.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession # [변경] AsyncSession
from sqlmodel import select
from database import get_session
from app.api.deps import get_current_user
from app.models.tables import User, Achievement
from app.schemas.user import (
    UserPreferenceUpdate, 
    UserInfoUpdate, 
    UserProfileResponse, 
    SplashMessageRead,
    MedalInfo
)
from datetime import datetime, timedelta, timezone
from app.crud import user as crud_user
from app.services.notification import check_and_send_inactivity_alarms

router = APIRouter()

# 1. 🙋‍♀️ 내 정보 상세 조회 (마이페이지)
@router.get("/profile", response_model=UserProfileResponse)
async def read_my_profile( # [변경] async
    current_user: User = Depends(get_current_user)
):
    # 관계 데이터 로딩 문제 시 get_current_user에서 selectinload 필요할 수 있음
    # 1. 메달 리스트 변환 (여기는 리스트 컴프리헨션이므로 기존 코드도 OK)
    medal_list = [
        MedalInfo(
            achieve_id=ach.achieve_id,
            medal_name=ach.medal.medal_name,
            medal_explain=ach.medal.medal_explain,
            earned_at=ach.earned_at,
            is_read=ach.is_read
        ) for ach in current_user.achievements
    ]

    # ✅ 안 읽은 메달이 하나라도 있는지 체크
    has_unread = any(not ach.is_read for ach in current_user.achievements)

    # KST 기준 미접속 일수 계산 로직
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).date()
    
    calc_inactive_days = 0
    if current_user.last_att_date:
        calc_inactive_days = max(0, (today - current_user.last_att_date).days)

    # 2. 명시적 매핑
    # UserProfileResponse에 from_attributes=True를 걸었으므로
    # preference에 DB 객체를 그대로 넣어도 Pydantic이 알아서 변환해줍니다.
    return UserProfileResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        nickname=current_user.nickname,
        current_streak=current_user.current_streak,
        is_push_enabled=current_user.is_push_enabled,
        inactive_days=calc_inactive_days,
        preference=current_user.preference, # 이제 객체 그대로 넣어도 OK
        total_medal_count=len(medal_list), # 여기서 개수를 세서 넣어줍니다.
        achievements=medal_list,
        has_unread_medals=has_unread,
        persona=current_user.persona,
        # 아래 내용도 추가함
        is_daily_alarm_on=current_user.is_daily_alarm_on,
        daily_alarm_time=current_user.daily_alarm_time,
        daily_alarm_days=current_user.daily_alarm_days
    )

# 1-2 사용자가 메달 확인 버튼을 눌렀을 때 호출하는 API
@router.patch("/medals/{achieve_id}/read")
async def mark_medal_as_read( 
    achieve_id: int,
    session: AsyncSession = Depends(get_session), 
    current_user: User = Depends(get_current_user)
):
    statement = select(Achievement).where(
        Achievement.achieve_id == achieve_id,
        Achievement.user_id == current_user.user_id
    )
   
    result = await session.exec(statement)
    achievement = result.first()

    if not achievement:
        raise HTTPException(status_code=404, detail="기록 없음")
    
    achievement.is_read = True
    session.add(achievement)
    await session.commit() 
    return {"message": "확인 완료"}


# 2. 🎨 취향 정보 등록 및 수정
@router.post("/preferences")
async def update_my_preferences( 
    pref_in: UserPreferenceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    취향 정보를 등록하거나 수정합니다.
    (활동적 여부, 실내외 여부, 태그 등)
    """
    # crud 함수 호출 (await)
    result = await crud_user.create_or_update_preference(session, current_user.user_id, pref_in)
    return {"message": "취향 정보가 성공적으로 저장되었습니다.", "data": result}


# 3. ⚙️ 기본 정보 수정 (닉네임, 알림, 토큰)
@router.patch("/info")
async def update_my_info( 
    user_in: UserInfoUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    닉네임이나 알림 설정을 수정합니다.
    """
    # crud 호출 (await)
    updated_user = await crud_user.update_user_info(session, current_user.user_id, user_in)
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return {
        "message": "회원 정보가 수정되었습니다.",
        "nickname": updated_user.nickname,
        "is_push_enabled": updated_user.is_push_enabled
    }


# 4. 🗑️ 회원 탈퇴
@router.delete("/me")
async def delete_my_account( 
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    서비스에서 탈퇴합니다. 
    """
    # crud 호출 (await)
    success = await crud_user.delete_user(session, current_user.user_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="탈퇴 처리에 실패했습니다.")
        
    return {"message": "회원 탈퇴가 완료되었습니다. 이용해주셔서 감사합니다."}


# 미접속일 수 강제로 7일로 세팅
from datetime import datetime, timedelta, timezone

@router.patch("/test/force-inactive")
async def force_inactive_days(
    days: int = 7, # 기본값을 7일로 설정
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    [테스트용] 현재 로그인한 유저의 마지막 접속일(last_att_date)을 조작하여
    미접속 일수(inactive_days)를 강제로 세팅하고, 연속 출석(streak)을 초기화합니다.
    """
    # KST 기준 오늘 날짜 구하기
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).date()
    
    # 입력받은 days만큼 과거로 돌림
    target_date = today - timedelta(days=days)
    
    # DB 업데이트: 접속일 조작 및 스트릭 초기화
    current_user.last_att_date = target_date
    current_user.current_streak = 0  # ✨ 스트릭을 0으로 강제 초기화하는 코드 추가!
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    return {
        "message": f"마지막 접속일이 {target_date}로 변경되었고, 연속 출석일이 0으로 초기화되었습니다.",
        "expected_inactive_days": days,
        "current_streak": 0
    }

# 👇 [테스트용 버튼]
@router.post("/test/send-inactivity-push")
async def test_send_inactivity_push( 
    db: AsyncSession = Depends(get_session)
):
    """
    [테스트용] 미접속자 알림 전송 (비동기 함수 호출)
    """
    # [중요] check_and_send_inactivity_alarms 함수도 반드시 async여야 함
    return await check_and_send_inactivity_alarms(db)

# 5. 앱 초기 화면에 랜덤 문구 
@router.get("/splash", response_model=SplashMessageRead)
async def read_splash_message(db: AsyncSession = Depends(get_session)):
    """
    앱 초기 화면(스플래시)에 띄울 랜덤 문구 하나를 가져옵니다.
    """
    # crud 호출 (await)
    message = await crud_user.get_random_splash_message(db)
    if not message:
        return {"msg_content": "오늘도 당신을 기다렸어요."}
    return message

