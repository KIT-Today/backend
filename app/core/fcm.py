# app/core/fcm.py
import firebase_admin
from firebase_admin import credentials, messaging
import os
import anyio # [추가] 비동기 논블로킹 처리를 위한 라이브러리

# 1. 파이어베이스 초기화
if not firebase_admin._apps:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    key_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred)

# [추가] 내부적으로만 쓸 동기 함수 (실제 전송 담당)
def _send_fcm_sync(message):
    return messaging.send(message)

# [변경] 외부에서 호출할 비동기 함수 (async def)
async def send_fcm_notification(token: str, title: str, body: str, data: dict = None):
    """
    진짜 알림을 보내는 함수 (비동기 래퍼, 데이터 페이로드 포함)
    """
    if not token:
        return False
        
    try:
        # 메시지 객체 생성
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data, # 👈 여기에 데이터를 담습니다!
            token=token,
        )
        
        # [핵심] 블로킹 함수(_send_fcm_sync)를 별도 스레드에서 실행하고 기다림
        # 이렇게 해야 서버가 멈추지 않습니다.
        response = await anyio.to_thread.run_sync(_send_fcm_sync, message)
        
        print(f"✅ FCM 전송 성공: {response}")
        return True
    except Exception as e:
        print(f"⛔ FCM 전송 실패: {e}")
        return False