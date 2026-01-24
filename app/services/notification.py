# app/sercices/notification.py
from datetime import date, datetime
from sqlmodel import Session, select
from app.models.tables import User, PushMessage, NotificationLog
from app.core.fcm import send_fcm_notification

def check_and_send_inactivity_alarms(db: Session):
    """
    모든 유저를 검사해서 3일, 7일, 30일 미접속자에게 알림을 전송하고 기록합니다.
    """
    today = date.today()
    
    # 1. 알림 켜짐(True) AND 토큰 있음 AND 마지막 접속일 있음 -> 유저 조회
    statement = (
        select(User)
        .where(User.is_push_enabled == True)
        .where(User.fcm_token != None)
        .where(User.last_att_date != None)
    )
    users = db.exec(statement).all()
    
    sent_count = 0
    
    for user in users:
        # 2. 미접속 일수 계산 (오늘 - 마지막 출석)
        diff_days = (today - user.last_att_date).days
        
        target_msg_id = None
        alert_type = ""

        # 3. 조건 체크
        if diff_days == 3:
            target_msg_id = 1
            alert_type = "3_DAYS_INACTIVE"
        elif diff_days == 7:
            target_msg_id = 2
            alert_type = "7_DAYS_INACTIVE"
        elif diff_days == 30:
            target_msg_id = 3
            alert_type = "30_DAYS_INACTIVE"
        
        # 해당되는 날짜가 아니면 다음 사람으로 넘어감
        if target_msg_id is None:
            continue

        # 4. 보낼 메시지 내용 가져오기
        push_msg = db.get(PushMessage, target_msg_id)
        if not push_msg:
            continue

        # [수정된 부분] 진짜 FCM 보내기!
        send_fcm_notification(
            token=user.fcm_token,
            title="오늘도(Today)",  # 앱 이름
            body=push_msg.msg_content
        )

        # 5. 보낸 거 서버 로그
        print(f"🚀 [PUSH] To: {user.nickname} | Msg: {push_msg.msg_content}")

        # 6. 로그 저장 (NotificationLogs)
        new_log = NotificationLog(
            user_id=user.user_id,
            msg_id=push_msg.msg_id,
            alert_type=alert_type,
            message=push_msg.msg_content,
            sent_at=datetime.now()
        )
        db.add(new_log)
        sent_count += 1

    db.commit()
    return {"message": f"총 {sent_count}명에게 알림 전송 및 기록 완료"}