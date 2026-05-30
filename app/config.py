"""Application configuration management."""
import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # JWT Configuration
    jwt_secret: str = os.environ.get("GIFT_MONEY_JWT_SECRET", "gift-money-secret-key-change-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # Database
    db_path: Path = Path(__file__).parent.parent / "gift_money.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    cors_origins: List[str] = []

    # Logging
    log_level: str = "INFO"

    # Backup
    backup_path: str = ""

    # Password Policy
    min_password_length: int = 6

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
