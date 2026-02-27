from pydantic import BaseModel

class FeedbackCreate(BaseModel):
    ai_message_rating: int
    mbi_category_rating: int