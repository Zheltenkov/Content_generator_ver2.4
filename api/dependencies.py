"""Зависимости для FastAPI endpoints."""

import os
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

# JWT настройки
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> dict[str, Any]:
    """
    Проверяет JWT токен и возвращает данные пользователя.
    
    Args:
        credentials: JWT токен из заголовка Authorization
        
    Returns:
        Словарь с данными пользователя
        
    Raises:
        HTTPException: Если токен невалиден или отсутствует
    """
    # В режиме разработки можно отключить аутентификацию
    if os.getenv("DISABLE_AUTH", "false").lower() == "true":
        return {"id": "dev_user", "username": "dev"}

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный токен"
            )
        return {
            "id": user_id,
            "username": payload.get("username", user_id),
            "email": payload.get("email"),
            "role": payload.get("role"),
        }
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен"
        )



