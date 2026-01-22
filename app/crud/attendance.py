# app/crud/attendance.py
from datetime import date, timedelta
from sqlmodel import Session, select
from fastapi import HTTPException
from app.models.tables import Attendance, User

# 1. 출석 생성 (일기 작성 시 호출)
def create_attendance(db: Session, user_id: int) -> Attendance:
    today = date.today()
    
    # 1. 이미 오늘 출석했는지 확인 (단순 조회라 Lock 불필요)
    existing_att = db.exec(
        select(Attendance)
        .where(Attendance.user_id == user_id)
        .where(Attendance.att_date == today)
    ).first()
    
    if existing_att:
        return existing_att  # 이미 출석 완료

    # 2. 유저 정보 가져오기 (Lock 적용: 동시성 이슈 방지)
    # with_for_update(): 이 트랜잭션이 끝날 때까지 이 유저 정보를 잠금
    statement = select(User).where(User.user_id == user_id).with_for_update()
    user = db.exec(statement).first()
    
    if not user:
        # 유저가 없는 심각한 상황이므로 404 에러 발생
        raise HTTPException(status_code=404, detail="User not found")

    # 3. 스트릭 로직 계산
    # 어제가 마지막 출석일이면 스트릭 +1, 아니면 1로 초기화
    if user.last_att_date == today - timedelta(days=1):
        user.current_streak += 1
    else:
        user.current_streak = 1
    
    user.last_att_date = today
    db.add(user) # 변경 사항 감지 (아직 DB 저장 안 됨)

    # 4. 출석부 도장 찍기
    new_att = Attendance(user_id=user_id, att_date=today)
    db.add(new_att)
    
    # 5. 한 번에 저장 (Transaction Commit)
    # 유저 정보 업데이트와 출석부 생성이 동시에 성공해야 함
    db.commit()      
    db.refresh(new_att)
    
    return new_att

# 2. 월별 출석 조회 
# 해당 월의 시작일과 마지막일 계산은 DB 쿼리에서 처리 (DB 필터링을 사용)
def get_monthly_attendance(db: Session, user_id: int, year: int, month: int) -> list[Attendance]:
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
    
    return db.exec(statement).all()