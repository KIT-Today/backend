# app/services/email_service.py
import aiosmtplib
from email.message import EmailMessage
import os
import random
import string
from dotenv import load_dotenv

load_dotenv()

# .env에서 가져올 설정값
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def generate_verification_code(length=6):
    """6자리 숫자 인증코드 생성"""
    return ''.join(random.choices(string.digits, k=length))

async def send_verification_email(to_email: str, code: str):
    """이메일로 인증 코드를 전송합니다 (비동기)"""
    # 설정이 없으면 테스트 모드로 동작 (콘솔 출력)
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print(f"⚠️ [TEST MODE] 메일 설정 없음. 인증번호: {code}")
        return True

    message = EmailMessage()
    message["From"] = f"Today App <{EMAIL_USER}>"
    message["To"] = to_email
    message["Subject"] = "[오늘도] 이메일 인증 번호 안내"
    
    html_content = f"""
    <div style='font-family: Arial, sans-serif; padding: 20px; border: 1px solid #ddd;'>
        <h2>이메일 인증</h2>
        <p>안녕하세요, <strong>오늘도(Today)</strong>입니다.</p>
        <p>아래 인증 번호를 앱에 입력해주세요.</p>
        <h1 style='color: #4CAF50; letter-spacing: 5px; background-color: #f9f9f9; padding: 10px; display: inline-block;'>{code}</h1>
        <p>이 코드는 3분간 유효합니다.</p>
    </div>
    """
    message.set_content(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_USER,
            password=EMAIL_PASSWORD
        )
        print(f"✅ 인증 메일 전송 성공: {to_email}")
        return True
    except Exception as e:
        print(f"❌ 인증 메일 전송 실패: {e}")
        return False