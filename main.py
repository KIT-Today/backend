from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import engine
from sqlmodel import SQLModel

# 서버가 시작될 때 DB 테이블을 생성하는 기능
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔄 DB 연결을 시도합니다...")
    try:
        SQLModel.metadata.create_all(engine)
        print("✅ DB 연결 성공!")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
def read_root():
    return {"message": "Hello, Today Project!", "status": "Server is running"}