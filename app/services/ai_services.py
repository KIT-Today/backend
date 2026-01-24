# app/services/ai_services.py
import httpx
import logging

logger = logging.getLogger(__name__)

async def request_diary_analysis(diary_id: int, content: str):
    """
    AI 서버에 분석을 요청합니다. 에러가 발생해도 메인 서비스에는 영향을 주지 않습니다.
    """
    ai_url = "http://ai-server-ip:8000/analyze"
    payload = {"diary_id": diary_id, "content": content}

    async with httpx.AsyncClient() as client:
        try:
            # 타임아웃을 5초로 설정하여 무한 대기를 방지합니다.
            response = await client.post(ai_url, json=payload, timeout=5.0)
            response.raise_for_status()
            logger.info(f"✅ AI 분석 요청 성공: Diary {diary_id}")
        except Exception as e:
            # 여기서 에러가 나도 이미 사용자에게 응답은 나간 상태입니다.
            # 로그만 남기고 나중에 재시도 로직 등을 검토할 수 있습니다.
            logger.error(f"❌ AI 분석 요청 실패 (Diary {diary_id}): {e}")