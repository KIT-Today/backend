# app/api/diary.py
import anyio
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, UploadFile, File, Form, HTTPException, BackgroundTasks
import json

# [수정] 여기가 빠져서 오류가 났습니다. 추가했습니다!
from sqlalchemy.ext.asyncio import AsyncSession 

from app.services.s3_service import upload_image_to_s3, delete_image_from_s3
from app.services.ai_services import request_diary_analysis

# DB 관련 도구들
from sqlmodel import func, select
from database import get_session

# 인증 관련
from app.api.deps import get_current_user

# 모델 & 스키마
from app.models.tables import User, Diary, EmotionAnalysis, SolutionLog
from app.schemas.diary import (
    DiaryCreate, 
    DiaryRead, 
    DiaryUpdate, 
    AIAnalysisResult
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
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    image_url = None
    if image:
        image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    keywords = json.loads(keywords_json) if keywords_json else None
    diary_in = DiaryCreate(input_type=input_type, content=content, keywords=keywords)
    
    # [변경] await
    db_diary = await crud_diary.create_diary(db, diary_in, current_user.user_id, image_url)

    # [변경] 백그라운드 호출 (수정 없음, 함수 내부에서 세션 생성함)
    background_tasks.add_task(request_diary_analysis, db_diary.diary_id, current_user.user_id)

    return db_diary

# 2. 일기 목록 조회
@router.get("/", response_model=List[DiaryRead])
async def read_diaries(
    skip: int = 0,
    limit: int = 10,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    # [변경] await
    return await crud_diary.get_diaries(
        db, user_id=current_user.user_id, skip=skip, limit=limit, year=year, month=month
    )

# 3. 일기 상세 조회
@router.get("/{diary_id}", response_model=DiaryRead)
async def read_diary(
    diary_id: int = Path(...),
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    # [변경] await
    return await crud_diary.get_diary(db, diary_id, current_user.user_id)

# 4. 일기 수정 
@router.patch("/{diary_id}", response_model=DiaryRead)
async def update_diary(
    diary_id: int,
    background_tasks: BackgroundTasks,
    input_type: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    keywords_json: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    # [변경] await
    db_diary = await crud_diary.get_diary(db, diary_id, current_user.user_id)
    new_image_url = db_diary.image_url

    if image:
        if db_diary.image_url:
            await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
        new_image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    keywords = None
    if keywords_json:
        try:
            keywords = json.loads(keywords_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="keywords_json 형식이 올바르지 않습니다.")

    diary_in = DiaryUpdate(input_type=input_type, content=content, keywords=keywords)
    
    # [변경] await
    updated_diary, is_changed = await crud_diary.update_diary_with_image(db, db_diary, diary_in, new_image_url)

    if is_changed:
        background_tasks.add_task(request_diary_analysis, updated_diary.diary_id, current_user.user_id)
        print(f"🔄 일기 {updated_diary.diary_id} 내용 변경됨 -> AI 분석 요청 전송")

    return updated_diary

# 5. 일기 삭제
@router.delete("/{diary_id}")
async def delete_diary(
    diary_id: int = Path(...),
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    # [변경] await
    return await crud_diary.delete_diary(db, diary_id, current_user.user_id)

# 6. AI 콜백
@router.post("/analysis-callback")
async def receive_ai_result(
    result: AIAnalysisResult,
    db: AsyncSession = Depends(get_session) # [변경] AsyncSession
):
    print(f"📩 [From AI Server] 분석 결과 도착! (Diary ID: {result.diary_id})")

    # [변경] await db.get
    diary = await db.get(Diary, result.diary_id)
    if not diary:
        return {"msg": "Diary not found"}
    
    # [변경] await exec
    count_statement = select(func.count(Diary.diary_id)).where(Diary.user_id == diary.user_id)
    count_result = await db.exec(count_statement)
    diary_count = count_result.one()

    final_mbi = result.mbi_category
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

    if diary_count >= 3:
        for rec in result.recommendations:
            new_solution = SolutionLog(
                diary_id=diary.diary_id,
                activity_id=rec.activity_id,
                ai_message=rec.ai_message,
                is_selected=False,
                is_completed=False
            )
            db.add(new_solution)
        print(f"✅ 솔루션 저장 완료 (일기 개수: {diary_count}개)")
    else:
        print(f"ℹ️ 일기 데이터 부족({diary_count}개)으로 솔루션 저장을 건너뜁니다.")
    
    # [변경] await commit
    await db.commit()
    
    return {"msg": "Analysis & Solutions saved successfully"}

# 7. 사진만 삭제하는 기능
@router.delete("/{diary_id}/image")
async def delete_diary_photo(
    diary_id: int,
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    # [변경] await
    db_diary = await crud_diary.get_diary(db, diary_id, current_user.user_id)
    
    if db_diary.image_url:
        await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
        db_diary.image_url = None 
        db.add(db_diary)
        
        # [변경] await
        await db.commit()
        await db.refresh(db_diary)
        
    return {"message": "사진이 성공적으로 삭제되었습니다."}