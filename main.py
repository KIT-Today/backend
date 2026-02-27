# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel
from app.models.tables import *

# 비동기 스케줄러 라이브러리 사용
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# engine과 async_session_maker 가져오기
from database import engine, async_session_maker 
from app.api import auth, user, attendance, diary, solution, activity
from app.services.notification import check_and_send_inactivity_alarms, send_custom_daily_alarm

from app.services.ai_services import send_feedback_to_ai_server

# 1. 비동기 스케줄러 설정
scheduler = AsyncIOScheduler()

# 스케줄러가 실행할 함수 (비동기 세션 직접 생성)
async def scheduled_job():
    print("⏰ [자정 알림 체크] 미접속자 확인 중...")
    # 라우터가 아니므로 Depends를 못 씁니다. 직접 세션을 엽니다.
    async with async_session_maker() as session:
        await check_and_send_inactivity_alarms(session)

# 1분마다 실행될 래퍼 함수
async def scheduled_custom_alarm_job():
    async with async_session_maker() as session:
        await send_custom_daily_alarm(session)

# ai서버로 피드백 전송
async def scheduled_feedback_job():
    print("⏰ [피드백 전송] AI 서버로 피드백 데이터 전송 시도 중...")
    async with async_session_maker() as session:
        await send_feedback_to_ai_server(session)          

# 2. 수명 주기 (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # [시작될 때 할 일]
    print("🚀 DB 테이블 생성 시작...")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    print("✅ DB 테이블 생성 완료!")
    
    # 스케줄러 작업 등록 및 시작
    # (테스트를 위해 매분 0초마다 실행되게 설정했습니다. 원하시면 hour=0, minute=0으로 바꾸세요)
    # scheduler.add_job(scheduled_job, 'cron', hour=0, minute=0)  # 원래 설정
    scheduler.add_job(scheduled_job, 'cron', hour=18, minute=30) # 테스트용 예시

    # 2. 사용자 설정 알림 (1분마다 체크)
    # 1분마다 돌면서 "지금 보내야 할 사람 있나?" 확인합니다.
    scheduler.add_job(scheduled_custom_alarm_job, 'cron', minute='*')

    # 3. [수정됨] AI 서버로 피드백 전송 (매일 새벽 2시에 실행하여 14일 주기 대상자 탐색)
    scheduler.add_job(scheduled_feedback_job, 'cron', hour=2, minute=0)
    
    # 💡 [테스트용 팁] 당장 1분마다 잘 걸러지는지 테스트하고 싶다면 아래 코드를 주석 해제해서 사용하세요!
    # scheduler.add_job(scheduled_feedback_job, 'cron', minute='*')
    
    scheduler.start()
    print("✅ 자동 알림 스케줄러가 시작되었습니다!")
    
    yield # -------- [여기서 서버가 계속 돌아갑니다] --------
    
    # [꺼질 때 할 일]
    scheduler.shutdown()
    print("💤 자동 알림 스케줄러가 종료되었습니다.")  

# 3. FastAPI 앱 생성
app = FastAPI(lifespan=lifespan)

# 4. CORS 설정
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. 라우터 등록
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(user.router, prefix="/users", tags=["users"])
app.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
app.include_router(diary.router, prefix="/diaries", tags=["diaries"])
app.include_router(solution.router, prefix="/solutions", tags=["solutions"])
app.include_router(activity.router, prefix="/activities", tags=["activities"])

@app.get("/")
def read_root():
    return {"message": "Hello, Today Project! Async Server is ready."}