"""Endpoints для обратного извлечения данных из README."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.services.reverse_extraction_service import (
    ReverseExtractionCommand,
    ReverseExtractionService,
    bytes_to_stream,
)
from api.utils.logger import get_logger

router = APIRouter()
logger = get_logger("reverse_extraction")
_reverse_extraction_service = ReverseExtractionService()


class ExtractRequest(BaseModel):
    """Запрос на извлечение данных из README."""
    readme_text: str


class ExtractResponse(BaseModel):
    """Ответ на запрос извлечения."""
    request_id: str
    status: str
    excel_file_id: str | None = None
    metadata: dict


@router.post("/reverse-extract/extract", response_model=ExtractResponse)
async def extract_from_readme(
    request: ExtractRequest,
    user: dict = Depends(get_current_user)
):
    """
    Извлекает данные из README и создает Excel файл.
    
    Args:
        request: JSON body with readme_text
        user: Данные пользователя
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")
    readme_text = request.readme_text
    if not readme_text or not readme_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Необходимо предоставить readme_text"
        )

    try:
        result = _reverse_extraction_service.extract_from_readme(
            ReverseExtractionCommand(
                request_id=request_id,
                user_id=user_id,
                readme_text=readme_text,
            )
        )
        return ExtractResponse(
            request_id=result.request_id,
            status=result.status,
            excel_file_id=result.excel_file_id,
            metadata=result.metadata
        )

    except Exception as e:
        logger.error(f"❌ Ошибка при обратном извлечении: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при извлечении данных: {str(e)}"
        )


@router.get("/reverse-extract/download/{file_id}")
async def download_excel(
    file_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Скачивает сгенерированный Excel файл.
    
    Args:
        file_id: ID файла из ответа extract
        user: Данные пользователя
        
    Returns:
        Excel файл для скачивания
    """
    download = _reverse_extraction_service.get_download(file_id)
    if download is None:
        logger.warning(f"⚠️ Файл {file_id} не найден в кэше")
        raise HTTPException(
            status_code=404,
            detail="Файл не найден или истек срок хранения"
        )

    # Используем простой формат заголовка (без RFC 5987) для надежности
    # Кавычки нужны для защиты от пробелов в имени файла
    content_disposition = f'attachment; filename="{download.filename}"'

    logger.info(f"📥 Скачивание Excel файла: file_id={file_id}, filename={download.filename}")

    return StreamingResponse(
        bytes_to_stream(download.excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition}
    )

