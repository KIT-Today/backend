from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Session
from database import engine
from app.api import auth, user, attendance, diary, solution
from app.services.notification import check_and_send_inactivity_alarms

# 1. 스케줄러 설정 (서버 켜지기 전에 미리 준비)
scheduler = BackgroundScheduler()

def scheduled_job():
    print("⏰ [자정 알림 체크] 미접속자 확인 중...")
    with Session(engine) as session:
        check_and_send_inactivity_alarms(session)

# 매일 밤 0시 0분에 실행 (테스트할 땐 주석 풀고 seconds=30 등으로 변경 가능)
scheduler.add_job(scheduled_job, 'cron', hour=18, minute=0)

# 2. 수명 주기 (Lifespan): 서버가 켜질 때와 꺼질 때 할 일
@asynccontextmanager
async def lifespan(app: FastAPI):
    # [시작될 때 할 일]
    print("🚀 DB 테이블 생성 시작...")
    SQLModel.metadata.create_all(engine)
    print("✅ DB 테이블 생성 완료!")
    
    # 스케줄러 켜기 (여기로 이동!)
    scheduler.start()
    print("✅ 자동 알림 스케줄러가 시작되었습니다!")
    
    yield # -------- [여기서 서버가 계속 돌아갑니다] --------
    
    # [꺼질 때 할 일]
    scheduler.shutdown()
    print("💤 자동 알림 스케줄러가 종료되었습니다.")

# 3. FastAPI 앱 생성 (lifespan 적용)
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
app.include_router(auth.router, prefix="/auth", tags=["auth"]) # 로그인 관련
app.include_router(user.router, prefix="/users", tags=["users"]) # 회원 정보 관련
app.include_router(attendance.router, prefix="/attendance", tags=["attendance"]) # 출석 정보 관련
app.include_router(diary.router, prefix="/diaries", tags=["diaries"]) # 일기 관련
app.include_router(solution.router, prefix="/solutions", tags=["solutions"]) # 솔루션 관련

@app.get("/")
def read_root():
    return {"message": "Hello, Today Project! DB is ready."}