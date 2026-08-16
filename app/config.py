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

    # Public base URL for outbound links (channel bind links etc.)
    web_base_url: str = os.environ.get("GIFT_MONEY_WEB_BASE_URL", os.environ.get("WEB_BASE_URL", "https://www.wanpingshipin.cloud"))

    # WeChat integration
    wechat_token: str = os.environ.get("GIFT_MONEY_WECHAT_TOKEN", os.environ.get("WECHAT_TOKEN", ""))
    wechat_default_user_id: int = int(os.environ.get("GIFT_MONEY_WECHAT_DEFAULT_USER_ID", "1"))
    wechat_require_binding: bool = os.environ.get("GIFT_MONEY_WECHAT_REQUIRE_BINDING", "true").lower() in ("1", "true", "yes", "on")
    # WeChat 接口测试号 OAuth (snsapi_base) —— 免费拿 openid 完成一键绑定
    wechat_app_id: str = os.environ.get("GIFT_MONEY_WECHAT_APP_ID", os.environ.get("WECHAT_APP_ID", ""))
    wechat_app_secret: str = os.environ.get("GIFT_MONEY_WECHAT_APP_SECRET", os.environ.get("WECHAT_APP_SECRET", ""))
    wechat_oauth_redirect_uri: str = os.environ.get("GIFT_MONEY_WECHAT_OAUTH_REDIRECT_URI", "")
    # 测试号 gh 账号 → 关注二维码 (open.weixin.qq.com/qr/code?username=gh_xxx)
    wechat_test_account: str = os.environ.get("GIFT_MONEY_WECHAT_TEST_ACCOUNT", os.environ.get("WECHAT_TEST_ACCOUNT", "gh_434b155e059c"))

    # MCP integration. Set this in production and pass it as X-MCP-Token.
    mcp_api_token: str = os.environ.get("GIFT_MONEY_MCP_API_TOKEN", "")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
