"""Endpoints для обратного извлечения данных из README."""

import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.utils.logger import get_logger
from content_gen.llm.client import LLMClient
from content_gen.reverse_extraction import ReverseExtractionOrchestrator

router = APIRouter()
logger = get_logger("reverse_extraction")

# Простой in-memory кэш для Excel файлов (file_id -> bytes)
_file_cache: dict[str, bytes] = {}
_metadata_cache: dict[str, dict] = {}


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
    http_request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Извлекает данные из README и создает Excel файл.
    
    Args:
        http_request: FastAPI Request объект (для получения JSON body)
        readme_file: Загруженный README.md файл (опционально)
        user: Данные пользователя
        
    Returns:
        ExtractResponse с file_id для скачивания
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")

    logger.info(f"📄 Начало обратного извлечения для пользователя {user_id}")

    # Получаем текст README
    readme_text = None

    # Проверяем Content-Type
    content_type = http_request.headers.get("content-type", "").lower()
    logger.info(f"📋 Content-Type: {content_type}")
    logger.info(f"📋 Метод: {http_request.method}, URL: {http_request.url}")

    # Обрабатываем в зависимости от Content-Type
    if "application/json" in content_type:
        # Читаем из JSON body (основной случай)
        try:
            body = await http_request.json()
            logger.info(f"📋 JSON body keys: {list(body.keys()) if isinstance(body, dict) else 'not a dict'}")

            readme_text = body.get("readme_text") or body.get("readmeText")
            if readme_text:
                logger.info(f"✅ README прочитан из JSON, размер: {len(readme_text)} символов")
            else:
                logger.warning(f"⚠️ readme_text не найден в JSON body. Доступные ключи: {list(body.keys()) if isinstance(body, dict) else 'N/A'}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Ошибка парсинга JSON: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Ошибка чтения JSON body: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Ошибка чтения JSON body: {str(e)}")
    elif "multipart/form-data" in content_type:
        # Пробуем получить из form-data (может быть файл или текстовое поле)
        try:
            form = await http_request.form()

            # Проверяем, есть ли файл
            readme_file = form.get("readme_file")
            if readme_file and hasattr(readme_file, 'read'):
                # Это файл
                try:
                    readme_text = (await readme_file.read()).decode("utf-8")
                    logger.info(f"✅ README прочитан из файла (form-data), размер: {len(readme_text)} символов")
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения файла из form-data: {e}", exc_info=True)
                    raise HTTPException(status_code=400, detail=f"Ошибка чтения файла: {str(e)}")
            else:
                # Пробуем получить как текстовое поле
                readme_text = form.get("readme_text")
                if readme_text and isinstance(readme_text, str):
                    logger.info(f"✅ README прочитан из form-data (текстовое поле), размер: {len(readme_text)} символов")
                else:
                    logger.warning("⚠️ readme_text не найден в form-data")
        except Exception as e:
            logger.error(f"❌ Ошибка чтения form-data: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Ошибка чтения form-data: {str(e)}")
    else:
        # Пробуем распарсить как JSON в любом случае (fallback)
        try:
            logger.info("🔄 Пробуем распарсить как JSON (auto-detect)")
            body = await http_request.json()
            readme_text = body.get("readme_text") or body.get("readmeText")
            if readme_text:
                logger.info(f"✅ README прочитан из body (auto-detect JSON), размер: {len(readme_text)} символов")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось распарсить как JSON: {e}")

    if not readme_text or not readme_text.strip():
        logger.error(f"❌ README текст не получен. Content-Type: {content_type}")
        logger.error(f"❌ readme_text is None: {readme_text is None}, empty: {readme_text == '' if readme_text else 'N/A'}")
        raise HTTPException(
            status_code=400,
            detail="Необходимо предоставить либо readme_text в JSON, либо загрузить readme_file"
        )

    try:
        # Инициализируем оркестратор
        llm_client = LLMClient()
        orchestrator = ReverseExtractionOrchestrator(llm_client)

        # Выполняем извлечение
        excel_buffer, metadata = orchestrator.extract_from_readme(readme_text)

        # Сохраняем файл в кэш
        excel_file_id = str(uuid.uuid4())
        excel_bytes = excel_buffer.getvalue()
        _file_cache[excel_file_id] = excel_bytes
        _metadata_cache[excel_file_id] = metadata

        logger.info(
            f"✅ Обратное извлечение завершено: file_id={excel_file_id}, "
            f"размер Excel={len(excel_bytes)} байт"
        )

        return ExtractResponse(
            request_id=request_id,
            status="completed",
            excel_file_id=excel_file_id,
            metadata=metadata
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
    if file_id not in _file_cache:
        logger.warning(f"⚠️ Файл {file_id} не найден в кэше")
        raise HTTPException(
            status_code=404,
            detail="Файл не найден или истек срок хранения"
        )

    excel_bytes = _file_cache[file_id]
    metadata = _metadata_cache.get(file_id, {})

    # Формируем имя файла
    title = metadata.get("extracted_fields", {}).get("final_mapping", {}).get("title_seed", "project")

    # Транслитерируем кириллицу в латиницу и очищаем от недопустимых символов
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }

    # Недопустимые символы для Windows имен файлов
    INVALID_CHARS = set('<>:"/\\|?*;')

    def transliterate_and_clean(text):
        """Транслитерирует кириллицу и удаляет недопустимые символы."""
        result = []
        for char in text:
            if char in translit_map:
                result.append(translit_map[char])
            elif char in INVALID_CHARS:
                result.append('_')  # Заменяем недопустимые символы на подчеркивание
            elif char.isalnum() or char in (" ", "-", "_", "."):
                result.append(char)
            else:
                result.append('_')  # Заменяем другие недопустимые символы
        return ''.join(result)

    # Транслитерируем и очищаем название
    safe_title = transliterate_and_clean(title)
    # Заменяем пробелы на подчеркивания и убираем множественные подчеркивания
    safe_title = '_'.join(safe_title.split())
    safe_title = safe_title.replace('__', '_').replace('__', '_')
    # Ограничиваем длину (50 символов для названия + "_spec.xlsx")
    safe_title = safe_title[:50].strip('_')

    filename = f"{safe_title}_spec.xlsx" if safe_title else "project_spec.xlsx"

    # Используем простой формат заголовка (без RFC 5987) для надежности
    # Кавычки нужны для защиты от пробелов в имени файла
    content_disposition = f'attachment; filename="{filename}"'

    logger.info(f"📥 Скачивание Excel файла: file_id={file_id}, filename={filename}")

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition}
    )

