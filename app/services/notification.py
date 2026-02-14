from datetime import date, datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.tables import User, PushMessage, NotificationLog
from app.core.fcm import send_fcm_notification

# 1. 연속적으로 일기를 작성하지 않았을 때, 알림
async def check_and_send_inactivity_alarms(db: AsyncSession):
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
    
    result = await db.exec(statement)
    users = result.all()
    
    sent_count = 0
    
    for user in users:
        # 2. 미접속 일수 계산
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
        
        if target_msg_id is None:
            continue

        # 4. 보낼 메시지 내용 가져오기
        push_msg = await db.get(PushMessage, target_msg_id)
        if not push_msg:
            continue

        # [수정 완료] 여기에 await를 꼭 붙여야 합니다!
        await send_fcm_notification(
            token=user.fcm_token,
            title="오늘도(Today)",
            body=push_msg.msg_content
        )

        # 5. 로그 저장
        print(f"🚀 [PUSH] To: {user.nickname} | Msg: {push_msg.msg_content}")

        new_log = NotificationLog(
            user_id=user.user_id,
            msg_id=push_msg.msg_id,
            alert_type=alert_type,
            message=push_msg.msg_content,
            sent_at=datetime.now()
        )
        db.add(new_log)
        sent_count += 1

    await db.commit()
    return {"message": f"총 {sent_count}명에게 알림 전송 및 기록 완료"}

# 2. 사용자가 커스텀해서 원하는 시간과 요일에 일기쓰기 알림을 하는 것.
async def send_custom_daily_alarm(db: AsyncSession):
    """
    사용자가 설정한 요일 + 시간에 맞춰 알림을 전송합니다.
    (1분마다 실행됨)
    """
    # 1. 한국 시간 기준 현재 시간 및 요일 구하기
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    
    current_time = now.time().replace(second=0, microsecond=0) # 시:분
    current_weekday = now.weekday() # 0(월) ~ 6(일)

    print(f"⏰ [알림 체크] 시간: {current_time} / 요일: {current_weekday}")

    # 2. 1차 필터링: DB에서 '시간'이 맞는 유저만 일단 다 가져옵니다.
    # (요일 조건인 JSON 필터링은 DB마다 문법이 달라서 파이썬에서 하는 게 안전합니다)
    statement = (
        select(User)
        .where(User.is_push_enabled == True)       # 앱 알림 전체 허용
        .where(User.is_daily_alarm_on == True)     # 데일리 알림 기능 켜짐
        .where(User.daily_alarm_time == current_time) # 시간이 일치함
        .where(User.fcm_token != None)
    )
    
    result = await db.exec(statement)
    candidates = result.all()
    
    sent_count = 0
    
    # 3. 2차 필터링 (Python 레벨): '요일' 확인
    for user in candidates:
        # 유저가 설정한 요일 리스트에 '오늘 요일'이 있는지 확인
        if user.daily_alarm_days and (current_weekday in user.daily_alarm_days):
            
            # 발송! 원하는 문구로 수정 가능!
            success = await send_fcm_notification(
                token=user.fcm_token,
                title="오늘의 하루를 기록해보세요 ✏️",
                body=f"{user.nickname}님, 기다리고 있었어요! 오늘 어떤 일이 있었나요?"
            )
            
            if success:
                print(f"🚀 [CUSTOM ALARM] To: {user.nickname}")
                sent_count += 1

    return sent_count