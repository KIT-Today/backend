# app/core/fcm.py
import firebase_admin
from firebase_admin import credentials, messaging
import os

# 1. 파이어베이스 초기화
# serviceAccountKey.json 파일이 main.py랑 같은 위치에 있어야 함!
if not firebase_admin._apps:
    # 현재 파일 위치 기준으로 상위 폴더의 serviceAccountKey.json 찾기 (경로 에러 방지용)
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    key_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred)

def send_fcm_notification(token: str, title: str, body: str):
    """
    진짜 알림을 보내는 함수 (우체부 아저씨)
    """
    if not token:
        return False
        
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
        )
        response = messaging.send(message)
        print(f"✅ FCM 전송 성공: {response}")
        return True
    except Exception as e:
        print(f"⛔ FCM 전송 실패: {e}")
        return False