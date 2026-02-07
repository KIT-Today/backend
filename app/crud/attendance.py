# app/crud/attendance.py
from datetime import date, timedelta
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from fastapi import HTTPException
from app.models.tables import Attendance, User

# 1. 출석 생성 (비동기)
async def create_attendance(db: AsyncSession, user_id: int) -> Attendance:
    today = date.today()
    
    # 1. 이미 오늘 출석했는지 확인
    statement = select(Attendance).where(Attendance.user_id == user_id).where(Attendance.att_date == today)
    result = await db.exec(statement) 
    existing_att = result.first()
    
    if existing_att:
        return existing_att 

    # 2. 유저 정보 가져오기 (Lock 적용)
    # 비동기에서 with_for_update() 사용 시 주의: 실행 시점에 await
    statement_user = select(User).where(User.user_id == user_id).with_for_update()
    result_user = await db.exec(statement_user) 
    user = result_user.first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. 스트릭 로직 계산
    if user.last_att_date == today - timedelta(days=1):
        user.current_streak += 1
    else:
        user.current_streak = 1
    
    user.last_att_date = today
    db.add(user) # add는 동기 함수라 await 없음

    # 4. 출석부 도장 찍기
    new_att = Attendance(user_id=user_id, att_date=today)
    db.add(new_att)
    
    # 5. 한 번에 저장
    await db.commit()  
    await db.refresh(new_att) 
    
    return new_att

# 2. 월별 출석 조회 (비동기)
async def get_monthly_attendance(db: AsyncSession, user_id: int, year: int, month: int) -> list[Attendance]:
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    statement = (
        select(Attendance)
        .where(Attendance.user_id == user_id)
        .where(Attendance.att_date >= start_date)
        .where(Attendance.att_date < end_date)
        .order_by(Attendance.att_date)
    )
    
    result = await db.exec(statement) 
    return result.all()