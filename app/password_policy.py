"""Password policy and validation utilities."""
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def validate_password(password: str) -> Tuple[bool, str]:
    """
    Validate password strength.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 6:
        return False, "密码长度至少6位"
    
    # 检查是否包含字母和数字
    has_letter = bool(re.search(r'[a-zA-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    
    if not has_letter or not has_digit:
        return False, "密码必须包含字母和数字"
    
    return True, ""


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    import bcrypt
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    import bcrypt
    try:
        # 处理可能的编码问题
        if isinstance(password_hash, bytes):
            password_hash = password_hash.decode('utf-8')
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8') if isinstance(password_hash, str) else password_hash
        )
    except Exception as e:
        logger.error(f"密码验证失败: {e}")
        return False