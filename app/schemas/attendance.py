# app/schemas/attendance.py
from datetime import date
from sqlmodel import SQLModel

# 출석 조회 시 반환할 데이터 형태
class AttendanceRead(SQLModel):
    att_date: date
