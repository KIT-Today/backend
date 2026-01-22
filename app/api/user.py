from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from database import get_session
from app.api.deps import get_current_user
from app.models.tables import User
from app.schemas.user import UserPreferenceUpdate, UserInfoUpdate, UserProfileResponse
from app.crud import user as crud_user

router = APIRouter()

# 1. 🙋‍♀️ 내 정보 상세 조회 (마이페이지)
@router.get("/profile", response_model=UserProfileResponse)
def read_my_profile(
    current_user: User = Depends(get_current_user),
):
    """
    내 프로필 정보를 조회합니다. (닉네임, 알림설정, 취향정보 등)
    토큰만 헤더에 넣어서 요청하면 됩니다.
    """
    return current_user



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