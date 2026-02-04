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
from app.crud import user as crud_user
# [주의] 이 함수도 아래에서 비동기로 고쳐야 합니다.
from app.services.notification import check_and_send_inactivity_alarms

router = APIRouter()

# 1. 🙋‍♀️ 내 정보 상세 조회 (마이페이지)
@router.get("/profile", response_model=UserProfileResponse)
async def read_my_profile( # [변경] async
    current_user: User = Depends(get_current_user)
):
    # 관계 데이터 로딩 문제 시 get_current_user에서 selectinload 필요할 수 있음
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

    return UserProfileResponse(
        **current_user.dict(), 
        preference=current_user.preference,
        achievements=medal_list,
        has_unread_medals=has_unread
    )

# 1-2 사용자가 메달 확인 버튼을 눌렀을 때 호출하는 API
@router.patch("/medals/{achieve_id}/read")
async def mark_medal_as_read( # [변경] async
    achieve_id: int,
    session: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    statement = select(Achievement).where(
        Achievement.achieve_id == achieve_id,
        Achievement.user_id == current_user.user_id
    )
    # [변경] await exec
    result = await session.exec(statement)
    achievement = result.first()

    if not achievement:
        raise HTTPException(status_code=404, detail="기록 없음")
    
    achievement.is_read = True
    session.add(achievement)
    await session.commit() # [변경] await
    return {"message": "확인 완료"}


# 2. 🎨 취향 정보 등록 및 수정
@router.post("/preferences")
async def update_my_preferences( # [변경] async
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
async def update_my_info( # [변경] async
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
async def delete_my_account( # [변경] async
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

# 👇 [테스트용 버튼]
@router.post("/test/send-inactivity-push")
async def test_send_inactivity_push( # [변경] async
    db: AsyncSession = Depends(get_session)
):
    """
    [테스트용] 미접속자 알림 전송 (비동기 함수 호출)
    """
    # [중요] check_and_send_inactivity_alarms 함수도 반드시 async여야 함
    return await check_and_send_inactivity_alarms(db)

# 5. 앱 초기 화면에 랜덤 문구 
@router.get("/splash", response_model=SplashMessageRead)
async def read_splash_message(db: AsyncSession = Depends(get_session)): # [변경] async
    """
    앱 초기 화면(스플래시)에 띄울 랜덤 문구 하나를 가져옵니다.
    """
    # crud 호출 (await)
    message = await crud_user.get_random_splash_message(db)
    if not message:
        return {"msg_content": "오늘도 당신을 기다렸어요."}
    return message