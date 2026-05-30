"""Database initialization and connection."""
import os
import sqlite3
import bcrypt
import jwt
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = settings.jwt_algorithm
JWT_EXPIRE_HOURS = settings.jwt_expire_hours
DB_PATH = settings.db_path


def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database tables and indexes."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # ── Users ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # ── Transactions (system core) ──
        # 只保留 category 字段，移除 event_type
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                date TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('income', 'expense')),
                note TEXT DEFAULT '',
                person_id INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (person_id) REFERENCES people(id)
            )
        """)

        # ── Categories (简化：只有 name 和 color) ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#6366f1',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # ── People ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # ── Indexes ──
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tx_user_name ON transactions(user_id, name)",
            "CREATE INDEX IF NOT EXISTS idx_tx_user_category ON transactions(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_tx_user_direction ON transactions(user_id, direction)",
            "CREATE INDEX IF NOT EXISTS idx_tx_user_person ON transactions(user_id, person_id)",
            "CREATE INDEX IF NOT EXISTS idx_tx_user_created ON transactions(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_people_user ON people(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_people_user_name ON people(user_id, name)",
            "CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_categories_user_name ON categories(user_id, name)",
        ]
        for idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
            except Exception:
                pass

        # ── People unique constraint: (user_id, name, address) ──
        try:
            # 删除旧的错误索引（如果存在）
            cursor.execute("DROP INDEX IF EXISTS idx_people_name_note")
            # 创建正确的唯一索引：user_id + name + address
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_people_name_address ON people(user_id, name, address)")
        except Exception:
            pass

        # ── Categories: (user_id, name) unique ──
        try:
            # 先删除旧的唯一约束（如果存在）
            cursor.execute("DROP INDEX IF EXISTS sqlite_autoindex_categories_1")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_user_name_unique ON categories(user_id, name)")
        except Exception:
            pass

        # ── Default admin ──
        admin_exists = cursor.execute(
            "SELECT id FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        if not admin_exists:
            # 生成随机密码而不是使用固定密码
            import secrets
            import string
            # 生成一个安全的随机密码
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            random_password = ''.join(secrets.choice(chars) for _ in range(12))
            pwd_hash = bcrypt.hashpw(random_password.encode('utf-8'), bcrypt.gensalt()).decode()
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?, ?, ?, ?)",
                ("admin", pwd_hash, "管理员", 1),
            )
            logger.info("默认管理员账户已创建，用户名: admin, 初始密码已生成（请妥善保存）")

        # ── Default categories (简化版) ──
        from app.constants import CATEGORIES
        default_colors = {
            "婚嫁": "#f59e0b",
            "丧葬": "#6b7280",
            "生日": "#8b5cf6",
            "乔迁": "#10b981",
            "开业": "#ef4444",
            "生育": "#ec4899",
            "探病": "#06b6d4",
            "其他": "#6366f1",
        }
        for cat in CATEGORIES:
            color = default_colors.get(cat, "#6366f1")
            cursor.execute(
                "INSERT OR IGNORE INTO categories (name, color, user_id) VALUES (?, ?, ?)",
                (cat, color, 1),
            )

        conn.commit()
        logger.info("数据库初始化完成")
    except Exception as e:
        conn.rollback()
        logger.error(f"数据库初始化失败: {e}")
        raise
    finally:
        conn.close()


def create_token(user_id: int, username: str, is_admin: bool) -> str:
    """Create JWT token."""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Verify JWT token and return payload."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def backup_database() -> str:
    """Create a backup of the database. Returns the backup file path."""
    if not settings.backup_path:
        logger.warning("备份路径未配置，跳过备份")
        return ""

    backup_dir = Path(settings.backup_path)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"gift_money_backup_{timestamp}.db"

    try:
        shutil.copy2(DB_PATH, backup_file)
        logger.info(f"数据库备份完成: {backup_file}")
        return str(backup_file)
    except Exception as e:
        logger.error(f"数据库备份失败: {e}")
        return ""
