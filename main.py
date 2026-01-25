# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

# [수정] 비동기 스케줄러 라이브러리 사용
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# [수정] engine과 async_session_maker 가져오기
from database import engine, async_session_maker 
from app.api import auth, user, attendance, diary, solution
from app.services.notification import check_and_send_inactivity_alarms

# 1. 비동기 스케줄러 설정
scheduler = AsyncIOScheduler()

# [수정] 스케줄러가 실행할 함수 (비동기 세션 직접 생성)
async def scheduled_job():
    print("⏰ [자정 알림 체크] 미접속자 확인 중...")
    # 라우터가 아니므로 Depends를 못 씁니다. 직접 세션을 엽니다.
    async with async_session_maker() as session:
        await check_and_send_inactivity_alarms(session)

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

@app.get("/")
def read_root():
    return {"message": "Hello, Today Project! Async Server is ready."}