# app/services/s3_service.py
import boto3
import uuid
import os
from fastapi import UploadFile

# .env에서 정보 가져오기 (실제로는 core/config.py에서 관리하는 것을 추천)
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

def upload_image_to_s3(file: UploadFile) -> str:
    """S3에 파일을 업로드하고 접근 가능한 URL을 반환합니다."""
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"diaries/{uuid.uuid4()}.{file_extension}"
    
    s3_client.upload_fileobj(
        file.file,
        AWS_BUCKET_NAME,
        unique_filename,
        ExtraArgs={"ContentType": file.content_type}
    )
    
    return f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"

def delete_image_from_s3(image_url: str):
    """S3에서 파일을 삭제합니다."""
    if not image_url: return
    # URL에서 파일 키(파일명)만 추출
    file_key = image_url.split(f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/")[-1]
    s3_client.delete_object(Bucket=AWS_BUCKET_NAME, Key=file_key)