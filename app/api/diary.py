# app/api/diary.py
import anyio
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, UploadFile, File, Form, HTTPException, BackgroundTasks
import json

# AsyncSession를 할 때, 이걸 사용해야 함.
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
    # 이번 일기에만 적용할 페르소나 (없으면 None)
    persona: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    image_url = None
    if image:
        image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    keywords = json.loads(keywords_json) if keywords_json else None
    diary_in = DiaryCreate(input_type=input_type, content=content, keywords=keywords)
    
    # 일기 저장
    db_diary = await crud_diary.create_diary(db, diary_in, current_user.user_id, image_url)

    # AI에게 보낼 페르소나 결정하기
   
    # (A) 프론트가 페르소나를 보냈다면? -> 그걸 씀
    # (B) 안 보냈다면(None)? -> DB에 저장된 유저의 기본 페르소나를 씀
    target_persona = persona if persona is not None else current_user.persona

    # (C) [안전장치] 만약 둘 다 없다면? (앱 초기라 설정도 안 했고, 프론트도 안 보냄)
    # -> AI 오류 방지를 위해 기본값(예: 1번 페르소나)을 설정
    final_persona = target_persona if target_persona is not None else 1

    # 백그라운드 호출 (수정 없음, 함수 내부에서 세션 생성함)
    background_tasks.add_task(request_diary_analysis, db_diary.diary_id, current_user.user_id, final_persona)

    return db_diary

# 2. 일기 목록 조회
@router.get("/", response_model=List[DiaryRead])
async def read_diaries(
    skip: int = 0,
    limit: int = 10,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
   
    return await crud_diary.get_diaries(
        db, user_id=current_user.user_id, skip=skip, limit=limit, year=year, month=month
    )

# 3. 일기 상세 조회
@router.get("/{diary_id}", response_model=DiaryRead)
async def read_diary(
    diary_id: int = Path(...),
    db: AsyncSession = Depends(get_session), 
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
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):

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
    
    updated_diary, is_changed = await crud_diary.update_diary_with_image(db, db_diary, diary_in, new_image_url)

    if is_changed:
        background_tasks.add_task(request_diary_analysis, updated_diary.diary_id, current_user.user_id)
        print(f"🔄 일기 {updated_diary.diary_id} 내용 변경됨 -> AI 분석 요청 전송")

    return updated_diary

# 5. 일기 삭제
@router.delete("/{diary_id}")
async def delete_diary(
    diary_id: int = Path(...),
    db: AsyncSession = Depends(get_session), 
    current_user: User = Depends(get_current_user)
):
    
    return await crud_diary.delete_diary(db, diary_id, current_user.user_id)

# 6. AI 콜백
@router.post("/analysis-callback")
async def receive_ai_result(
    result: AIAnalysisResult,
    db: AsyncSession = Depends(get_session) 
):
    print(f"📩 [From AI Server] 분석 결과 도착! (Diary ID: {result.diary_id})")

    # 1. 일기 조회 (존재 확인)
    diary = await db.get(Diary, result.diary_id)
    if not diary:
        return {"msg": "Diary not found"}
    
    # 2. 유저의 총 일기 개수 확인 (3개 미만이면 솔루션 제공 안 함)
    count_statement = select(func.count(Diary.diary_id)).where(Diary.user_id == diary.user_id)
    count_result = await db.exec(count_statement)
    diary_count = count_result.one()

    # 3. MBI 카테고리 결정 (데이터 부족 시 NONE)
    final_mbi = result.mbi_category
    if diary_count < 3:
        final_mbi = "NONE" 

    # 4. EmotionAnalysis 저장
    emotion = EmotionAnalysis(
        diary_id=diary.diary_id,
        primary_emotion=result.primary_emotion,
        primary_score=result.primary_score,
        mbi_category=final_mbi,
        emotion_probs=result.emotion_probs,
        # [핵심] AI의 총평을 여기에 저장합니다!
        # 이제 일기가 3개 미만이어도 메시지는 저장될 수 있습니다. (AI가 보내준다면)
        ai_message=result.ai_message
    )
    db.add(emotion)

    # 5. SolutionLog 저장 (조건: 일기가 3개 이상일 때)
    # (AI가 준 recommendations 리스트를 돌면서 ai_message를 저장합니다)
    if diary_count >= 3:
        for rec in result.recommendations:
            new_solution = SolutionLog(
                diary_id=diary.diary_id,
                activity_id=rec.activity_id,
                is_selected=False,
                is_completed=False
            )
            db.add(new_solution)
        print(f"✅ 솔루션 저장 완료 (일기 개수: {diary_count}개)")
    else:
        # 일기가 적어서 솔루션은 저장 안 하지만, 
        # 위에서 EmotionAnalysis(총평)는 저장했으므로 데이터 손실 없음!
        print(f"ℹ️ 일기 부족({diary_count}개) -> 솔루션 추천 건너뜀 (총평은 저장됨)")
    
    await db.commit()
    
    return {"msg": "Analysis & Solutions saved successfully"}

# 7. 사진만 삭제하는 기능
@router.delete("/{diary_id}/image")
async def delete_diary_photo(
    diary_id: int,
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
   
    db_diary = await crud_diary.get_diary(db, diary_id, current_user.user_id)
    
    if db_diary.image_url:
        await anyio.to_thread.run_sync(delete_image_from_s3, db_diary.image_url)
        db_diary.image_url = None 
        db.add(db_diary)
        
        await db.commit()
        await db.refresh(db_diary)
        
    return {"message": "사진이 성공적으로 삭제되었습니다."}