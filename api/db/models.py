"""SQLAlchemy модели для базы данных логов."""

from datetime import datetime
from typing import Any

from passlib.context import CryptContext
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# Контекст для хеширования паролей
# Используем Argon2 как основной (нет ограничения в 72 байта), bcrypt для совместимости со старыми паролями
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


class LogEntry(Base):
    """Модель записи лога в базе данных."""

    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level = Column(String(10), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    agent_name = Column(String(100))
    phase = Column(String(100))
    meta_data = Column(JSON, nullable=True)  # Дополнительные данные (ошибки, метрики, etc.) - переименовано из 'metadata' (зарезервированное имя в SQLAlchemy)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_logs_request_id', 'request_id'),
        Index('idx_logs_user_id', 'user_id'),
        Index('idx_logs_timestamp', 'timestamp'),
        Index('idx_logs_level', 'level'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "level": self.level,
            "message": self.message,
            "agent_name": self.agent_name,
            "phase": self.phase,
            "metadata": self.meta_data,  # Возвращаем как 'metadata' для обратной совместимости API
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """Модель пользователя."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    is_email_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_users_email', 'email'),
        Index('ix_users_username', 'username'),
        Index('ix_users_id', 'id'),
    )

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Хеширует пароль с использованием Argon2.
        
        Argon2 не имеет ограничения по длине пароля (в отличие от bcrypt с 72 байтами).
        Новые пароли будут хешироваться с Argon2.
        """
        return pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        """
        Проверяет пароль.
        
        Поддерживает проверку как Argon2 (новые), так и bcrypt (старые) хешей.
        """
        return pwd_context.verify(password, self.hashed_password)

    def needs_rehash(self) -> bool:
        """
        Проверяет, нужно ли перехешировать пароль (если это старый bcrypt хеш).
        
        Returns:
            True если пароль нужно перехешировать в Argon2
        """
        return self.hashed_password.startswith("$2b$") or self.hashed_password.startswith("$2a$")

    def to_dict(self) -> dict[str, Any]:
        """Преобразует в словарь (без пароля)."""
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "is_email_verified": self.is_email_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class PasswordResetToken(Base):
    """Модель токена для восстановления пароля."""

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index('ix_password_reset_tokens_token', 'token'),
        Index('ix_password_reset_tokens_user_id', 'user_id'),
        Index('ix_password_reset_tokens_expires_at', 'expires_at'),
    )


class UserSession(Base):
    """Модель сессии пользователя."""

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    username = Column(String(100), nullable=False)
    session_token = Column(String(255), nullable=False, unique=True, index=True)
    token_hash = Column(String(255), nullable=True, index=True)  # Хеш токена для безопасности
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_activity = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_address = Column(String(45))  # IPv6 может быть до 45 символов
    user_agent = Column(Text)
    is_active = Column(String(10), default="true", nullable=False)  # "true" или "false" для совместимости
    ended_at = Column(DateTime, nullable=True)
    user_id_fk = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", back_populates="sessions")

    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_sessions_user_id', 'user_id'),
        Index('idx_sessions_token', 'session_token'),
        Index('idx_sessions_token_hash', 'token_hash'),
        Index('idx_sessions_started_at', 'started_at'),
        Index('idx_sessions_active', 'is_active'),
        Index('idx_sessions_token_active', 'session_token', 'is_active'),
        Index('idx_sessions_user_activity', 'user_id', 'last_activity'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "session_token": self.session_token,
            "token_hash": self.token_hash,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "is_active": self.is_active == "true",
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class RequestLog(Base):
    """Модель для логирования HTTP запросов."""

    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), index=True)
    method = Column(String(10), nullable=False)  # GET, POST, PUT, DELETE и т.д.
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False, index=True)
    request_body = Column(JSON, nullable=True)  # Тело запроса (с маскированием чувствительных данных)
    response_time_ms = Column(Integer, nullable=True)  # Время ответа в миллисекундах
    ip_address = Column(String(45))  # IPv6 может быть до 45 символов
    user_agent = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_request_logs_request_id', 'request_id'),
        Index('idx_request_logs_user_id', 'user_id'),
        Index('idx_request_logs_timestamp', 'timestamp'),
        Index('idx_request_logs_status', 'status_code'),
        Index('idx_request_logs_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_request_logs_path', 'path'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "request_body": self.request_body,
            "response_time_ms": self.response_time_ms,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GenerationResult(Base):
    """Основная таблица для хранения результатов генерации README."""

    __tablename__ = "generation_results"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), nullable=False, unique=True, index=True)
    user_id = Column(String(100), index=True)

    seed_data = Column(JSON, nullable=True)
    markdown = Column(Text, nullable=True)
    text_stats = Column(JSON, nullable=True)
    task_plan = Column(JSON, nullable=True)
    issues = Column(JSON, nullable=True)
    practice_critic_issues = Column(JSON, nullable=True)
    agent_config_versions = Column(JSON, nullable=True)
    flow_trace = Column(JSON, nullable=True)

    regenerated_markdown = Column(Text, nullable=True)
    regeneration_comments = Column(Text, nullable=True)
    regeneration_changes = Column(JSON, nullable=True)
    original_markdown = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    rubric = relationship("RubricResult", back_populates="generation", uselist=False, cascade="all, delete-orphan")
    report = relationship("ReportResult", back_populates="generation", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_gen_results_request_id', 'request_id'),
        Index('idx_gen_results_user_id', 'user_id'),
        Index('idx_gen_results_created_at', 'created_at'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "seed_data": self.seed_data,
            "markdown": self.markdown,
            "text_stats": self.text_stats,
            "task_plan": self.task_plan,
            "issues": self.issues,
            "practice_critic_issues": self.practice_critic_issues,
            "agent_config_versions": self.agent_config_versions,
            "flow_trace": self.flow_trace,
            "regenerated_markdown": self.regenerated_markdown,
            "regeneration_comments": self.regeneration_comments,
            "regeneration_changes": self.regeneration_changes,
            "original_markdown": self.original_markdown,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PausedGenerationSession(Base):
    """Durable pause/resume state for methodology human-in-the-loop gates."""

    __tablename__ = "paused_generation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), nullable=False, unique=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="needs_review", index=True)

    project_seed = Column(JSON, nullable=True)
    track_paths = Column(JSON, nullable=True)
    context_payload = Column(JSON, nullable=True)
    steps_payload = Column(JSON, nullable=True)
    resume_from_index = Column(Integer, nullable=False, default=0)
    methodology = Column(JSON, nullable=True)
    review_actions = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_paused_gen_request_id', 'request_id'),
        Index('idx_paused_gen_user_id', 'user_id'),
        Index('idx_paused_gen_status', 'status'),
        Index('idx_paused_gen_created_at', 'created_at'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь без разворачивания context payload."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "status": self.status,
            "project_seed": self.project_seed,
            "track_paths": self.track_paths,
            "resume_from_index": self.resume_from_index,
            "methodology": self.methodology,
            "review_actions": self.review_actions or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RubricResult(Base):
    """Таблица для хранения полных rubric.json."""

    __tablename__ = "rubric_results"

    id = Column(Integer, primary_key=True, index=True)
    generation_result_id = Column(
        Integer,
        ForeignKey("generation_results.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    rubric_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    generation = relationship("GenerationResult", back_populates="rubric")

    __table_args__ = (
        Index('idx_rubric_gen_id', 'generation_result_id'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "generation_result_id": self.generation_result_id,
            "rubric_data": self.rubric_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReportResult(Base):
    """Таблица для хранения сокращённых report.json."""

    __tablename__ = "report_results"

    id = Column(Integer, primary_key=True, index=True)
    generation_result_id = Column(
        Integer,
        ForeignKey("generation_results.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    report_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    generation = relationship("GenerationResult", back_populates="report")

    __table_args__ = (
        Index('idx_report_gen_id', 'generation_result_id'),
    )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует запись в словарь."""
        return {
            "id": self.id,
            "generation_result_id": self.generation_result_id,
            "report_data": self.report_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
