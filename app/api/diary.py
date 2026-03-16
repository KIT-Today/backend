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
from app.models.tables import User, Diary, EmotionAnalysis, SolutionLog, Activity, DiaryFeedback
from app.schemas.diary import (
    DiaryCreate, 
    DiaryRead, 
    DiaryUpdate, 
    AIAnalysisResult
)
from app.schemas.feedback import FeedbackCreate # 아까 만든 스키마
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
    persona: Optional[int] = Form(None), # ✨ 1. 여기에 persona 파라미터 추가!
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):

    # 1. DB에서 일기를 가져옵니다. (이때는 아직 수정 전이라 옛날 주소가 들어있습니다)
    db_diary = await crud_diary.get_diary(db, diary_id, current_user.user_id)
    
    # [수정 전] 기존 URL 저장
    old_image_url = db_diary.image_url
    new_image_url = db_diary.image_url

    # [순서 변경 1] JSON 검사 먼저!
    keywords = None
    if keywords_json:
        try:
            keywords = json.loads(keywords_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="keywords_json 형식이 올바르지 않습니다.")
        
    # [순서 변경 2] 이미지 업로드
    if image:
        image.file.seek(0, 2)
        size = image.file.tell()
        image.file.seek(0) # 필수 복구

        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="이미지 파일은 10MB 이하여야 합니다.")
        
        if not image.content_type.startswith("image/"):
             raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")

        new_image_url = await anyio.to_thread.run_sync(upload_image_to_s3, image)

    
    # 이후 DB 업데이트 
    diary_in = DiaryUpdate(input_type=input_type, content=content, keywords=keywords)
    
    # 3. DB 업데이트 - "새 주소"로 업데이트합니다.
    updated_diary, is_changed = await crud_diary.update_diary_with_image(db, db_diary, diary_in, new_image_url)

    # 4. 모든 처리가 성공했다면, 그때 비로소 '기존 이미지' 삭제 (백그라운드 처리 추천)
    if image and old_image_url and (old_image_url != new_image_url):
        background_tasks.add_task(delete_image_from_s3, old_image_url)

    if is_changed:
        # ✨ 2. AI에게 보낼 페르소나를 결정하고 background_tasks에 파라미터로(final_persona) 넘겨주기!
        target_persona = persona if persona is not None else current_user.persona
        final_persona = target_persona if target_persona is not None else 1

        background_tasks.add_task(request_diary_analysis, updated_diary.diary_id, current_user.user_id, final_persona)
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

# # 6. AI 콜백
# @router.post("/analysis-callback")
# async def receive_ai_result(
#     result: AIAnalysisResult,
#     db: AsyncSession = Depends(get_session) 
# ):
#     print(f"📩 [From AI Server] 분석 결과 도착! (Diary ID: {result.diary_id})")

#     # 1. 일기 조회 (존재 확인)
#     diary = await db.get(Diary, result.diary_id)
#     if not diary:
#         return {"msg": "Diary not found"}
    
#     # 2. 유저의 총 일기 개수 확인 (3개 미만이면 솔루션 제공 안 함)
#     count_statement = select(func.count(Diary.diary_id)).where(Diary.user_id == diary.user_id)
#     count_result = await db.exec(count_statement)
#     diary_count = count_result.one()

#     # 3. MBI 카테고리 결정 (데이터 부족 시 NONE)
#     final_mbi = result.mbi_category
#     if diary_count < 3:
#         final_mbi = "NONE" 

#     # 4. EmotionAnalysis 저장
#     emotion = EmotionAnalysis(
#         diary_id=diary.diary_id,
#         primary_emotion=result.primary_emotion,
#         primary_score=result.primary_score,
#         mbi_category=final_mbi,
#         emotion_probs=result.emotion_probs,
#         ai_message=result.ai_message
#     )
#     db.add(emotion)

#     # 5. SolutionLog 저장 (조건: 일기가 3개 이상일 때)
#     if diary_count >= 3:
#         for rec in result.recommendations:
#             new_solution = SolutionLog(
#                 diary_id=diary.diary_id,
#                 activity_id=rec.activity_id,
#                 is_selected=False,
#                 is_completed=False
#             )
#             db.add(new_solution)
#         print(f"✅ 솔루션 저장 완료 (일기 개수: {diary_count}개)")
#     else:
#         print(f"ℹ️ 일기 부족({diary_count}개) -> 솔루션 추천 건너뜀 (총평은 저장됨)")
    
#     # [중요] 여기서 먼저 commit을 해야 방금 추가한 EmotionAnalysis가 DB에 들어갑니다!
#     await db.commit()

#     # 유저 정보를 가져와서 푸시 알림(FCM)을 보냅니다.
#     user = await db.get(User, diary.user_id)
#     if user and user.fcm_token:
#         # 🔔 1. 일기 분석 완료 알림 (데이터 페이로드 포함!)
#         await send_fcm_notification(
#             token=user.fcm_token,
#             title="일기 분석 완료 ✨",
#             body="방금 작성하신 일기의 AI 분석이 끝났어요. 결과를 확인해볼까요?",
#             data={
#                 "type": "ANALYSIS_COMPLETE",      # 프론트가 어떤 알림인지 구분하기 위한 타입
#                 "diary_id": str(diary.diary_id)   # 반드시 문자열(str)로 변환해서 보내야 함!
#             }
#         )
    
