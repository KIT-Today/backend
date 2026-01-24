# app/api/user.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
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
from app.services.notification import check_and_send_inactivity_alarms

router = APIRouter()

# 1. 🙋‍♀️ 내 정보 상세 조회 (마이페이지)
@router.get("/profile", response_model=UserProfileResponse)
def read_my_profile(
    current_user: User = Depends(get_current_user)
):
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
def mark_medal_as_read(
    achieve_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    statement = select(Achievement).where(
        Achievement.achieve_id == achieve_id,
        Achievement.user_id == current_user.user_id
    )
    achievement = session.exec(statement).first()
    if not achievement:
        raise HTTPException(status_code=404, detail="기록 없음")
    
    achievement.is_read = True
    session.add(achievement)
    session.commit()
    return {"message": "확인 완료"}



# 2. 🎨 취향 정보 등록 및 수정
@router.post("/preferences")
def update_my_preferences(
    pref_in: UserPreferenceUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    취향 정보를 등록하거나 수정합니다.
    (활동적 여부, 실내외 여부, 태그 등)
    """
    # crud 함수 호출
    result = crud_user.create_or_update_preference(session, current_user.user_id, pref_in)
    return {"message": "취향 정보가 성공적으로 저장되었습니다.", "data": result}



# 3. ⚙️ 기본 정보 수정 (닉네임, 알림, 토큰)
@router.patch("/info")
def update_my_info(
    user_in: UserInfoUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    닉네임이나 알림 설정을 수정합니다.
    - 알림을 켤 때(True)는 fcm_token을 함께 보내주세요.
    - 알림을 끌 때(False)는 자동으로 토큰이 삭제됩니다.
    """
    updated_user = crud_user.update_user_info(session, current_user.user_id, user_in)
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return {
        "message": "회원 정보가 수정되었습니다.",
        "nickname": updated_user.nickname,
        "is_push_enabled": updated_user.is_push_enabled
    }



# 4. 🗑️ 회원 탈퇴
@router.delete("/me")
def delete_my_account(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    서비스에서 탈퇴합니다. 
    작성한 일기, 취향 정보 등 모든 데이터가 함께 삭제됩니다.
    """
    success = crud_user.delete_user(session, current_user.user_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="탈퇴 처리에 실패했습니다.")
        
    return {"message": "회원 탈퇴가 완료되었습니다. 이용해주셔서 감사합니다."}

# 👇 [2. 여기 추가!] 맨 마지막 줄에 이 테스트용 버튼을 붙여넣으세요.
@router.post("/test/send-inactivity-push")
def test_send_inactivity_push(
    db: Session = Depends(get_session)
):
    """
    [테스트용] 3일, 7일, 30일 미접속자에게 알림을 보내고 로그를 쌓습니다.
    (원래는 밤 12시에 자동 실행되지만, 테스트를 위해 수동으로 실행하는 버튼입니다)
    """
    return check_and_send_inactivity_alarms(db)

# 5. 앱 초기 화면에 랜덤 문구 
@router.get("/splash", response_model=SplashMessageRead)
def read_splash_message(db: Session = Depends(get_session)):
    """
    앱 초기 화면(스플래시)에 띄울 랜덤 문구 하나를 가져옵니다.
    """
    message = crud_user.get_random_splash_message(db)
    if not message:
        # 문구가 하나도 없을 경우를 대비한 기본 문구
        return {"msg_content": "오늘도 당신을 기다렸어요."}
    return message
