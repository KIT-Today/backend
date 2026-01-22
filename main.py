from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # [필수] 이거 꼭 추가해야 함!
from sqlmodel import SQLModel
from database import engine
from app.models import tables 
from app.api import auth, user, attendance

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 DB 테이블 생성 시작...")
    # [설명] 이미 테이블이 있으면 건너뛰고, 없으면 새로 만듭니다.
    SQLModel.metadata.create_all(engine)
    print("✅ DB 테이블 생성 완료!")
    yield

app = FastAPI(lifespan=lifespan)

# CORS 설정
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

# 라우터 등록 (이 줄이 없으면 API가 작동 안 함!)
app.include_router(auth.router, prefix="/auth", tags=["auth"])       # 로그인 관련
app.include_router(user.router, prefix="/users", tags=["users"])     # 회원 정보 관련
app.include_router(attendance.router, prefix="/attendance", tags=["attendance"]) # 출석 정보 관련

@app.get("/")
def read_root():
    return {"message": "Hello, Today Project! DB is ready."}