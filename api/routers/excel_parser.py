"""Endpoint для парсинга Excel файлов."""

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()


@router.post("/parse-excel")
async def parse_excel(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Парсит Excel файл и возвращает данные в формате JSON.
    
    Args:
        file: Загруженный Excel файл
        
    Returns:
        Словарь с данными проекта
    """
    try:
        from utils.excel_io import excel_to_json

        # Читаем файл
        file_bytes = await file.read()

        # Парсим Excel
        data_list = excel_to_json(file_bytes)

        if not data_list:
            raise HTTPException(status_code=400, detail="Excel файл пуст или не содержит данных")

        # Возвращаем первый элемент (если несколько проектов в файле)
        result = data_list[0]

        # Маппинг для обратной совместимости
        if "project_title" in result and "title_seed" not in result:
            result["title_seed"] = result["project_title"]

        return result

    except ImportError:
        raise HTTPException(status_code=500, detail="Для работы с Excel файлами требуется pandas. Установите: pip install pandas openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при чтении Excel файла: {str(e)}")

