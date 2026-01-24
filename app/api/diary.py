# app/api/diary.py
# 1. FastAPI 관련 도구들
import anyio
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
import json
from fastapi import UploadFile, File, Form, HTTPException, BackgroundTasks # 추가
from app.services.s3_service import upload_image_to_s3, delete_image_from_s3
from app.services.ai_services import request_diary_analysis

# 2. DB 관련 도구들
from sqlmodel import Session, func, select # func, select 꼭 필요함!
from database import get_session

# 3. 인증 관련
from app.api.deps import get_current_user

# 4. 모델(Tables) & 스키마(Schemas)
from app.models.tables import User, Diary, EmotionAnalysis, SolutionLog # 테이블들
from app.schemas.diary import (
    DiaryCreate, 
    DiaryRead, 
    DiaryUpdate, 
    AIAnalysisResult # 아까 만든 AI용 스키마
)
from app.crud import diary as crud_diary

router = APIRouter()

# 1. 일기 등록 
@router.post("/", response_model=DiaryRead)
async def create_diary(
    background_tasks: BackgroundTasks,
    input_type: str = Form(...),
    content: Optional[str] = Form(None),
    keywords_json: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # 📸 이미지 업로드 처리
    image_url = None
    if image:
        image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    # 🔍 키워드 JSON 파싱
    keywords = json.loads(keywords_json) if keywords_json else None

    # 📝 일기 데이터 생성 및 검증
    diary_in = DiaryCreate(input_type=input_type, content=content, keywords=keywords)
    
    # 💾 DB 저장 및 출석 체크 (통합 트랜잭션 수행)
    db_diary = crud_diary.create_diary(db, diary_in, current_user.user_id, image_url)

    # 🚀 AI 분석 백그라운드 작업 예약
    analysis_input = db_diary.content or str(db_diary.keywords)
    if analysis_input:
        background_tasks.add_task(request_diary_analysis, db_diary.diary_id, analysis_input)

    return db_diary



# 2. 일기 목록 조회 (GET /diaries/)
@router.get("/", response_model=List[DiaryRead])
def read_diaries(
    skip: int = 0,
    limit: int = 10,
    year: Optional[int] = Query(None, description="필터링할 연도 (예: 2026)"),
    month: Optional[int] = Query(None, description="필터링할 월 (예: 1)"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    내 일기 목록을 최신순으로 조회합니다.
    - year만 입력: 해당 연도 전체
    - year + month 입력: 해당 연도의 특정 월
    - 둘 다 미입력: 전체 일기 (페이징)
    """
    return crud_diary.get_diaries(
        db, 
        user_id=current_user.user_id, 
        skip=skip, 
        limit=limit, 
        year=year, 
        month=month
    )

# 3. 일기 상세 조회 (GET /diaries/{diary_id})
@router.get("/{diary_id}", response_model=DiaryRead)
def read_diary(
    diary_id: int = Path(..., description="조회할 일기 ID"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기 상세 내용을 조회합니다.
    (감정 분석 결과나 솔루션이 있으면 같이 나오고, 없으면 비어서 나옵니다)
    """
    return crud_diary.get_diary(db, diary_id, current_user.user_id)

# 4. 일기 수정 
@router.patch("/{diary_id}", response_model=DiaryRead)
async def update_diary(
    diary_id: int,
    background_tasks: BackgroundTasks,
    input_type: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    keywords_json: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # 1. 기존 데이터 조회
    db_diary = crud_diary.get_diary(db, diary_id, current_user.user_id)
    new_image_url = db_diary.image_url

    # 2. 📸 사진 교체 처리
    if image:
        if db_diary.image_url:
            # 기존 이미지 삭제 (네트워크 작업이므로 스레드 활용)
            await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
        # 새 이미지 업로드
        new_image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    # 3. 🔍 키워드 JSON 안전하게 파싱
    keywords = None
    if keywords_json:
        try:
            keywords = json.loads(keywords_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="keywords_json 형식이 올바르지 않습니다.")

    # 4. 수정 객체 생성
    diary_in = DiaryUpdate(input_type=input_type, content=content, keywords=keywords)
    
    # 5. 💾 DB 업데이트 (변경된 필드만 반영 및 변경 여부 수신)
    updated_diary, is_changed = crud_diary.update_diary_with_image(db, db_diary, diary_in, new_image_url)

    # 6. 🚀 내용이 실제로 바뀌었을 때만 AI 재분석 요청 (사진만 바뀐 경우 패스)
    if is_changed:
        analysis_input = updated_diary.content or str(updated_diary.keywords)
        background_tasks.add_task(request_diary_analysis, updated_diary.diary_id, analysis_input)
        print(f"🔄 일기 {updated_diary.diary_id} 내용 변경됨 -> AI 분석 요청 전송")

    return updated_diary


# 5. 일기 삭제 (DELETE /diaries/{diary_id})
@router.delete("/{diary_id}")
async def delete_diary(
    diary_id: int = Path(..., description="삭제할 일기 ID"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    일기를 삭제합니다. 연관된 분석 데이터도 함께 삭제됩니다.
    """
    # crud 내부의 S3 삭제 작업을 스레드 풀로 보냅니다.
    return await anyio.to_thread.run_sync(crud_diary.delete_diary, db, diary_id, current_user.user_id)

# 6. AI가 분석 끝나면 호출할 콜백 API
@router.post("/analysis-callback")
def receive_ai_result(
    result: AIAnalysisResult,
    db: Session = Depends(get_session)
):
    """
    [AI 서버 전용] AI가 분석을 마치면 이 API를 호출해서 결과를 저장합니다.
    """
    print(f"📩 [From AI Server] 분석 결과 도착! (Diary ID: {result.diary_id})")

    # 1. 일기 찾기
    diary = db.get(Diary, result.diary_id)
    if not diary:
        return {"msg": "Diary not found"}
    
    # [A] 감정 분석 결과 저장
    # 일기 개수 체크 (3개 미만이면 번아웃 'NONE' 처리)
    count_statement = select(func.count(Diary.diary_id)).where(Diary.user_id == diary.user_id)
    diary_count = db.exec(count_statement).one()

    final_mbi = result.mbi_category
    
    # [수정 1] 데이터 부족 시 번아웃 결과를 NONE으로 덮어쓰기
    if diary_count < 3:
        final_mbi = "NONE" 

    emotion = EmotionAnalysis(
        diary_id=diary.diary_id,
        primary_emotion=result.primary_emotion,
        primary_score=result.primary_score,
        mbi_category=final_mbi,
        emotion_probs=result.emotion_probs
    )
    db.add(emotion)

    # [B] 솔루션 저장 
    # [수정 2] 일기가 3개 이상일 때만 솔루션(행동)을 저장합니다. (3개 미만이면 아예 저장 안 함)
    if diary_count >= 3:
        for rec in result.recommendations:
            new_solution = SolutionLog(
                diary_id=diary.diary_id,
                activity_id=rec.activity_id, # 리스트 안에 있는 id
                ai_message=rec.ai_message,   # 리스트 안에 있는 message
                is_selected=False,
                is_completed=False
            )
            db.add(new_solution)
        print(f"✅ 솔루션 저장 완료 (일기 개수: {diary_count}개)")
    else:
        print(f"ℹ️ 일기 데이터 부족({diary_count}개)으로 솔루션 저장을 건너뜁니다.")
    
    # 최종 저장 (한 번만 하면 됨)
    db.commit()
    
    return {"msg": "Analysis & Solutions saved successfully"}

# 7. 사진만 삭제하는 기능
@router.delete("/{diary_id}/image")
async def delete_diary_photo(
    diary_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    db_diary = crud_diary.get_diary(db, diary_id, current_user.user_id)
    if db_diary.image_url:
        await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
        db_diary.image_url = None 
        db.add(db_diary)
        db.commit()
        db.refresh(db_diary)
    return {"message": "사진이 성공적으로 삭제되었습니다."}