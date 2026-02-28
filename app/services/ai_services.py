# app/services/ai_services.py
import httpx
import logging
from datetime import datetime # 추가: 날짜 계산을 위해 필요합니다.
from sqlmodel.ext.asyncio.session import AsyncSession
from database import get_session # 세션 생성 함수 임포트
from app.crud.diary import get_recent_diaries_for_ai
from app.models.tables import DiaryFeedback, Diary, User, EmotionAnalysis
from sqlmodel import select

logger = logging.getLogger(__name__)

async def request_diary_analysis(diary_id: int, user_id: int, persona: int):
    """
    [안전 버전] 2주치 데이터를 모아 AI 서버에 비동기로 분석을 요청합니다.
    """
    # 이 주소가 아닐까? -> 확인하고 실제 주소로 변경!
    ai_url = "http://localhost:8001/analyze"

    # API 응답 후에도 안전하게 실행되도록 함수 내부에서 새 세션을 생성합니다.
    async for db in get_session():
        try:
            # 1. 2주치 일기 데이터 가져오기 (await)
            recent_diaries = await get_recent_diaries_for_ai(db, user_id)
            
            # 2. AI 서버 규격에 맞게 가공 (Content + Keywords 포함)
            history_data = [
                {
                    "diary_id": d.diary_id,
                    "content": d.content,
                    "keywords": d.keywords,
                    "created_at": d.created_at.isoformat()
                }
                for d in recent_diaries
            ]

            # 3. Payload 구성
            payload = {
                "diary_id": diary_id,  # 타겟 일기 ID
                "user_id": user_id,
                "persona": persona, # AI 서버에 전달
                "history": history_data # 2주치 전체 데이터 리스트
            }

            # 4. 비동기 HTTP 요청 전송
            async with httpx.AsyncClient() as client:
                response = await client.post(ai_url, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info(f"✅ AI 분석 요청 성공: Diary {diary_id}, , Persona {persona} (History: {len(history_data)}건)")
            
            break # 작업 완료 후 세션 루프 탈출

        except Exception as e:
            logger.error(f"❌ AI 분석 요청 실패 (Diary {diary_id}): {str(e)}")
            break


async def send_feedback_to_ai_server(db: AsyncSession):
    """매일 한 번씩 돌며, 오늘 가입일 기준 14일 주기(14, 28, 42...)가 된 유저의 피드백만 AI 서버로 전송합니다."""
    
    # 1. [수정] select에 EmotionAnalysis.mbi_category 추가 (user_id 제거)
    statement = (
        select(DiaryFeedback, User.created_at, EmotionAnalysis.mbi_category)
        .join(Diary, DiaryFeedback.diary_id == Diary.diary_id)
        .join(User, Diary.user_id == User.user_id) # 기존 User.id 오타를 User.user_id로 변경
        .join(EmotionAnalysis, Diary.diary_id == EmotionAnalysis.diary_id) # 감정 결과 가져오기 위해 조인 추가
        .where(DiaryFeedback.is_sent_to_ai == False)
    )
    result = await db.exec(statement)
    feedbacks_data = result.all()

    if not feedbacks_data:
        print("ℹ️ 전송할 새 피드백이 없습니다.")
        return

    # 2. 오늘 날짜를 기준으로 가입일이 14의 배수인지 확인합니다.
    today = datetime.now().date()
    payload = []
    feedbacks_to_update = [] # 전송 성공 시 업데이트할 피드백 객체들만 따로 모아둡니다.

    # [수정] user_id 대신 predicted_mbi_category로 데이터 받기
    for feedback, created_at, predicted_mbi_category in feedbacks_data: 
        # 가입일만 추출 (시간 제외)
        join_date = created_at.date() if isinstance(created_at, datetime) else created_at
        
        # 가입한 지 며칠 지났는지 계산
        days_since_join = (today - join_date).days

        # 가입일이 오늘(0일)이 아니고, 14의 배수인 경우만 리스트에 추가합니다.
        if days_since_join > 0 and days_since_join % 14 == 0:
            # AI 서버가 요구한 데이터 형식으로 payload 구성 
            payload.append({
                "diary_id": feedback.diary_id,
                "predicted_mbi_category": predicted_mbi_category, 
                "ai_message_rating": feedback.ai_message_rating,
                "mbi_category_rating": feedback.mbi_category_rating
            })
            feedbacks_to_update.append(feedback)

    # 14일 주기인 유저가 없다면 여기서 종료
    if not payload:
        print("ℹ️ 오늘이 가입 14일 주기인 유저 중 전송할 피드백이 없습니다.")
        return

    # 3. AI 서버로 전송
    ai_feedback_url = "http://localhost:8001/feedback/batch" # AI 서버 API 주소
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ai_feedback_url, json={"feedbacks": payload}, timeout=10.0)
            response.raise_for_status()
            
            # 4. 전송 성공 시 상태 업데이트 (걸러진 피드백들만 업데이트)
            for feedback in feedbacks_to_update:
                feedback.is_sent_to_ai = True
                db.add(feedback)
            
            await db.commit()
            print(f"✅ {len(payload)}개의 피드백을 AI 서버로 전송 완료했습니다. (14일 주기 타겟 유저)")
            
    except Exception as e:
        print(f"❌ 피드백 전송 실패: {str(e)}")