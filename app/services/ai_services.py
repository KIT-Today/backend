import httpx
import logging
from database import get_session # 세션 생성 함수 임포트
from app.crud.diary import get_recent_diaries_for_ai

logger = logging.getLogger(__name__)

async def request_diary_analysis(diary_id: int, user_id: int):
    """
    [안전 버전] 2주치 데이터를 모아 AI 서버에 비동기로 분석을 요청합니다.
    """
    ai_url = "http://ai-server-ip:8000/analyze"

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
                "history": history_data # 2주치 전체 데이터 리스트
            }

            # 4. 비동기 HTTP 요청 전송
            async with httpx.AsyncClient() as client:
                response = await client.post(ai_url, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info(f"✅ AI 분석 요청 성공: Diary {diary_id} (History: {len(history_data)}건)")
            
            break # 작업 완료 후 세션 루프 탈출

        except Exception as e:
            logger.error(f"❌ AI 분석 요청 실패 (Diary {diary_id}): {str(e)}")
            break