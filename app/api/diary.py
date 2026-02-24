# app/api/diary.py
import anyio
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, UploadFile, File, Form, HTTPException, BackgroundTasks
import json

# AsyncSession를 할 때, 이걸 사용해야 함.
from sqlalchemy.ext.asyncio import AsyncSession 

from app.services.s3_service import upload_image_to_s3, delete_image_from_s3
from app.services.ai_services import request_diary_analysis
from app.crud.user import check_and_award_recovery_medal
from app.core.fcm import send_fcm_notification

# DB 관련 도구들
from sqlmodel import func, select
from database import get_session

# 인증 관련
from app.api.deps import get_current_user

from fastapi import UploadFile, HTTPException

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

# [설정] 제한할 용량 (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

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
    # [순서 변경 1] 가벼운 JSON 검사를 먼저 합니다. (여기서 에러 나면 사진 업로드 안 함)
    # 프론트엔드에서 Keywords_json을 잘못된 형식(JSON아님)으로 보내면 500 에러가 나는데 이걸 안전하게 예외처리로 바꿈.
    keywords = None
    if keywords_json:
        try:
            keywords = json.loads(keywords_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="keywords_json 형식이 올바르지 않습니다.")
        
    # [순서 변경 2] 그 다음에 무거운 이미지 업로드를 합니다.    
    image_url = None
    if image:
        # ---------------------------------------------------------
        # [추가] 이미지 용량 및 형식 체크 로직
        # ---------------------------------------------------------
        # 1. 파일 끝으로 이동해서 크기 확인
        image.file.seek(0, 2)
        size = image.file.tell()
        # 2. 다시 파일 처음으로 되돌리기 (필수! 안 하면 업로드될 때 빈 파일이 됨)
        image.file.seek(0)

        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="이미지 파일은 10MB 이하여야 합니다.")
        
        if not image.content_type.startswith("image/"):
             raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
        # ---------------------------------------------------------

        image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    # 이후 DB 저장 로직
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
# [새 사진 업로드] -> [DB 저장] -> [성공 시 기존 사진 삭제]
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

    # 1. DB에서 일기를 가져옵니다. (이때는 아직 수정 전이라 옛날 주소가 들어있습니다)
    db_diary = await crud_diary.get_diary(db, diary_id, current_user.user_id)
    
    # [수정 전] 기존 URL 저장
    # [중요!] 여기가 바로 "왼손에 헌 옷 쥐기" 단계입니다.
    # DB를 바꾸기 전에, 현재 주소를 'old_image_url'이라는 변수에 복사해둡니다.
    old_image_url = db_diary.image_url
    new_image_url = db_diary.image_url

# ... (새 사진 업로드 과정) ...

    # [순서 변경 1] JSON 검사 먼저!
    # 1. 키워드 파싱 (예외처리 포함)
    keywords = None
    if keywords_json:
        try:
            keywords = json.loads(keywords_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="keywords_json 형식이 올바르지 않습니다.")
        
    # [순서 변경 2] 이미지 업로드
    # 2. 새 이미지가 있다면 '먼저' 업로드 (안전하게!)
    if image:
        # ---------------------------------------------------------
        # [추가] 이미지 용량 및 형식 체크 로직
        # ---------------------------------------------------------
        image.file.seek(0, 2)
        size = image.file.tell()
        image.file.seek(0) # 필수 복구

        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="이미지 파일은 10MB 이하여야 합니다.")
        
        if not image.content_type.startswith("image/"):
             raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
        # ---------------------------------------------------------

        new_image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    
    # 이후 DB 업데이트 
    diary_in = DiaryUpdate(input_type=input_type, content=content, keywords=keywords)
    
    # 3. DB 업데이트 - "새 주소"로 업데이트합니다.
    # 이제 db_diary 객체 안의 주소는 새것으로 바뀌었지만,
    # 위에서 만든 'old_image_url' 변수는 여전히 옛날 주소를 기억하고 있습니다!
    updated_diary, is_changed = await crud_diary.update_diary_with_image(db, db_diary, diary_in, new_image_url)

    # 모든 게 성공했으니, 아까 챙겨둔 'old_image_url'을 이용해 S3에서 지웁니다.
    # 4. 모든 처리가 성공했다면, 그때 비로소 '기존 이미지' 삭제 (백그라운드 처리 추천)
    if image and old_image_url and (old_image_url != new_image_url):
        # BackgroundTasks를 이용해 응답 후 삭제 (사용자 대기 시간 단축)
        background_tasks.add_task(delete_image_from_s3, old_image_url)

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
        ai_message=result.ai_message
    )
    db.add(emotion)

    # 5. SolutionLog 저장 (조건: 일기가 3개 이상일 때)
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
        print(f"ℹ️ 일기 부족({diary_count}개) -> 솔루션 추천 건너뜀 (총평은 저장됨)")
    
    # [중요] 여기서 먼저 commit을 해야 방금 추가한 EmotionAnalysis가 DB에 들어갑니다!
    await db.commit()

    # 유저 정보를 가져와서 푸시 알림(FCM)을 보냅니다.
    user = await db.get(User, diary.user_id)
    if user and user.fcm_token:
        # 🔔 1. 일기 분석 완료 알림 (데이터 페이로드 포함!)
        await send_fcm_notification(
            token=user.fcm_token,
            title="일기 분석 완료 ✨",
            body="방금 작성하신 일기의 AI 분석이 끝났어요. 결과를 확인해볼까요?",
            data={
                "type": "ANALYSIS_COMPLETE",      # 프론트가 어떤 알림인지 구분하기 위한 타입
                "diary_id": str(diary.diary_id)   # 반드시 문자열(str)로 변환해서 보내야 함!
            }
        )
    
    # 🔔 2. 메달 획득 조건 체크 및 알림 전송 (기존 로직 유지 + 데이터 추가 가능)
        new_achievement = await check_and_award_recovery_medal(db, diary.user_id)
        if new_achievement:
            print(f"🏅 유저 {diary.user_id} 메달 획득 성공!")
            await send_fcm_notification(
                token=user.fcm_token,
                title="새로운 메달 획득! 🏅",
                body="마음이 한결 편안해지셨네요. 사용자페이지에서 획득한 메달을 확인해 보세요!",
                data={
                    "type": "NEW_MEDAL",
                    "achieve_id": str(new_achievement.achieve_id)
                }
            )

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