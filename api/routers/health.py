"""Health check endpoint."""

import os
import time
from typing import Any

import psutil
from fastapi import APIRouter

from api.db.session import check_database_connection, get_database_status
from api.utils.logger import get_logger

router = APIRouter()
logger = get_logger("health")


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Расширенная проверка здоровья сервиса.
    
    Проверяет:
    - Подключение к БД
    - Доступность внешних сервисов (OpenAI)
    - Использование ресурсов (память, CPU)
    
    Args:
        db: Сессия БД
        
    Returns:
        Статус сервиса и его компонентов
    """
    status = "healthy"
    checks = {}

    # Проверка подключения к БД
    try:
        check_database_connection()
        checks["database"] = {
            "status": "ok",
            "message": "Connected",
            "target": get_database_status().get("target"),
        }
    except Exception as e:
        status = "unhealthy"
        db_status = get_database_status()
        checks["database"] = {
            "status": "error",
            "message": db_status.get("error") or str(e),
            "target": db_status.get("target"),
        }
        logger.error("Database health check failed: %s", checks["database"]["message"])

    # Проверка доступности LLM API
    llm_available = bool(os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY"))
    checks["llm"] = {
        "status": "ok" if llm_available else "warning",
        "available": llm_available,
        "message": "LLM API key configured" if llm_available else "LLM API key not configured"
    }

    if not llm_available:
        status = "degraded"

    # Контекст генерации
    checks["generation_context"] = {
        "status": "ok",
        "mode": "curriculum_only",
        "message": "Production generation uses curriculum_context and explicit reference hints",
    }

    # Проверка Redis (если используется)
    redis_url = os.getenv("REDIS_URL")
    if redis_url and redis_url != "":
        try:
            import redis
            redis_client = redis.from_url(redis_url, decode_responses=True)
            redis_client.ping()
            checks["redis"] = {
                "status": "ok",
                "available": True,
                "message": "Redis connected"
            }
        except ImportError:
            checks["redis"] = {
                "status": "warning",
                "available": False,
                "message": "Redis URL configured but redis package not installed"
            }
        except Exception as e:
            checks["redis"] = {
                "status": "error",
                "available": False,
                "message": f"Redis connection failed: {e}"
            }
            if status == "healthy":
                status = "degraded"
    else:
        checks["redis"] = {
            "status": "ok",
            "available": False,
            "message": "Redis not configured (optional)"
        }

    # Метрики использования ресурсов
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        cpu_percent = process.cpu_percent(interval=0.1)

        checks["resources"] = {
            "status": "ok",
            "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(process.memory_percent(), 2)
        }
    except Exception as e:
        checks["resources"] = {
            "status": "warning",
            "message": f"Could not get resource metrics: {e}"
        }

    return {
        "status": status,
        "version": "1.0.0",
        "timestamp": time.time(),
        "checks": checks
    }
