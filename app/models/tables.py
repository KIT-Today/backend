# app/models/tables.py
from typing import Optional, List
from datetime import date, datetime, time
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON, UniqueConstraint  # UniqueConstraint 추가됨

# 1. Users (사용자)
class User(SQLModel, table=True):
    __tablename__ = "users"

    user_id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=100)
    password: Optional[str] = Field(default=None, max_length=255)
    nickname: str = Field(max_length=20)
    
    provider: str = Field(default="LOCAL", max_length=20)
    provider_id: Optional[str] = Field(default=None, max_length=255)
    
    created_at: datetime = Field(default_factory=datetime.now)
    last_att_date: Optional[date] = Field(default=None)
    current_streak: int = Field(default=0)
    
    fcm_token: Optional[str] = Field(default=None, max_length=512)
    is_push_enabled: bool = Field(default=True)

    # 페르소나 (1~5, 선택 안했으면 None)
    persona: Optional[int] = Field(default=None)

    # [추가 1] 데일리 알림 켜짐/꺼짐 여부
    is_daily_alarm_on: bool = Field(default=False)

    # [추가 2] 알림 받을 시간 (예: 22:00:00)
    daily_alarm_time: Optional[time] = Field(default=None)

    # [추가 3] 알림 받을 요일들 (예: [0, 2, 4] -> 월, 수, 금)
    # 0: 월요일 ~ 6: 일요일 (Python datetime 기준)
    daily_alarm_days: List[int] = Field(default=[], sa_column=Column(JSON))

    # 관계 설정 (cascade 옵션 추가)
    diaries: List["Diary"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    attendances: List["Attendance"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    achievements: List["Achievement"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    preference: Optional["UserPreference"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    notification_logs: List["NotificationLog"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

# 2. UserPreferences (취향)
class UserPreference(SQLModel, table=True):
    __tablename__ = "user_preferences"

    pref_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id", unique=True)
    
    is_active: bool = Field(default=False)
    is_outdoor: bool = Field(default=False)
    is_social: bool = Field(default=False)
    
    preferred_tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    user: Optional[User] = Relationship(back_populates="preference")

# 3. Diaries (일기)
class Diary(SQLModel, table=True):
    __tablename__ = "diaries"

    diary_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id", index=True)
    
    content: Optional[str] = Field(default=None, sa_column=Column(Text))
    keywords: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    input_type: str = Field(max_length=10)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    image_url: Optional[str] = Field(default=None, max_length=512)

    user: Optional[User] = Relationship(back_populates="diaries")
  
    emotion_analysis: Optional["EmotionAnalysis"] = Relationship(
        back_populates="diary", 
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    solution_logs: List["SolutionLog"] = Relationship(
        back_populates="diary", 
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

# 4. EmotionAnalysis (감정 분석)
class EmotionAnalysis(SQLModel, table=True):
    __tablename__ = "emotion_analysis"

    analysis_id: Optional[int] = Field(default=None, primary_key=True)
    diary_id: int = Field(foreign_key="diaries.diary_id", index=True)
    
    emotion_probs: dict = Field(sa_column=Column(JSON))
    primary_emotion: str = Field(max_length=20)
    primary_score: float = Field()
    mbi_category: str = Field(default="NONE", max_length=30)
    # ai 메시지가 여기에 있어야 함.
    ai_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=datetime.now)

    diary: Optional[Diary] = Relationship(back_populates="emotion_analysis")

# 5. Activities (솔루션 리스트)
class Activity(SQLModel, table=True):
    __tablename__ = "activities"

    activity_id: Optional[int] = Field(default=None, primary_key=True)
    act_content: str = Field(max_length=255)
    act_category: str = Field(max_length=20)
    
    is_active: bool = Field(default=False)
    is_outdoor: bool = Field(default=False)
    is_social: bool = Field(default=False)

# "지금 이 솔루션을 사용자에게 추천해도 되는가?" (운영 관리용)
    is_enabled: bool = Field(default=True)

# 6. SolutionLogs (솔루션 기록)
class SolutionLog(SQLModel, table=True):
    __tablename__ = "solution_logs"

    log_id: Optional[int] = Field(default=None, primary_key=True)
    diary_id: int = Field(foreign_key="diaries.diary_id", index=True)
    activity_id: int = Field(foreign_key="activities.activity_id")
    is_selected: bool = Field(default=False)
    is_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)

    diary: Optional[Diary] = Relationship(back_populates="solution_logs")
    activity: Optional[Activity] = Relationship(link_model=None)

# 7. Attendance (출석부)
class Attendance(SQLModel, table=True):
    __tablename__ = "attendance"
    
    # 하루에 한 번만 출석 가능하도록 제약조건
    __table_args__ = (
        UniqueConstraint("user_id", "att_date", name="unique_attendance_per_day"),
    )

    att_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id", index=True)
    att_date: date = Field(default_factory=date.today, index=True)
    created_at: datetime = Field(default_factory=datetime.now)

    user: Optional[User] = Relationship(back_populates="attendances")

# 8. Medals (메달 정보)
class Medal(SQLModel, table=True):
    __tablename__ = "medals"

    medal_id: Optional[int] = Field(default=None, primary_key=True)
    medal_code: str = Field(unique=True, max_length=50)
    medal_name: str = Field(max_length=50)
    medal_explain: str = Field(max_length=255)

# 9. Achievements (업적 획득)
class Achievement(SQLModel, table=True):
    __tablename__ = "achievements"

    # 같은 메달 중복 획득 방지 제약조건 
    __table_args__ = (
        UniqueConstraint("user_id", "medal_id", name="unique_medal_per_user"),
    )

    achieve_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id")
    medal_id: int = Field(foreign_key="medals.medal_id")
    
    earned_at: datetime = Field(default_factory=datetime.now)
    is_read: bool = Field(default=False)

    user: Optional[User] = Relationship(back_populates="achievements")
    medal: Optional[Medal] = Relationship(link_model=None)

# 10. PushMessages (문구)
class PushMessage(SQLModel, table=True):
    __tablename__ = "push_messages"

    msg_id: Optional[int] = Field(default=None, primary_key=True)
    msg_content: str = Field(max_length=255)
    category: str = Field(max_length=50)
    created_at: datetime = Field(default_factory=datetime.now)

# 11. NotificationLogs (알림 기록)
class NotificationLog(SQLModel, table=True):
    __tablename__ = "notification_logs"

    log_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id")
    alert_type: str = Field(max_length=50)
    message: str = Field(sa_column=Column(Text))
    sent_at: datetime = Field(default_factory=datetime.now)
    
    msg_id: Optional[int] = Field(default=None, foreign_key="push_messages.msg_id")

    user: Optional[User] = Relationship(back_populates="notification_logs")

# 12. 이메일 인증 번호 저장용
class EmailVerification(SQLModel, table=True):
    __tablename__ = "email_verifications"
    
    email: str = Field(primary_key=True, max_length=100)
    code: str = Field(max_length=6) # 인증번호 6자리
    is_verified: bool = Field(default=False) # 인증 성공 여부
    created_at: datetime = Field(default_factory=datetime.now)