# database.py
# 1. 엔진 생성을 위한 도구 (SQLAlchemy)
from sqlalchemy.ext.asyncio import create_async_engine
# 2. 세션 생성을 위한 도구 (SQLAlchemy)
from sqlalchemy.orm import sessionmaker
# 3. 비동기 세션 객체 (반드시 SQLModel 것을 사용!)
from sqlmodel.ext.asyncio.session import AsyncSession

import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT")

# 1. 비동기용 주소 (postgresql+asyncpg 사용)
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 2. 비동기 엔진 생성
engine = create_async_engine(DATABASE_URL, echo=True)

# 3. 비동기 세션 팩토리 설정
async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# 4. 비동기 세션 생성 함수 (get_session)
async def get_session():
    async with async_session_maker() as session:
        yield session