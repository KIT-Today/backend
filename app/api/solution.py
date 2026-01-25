from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession # [변경] AsyncSession
from app.api.deps import get_current_user
from database import get_session
from app.models.tables import User, SolutionLog, Diary
from app.schemas.solution import SolutionUpdate, SolutionRead

router = APIRouter()

@router.patch("/{log_id}", response_model=SolutionRead)
async def update_solution_status( # [변경] async def
    log_id: int,
    solution_in: SolutionUpdate,
    db: AsyncSession = Depends(get_session), # [변경] AsyncSession
    current_user: User = Depends(get_current_user)
):
    """
    솔루션의 상태(선택 여부, 완료 여부)를 수정합니다.
    - is_selected: true/false
    - is_completed: true/false
    """
    # 1. 솔루션 로그 찾기
    solution = await db.get(SolutionLog, log_id) # [변경] await db.get
    if not solution:
        raise HTTPException(status_code=404, detail="솔루션을 찾을 수 없습니다.")

    # 2. 권한 확인 (내 일기에 달린 솔루션인지 확인)
    # SolutionLog -> Diary -> User 연결 확인
    diary = await db.get(Diary, solution.diary_id) # [변경] await db.get
    if not diary or diary.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    # 3. 데이터 업데이트 (보내준 값만 변경)
    if solution_in.is_selected is not None:
        solution.is_selected = solution_in.is_selected
    
    if solution_in.is_completed is not None:
        solution.is_completed = solution_in.is_completed

    db.add(solution)
    await db.commit() # [변경] await commit
    await db.refresh(solution) # [변경] await refresh
    
    return solution