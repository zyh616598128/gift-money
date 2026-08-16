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
        # date 必须是严格 YYYY-MM-DD（系统级最后防线：任何入口——MCP、REST、
        # 批量、未来代码——都无法写入非标准日期，避免脏数据逐入口漏检）。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                date TEXT NOT NULL CHECK(date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wechat_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT 'wechat',
                external_id TEXT NOT NULL,
                nickname TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(channel, external_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL DEFAULT 'wechat',
                external_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'received',
                response TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(channel, message_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT 'wechat',
                external_id TEXT NOT NULL DEFAULT '',
                parsed_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                confirmed_at TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wechat_bind_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # ── 渠道一键绑定码 (channel-agnostic) ──
        # 用户未绑定时，聊天 bot 回复一个短码绑定链接（?c=CODE）。点开后在网页
        # 登录/确认，code 即绑定到当前登录账号。短码 URL 不会被聊天客户端截断。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_bind_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL,
                external_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # ── Migration: enforce a strict YYYY-MM-DD CHECK on transactions.date ──
        # SQLite cannot ALTER TABLE to add a CHECK, so an existing table created
        # before this constraint is rebuilt in place (copy → drop → recreate →
        # copy back). The rebuild tolerates legacy dirty dates by normalizing
        # them in SQL during the copy, so historical rows survive the migration.
        # This is the system boundary that guarantees no future write path can
        # persist a non-ISO date. The whole rebuild is wrapped in a savepoint so
        # a failure rolls back atomically.
        try:
            txn_sql = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='transactions'"
            ).fetchone()
            needs_rebuild = bool(txn_sql) and "CHECK(date GLOB" not in (txn_sql["sql"] or "")
            if needs_rebuild:
                logger.info("transactions table lacks date CHECK — migrating (rebuild with strict date constraint)")
                cursor.execute("SAVEPOINT migrate_tx_date_check")
                cursor.execute("PRAGMA foreign_keys=OFF")
                try:
                    # Stage 1: copy rows into a CHECK-free staging table.
                    cursor.execute("ALTER TABLE transactions RENAME TO transactions_old")
                    cursor.execute("""
                        CREATE TABLE transactions_staging (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL DEFAULT 1,
                            name TEXT NOT NULL,
                            amount REAL NOT NULL,
                            category TEXT NOT NULL DEFAULT '其他',
                            date TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            note TEXT DEFAULT '',
                            person_id INTEGER,
                            created_at TEXT DEFAULT (datetime('now', 'localtime'))
                        )
                    """)
                    # Legacy dirty dates (中文/无格式) are repaired inline:
                    #   - '今天'/'今日'/'昨天'/'昨日'/'前天'/'大前天' → relative date
                    #   - YYYYMMDD (8 digits) → YYYY-MM-DD
                    #   - anything else → created_at's date, else 1970-01-01
                    cursor.execute("""
                        INSERT INTO transactions_staging
                            (id, user_id, name, amount, category, date, direction, note, person_id, created_at)
                        SELECT id, user_id, name, amount, category,
                               CASE
                                 WHEN date IN ('今天','今日') THEN date('now','localtime')
                                 WHEN date IN ('昨天','昨日') THEN date('now','localtime','-1 day')
                                 WHEN date IN ('前天') THEN date('now','localtime','-2 day')
                                 WHEN date IN ('大前天') THEN date('now','localtime','-3 day')
                                 WHEN length(date) = 8 AND date GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                                   THEN substr(date,1,4) || '-' || substr(date,5,2) || '-' || substr(date,7,2)
                                 WHEN date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN date
                                 WHEN created_at IS NOT NULL AND length(created_at) >= 10 THEN substr(created_at,1,10)
                                 ELSE '1970-01-01'
                               END,
                               direction, note, person_id, created_at
                        FROM transactions_old
                    """)
                    cursor.execute("DROP TABLE transactions_old")

                    # Stage 2: recreate the real table WITH the date CHECK and
                    # move the (now clean) rows into it.
                    cursor.execute("""
                        CREATE TABLE transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL DEFAULT 1,
                            name TEXT NOT NULL,
                            amount REAL NOT NULL,
                            category TEXT NOT NULL DEFAULT '其他',
                            date TEXT NOT NULL CHECK(date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
                            direction TEXT NOT NULL CHECK(direction IN ('income', 'expense')),
                            note TEXT DEFAULT '',
                            person_id INTEGER,
                            created_at TEXT DEFAULT (datetime('now', 'localtime')),
                            FOREIGN KEY (user_id) REFERENCES users(id),
                            FOREIGN KEY (person_id) REFERENCES people(id)
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO transactions
                            (id, user_id, name, amount, category, date, direction, note, person_id, created_at)
                        SELECT id, user_id, name, amount, category, date, direction, note, person_id, created_at
                        FROM transactions_staging
                    """)
                    cursor.execute("DROP TABLE transactions_staging")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("RELEASE SAVEPOINT migrate_tx_date_check")
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT migrate_tx_date_check")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    raise
        except Exception as e:
            logger.warning(f"transactions date-check migration skipped: {e}")

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
            "CREATE INDEX IF NOT EXISTS idx_wechat_accounts_external ON wechat_accounts(channel, external_id)",
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_external ON chat_messages(channel, external_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_transaction_drafts_user ON transaction_drafts(user_id, status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_wechat_bind_codes_user ON wechat_bind_codes(user_id, status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_wechat_bind_codes_code ON wechat_bind_codes(code, status)",
            "CREATE INDEX IF NOT EXISTS idx_channel_bind_codes_code ON channel_bind_codes(code, status)",
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