#     # 🔔 2. 메달 획득 조건 체크 및 알림 전송 (기존 로직 유지 + 데이터 추가 가능)
#         new_achievement = await check_and_award_recovery_medal(db, diary.user_id)
#         if new_achievement:
#             print(f"🏅 유저 {diary.user_id} 메달 획득 성공!")
#             await send_fcm_notification(
#                 token=user.fcm_token,
#                 title="새로운 메달 획득! 🏅",
#                 body="마음이 한결 편안해지셨네요. 사용자페이지에서 획득한 메달을 확인해 보세요!",
#                 data={
#                     "type": "NEW_MEDAL",
#                     "achieve_id": str(new_achievement.achieve_id)
#                 }
#             )

#     return {"msg": "Analysis & Solutions saved successfully"}

# (수정 후)
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

    # --- 🚀 [수정된 구간 1] MBI 카테고리 결정 ---
    if result.primary_emotion == "긍정":
        final_mbi = "NORMAL"
    else: # "부정"인 경우
        if diary_count < 3:
            final_mbi = "NONE" # 데이터 부족 시
        else:
            final_mbi = result.mbi_category 
    # -------------------------------------------

    # 4. EmotionAnalysis 추가 (아직 DB 반영 안 됨)
    emotion = EmotionAnalysis(
        diary_id=diary.diary_id,
        primary_emotion=result.primary_emotion,
        primary_score=result.primary_score,
        mbi_category=final_mbi,
        emotion_probs=result.emotion_probs,
        ai_message=result.ai_message # 이 ai_message는 EmotionAnalysis용 (기존 유지)
    )
    db.add(emotion)

    # 5. SolutionLog 저장 (조건: 일기가 3개 이상일 때)
    if diary_count >= 3:
        # 5-1. AI가 추천한 엑티비티 내용만 리스트로 추출
        recommended_contents = [rec.act_content for rec in result.recommendations]

        # 5-2. DB에서 기존에 있는 엑티비티 한 번에 조회
        statement = select(Activity).where(Activity.act_content.in_(recommended_contents))
        existing_activities_result = await db.exec(statement)
        
        # 빠른 검색을 위해 딕셔너리로 변환 {"산책하기": Activity객체}
        existing_dict = {act.act_content: act for act in existing_activities_result.all()}

        # 5-3. DB에 없는 새로운 엑티비티 추려내기
        new_activities = []
        for rec in result.recommendations:
            if rec.act_content not in existing_dict:
                new_act = Activity(
                    act_content=rec.act_content,
                    act_category=rec.act_category,
                    is_active=rec.is_active,
                    is_outdoor=rec.is_outdoor,
                    is_social=rec.is_social,
                    is_enabled=True, 
                    source="LLM"
                )
                new_activities.append(new_act)
                existing_dict[rec.act_content] = new_act

        # 5-4. 새로운 엑티비티가 있으면 DB에 한 번에 밀어넣고 ID 발급
        if new_activities:
            db.add_all(new_activities)
            await db.flush() # db.commit() 전에 ID만 발급받는 기능

        # 5-5. 최종적으로 SolutionLog 연결 및 추가
        for rec in result.recommendations:
            target_activity = existing_dict[rec.act_content]
            
            new_solution = SolutionLog(
                diary_id=diary.diary_id,
                activity_id=target_activity.activity_id,
                is_selected=False,
                is_completed=False,
                ai_message=rec.ai_message  # --- 🚀 [수정된 구간 2] 솔루션별 AI 메시지 추가 ---
            )
            db.add(new_solution)
            
        print(f"✅ 솔루션 저장 완료 (신규 엑티비티 {len(new_activities)}개 추가됨)")
    else:
        print(f"ℹ️ 일기 부족({diary_count}개) -> 솔루션 추천 건너뜀 (총평은 저장됨)")
    
    # [중요] 여기서 한번에 커밋! 
    await db.commit()

    # -------------------------------------------------------------
    # 이하 FCM 알림 및 메달 로직 (기존과 동일하므로 생략 없이 그대로 복사됨)
    # -------------------------------------------------------------
    
    user = await db.get(User, diary.user_id)
    if user and user.fcm_token:
        # 🔔 1. 일기 분석 완료 알림
        await send_fcm_notification(
            token=user.fcm_token,
            title="일기 분석 완료 ✨",
            body="방금 작성하신 일기의 AI 분석이 끝났어요. 결과를 확인해볼까요?",
            data={
                "type": "ANALYSIS_COMPLETE",
                "diary_id": str(diary.diary_id) 
            }
        )
    
        # 🔔 2. 메달 획득 조건 체크 및 알림 전송
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

# 8. 별점 피드백 db 저장하는 api
@router.post("/{diary_id}/feedback")
async def submit_diary_feedback(
    diary_id: int,
    feedback_in: FeedbackCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # 1. 일기 소유권 확인
    diary = await db.get(Diary, diary_id)
    if not diary or diary.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="권한이 없거나 일기를 찾을 수 없습니다.")

    # 2. 이미 피드백을 했는지 확인
    statement = select(DiaryFeedback).where(DiaryFeedback.diary_id == diary_id)
    result = await db.exec(statement)
    if result.first():
        raise HTTPException(status_code=400, detail="이미 피드백을 제출하셨습니다.")

    # 3. 피드백 저장
    new_feedback = DiaryFeedback(
        diary_id=diary_id,
        ai_message_rating=feedback_in.ai_message_rating,
        mbi_category_rating=feedback_in.mbi_category_rating,
        is_sent_to_ai=False # 스케줄러 대기 상태
    )
    db.add(new_feedback)
    await db.commit()

    return {"message": "피드백이 성공적으로 저장되었습니다."}