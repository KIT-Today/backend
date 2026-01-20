from sqlmodel import SQLModel, create_engine, Session
import os
from dotenv import load_dotenv

# 1. .env 파일에서 비밀 정보 가져오기
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT")

# 2. 데이터베이스 연결 주소 만들기
# 형식: postgresql://아이디:비번@주소:포트/DB이름
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 3. 엔진 생성 (실제 연결 담당)
# echo=True 옵션: DB가 무슨 일을 하는지 터미널에 로그를 보여줌 (개발할 때 좋음)
engine = create_engine(DATABASE_URL, echo=True)

# 4. 세션 생성 함수 (나중에 API에서 DB를 쓸 때마다 이 함수를 호출함)
def get_session():
    with Session(engine) as session:
        yield session