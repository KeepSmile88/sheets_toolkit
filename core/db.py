import sqlite3
import hashlib
import os
import base64

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "sheets.db")

def _hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 对密码进行哈希加密"""
    salt = os.urandom(16)
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return "pbkdf2:sha256:100000$" + salt.hex() + "$" + pwdhash.hex()

def init_db():
    """初始化数据库并设置默认管理员密码（如果不存在）"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT
            )
        """)
        
        # 将可能已存在的老 admin 密码迁移到 users 表（如果有）
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_password'")
        old_admin = cursor.fetchone()
        if old_admin:
            # 将其插入到 users 并且删除老的
            cursor.execute("INSERT OR IGNORE INTO users (username, password_hash) VALUES ('admin', ?)", (old_admin[0],))
            cursor.execute("DELETE FROM settings WHERE key = 'admin_password'")
        
        # 检查是否已有管理员密码
        cursor.execute("SELECT password_hash FROM users WHERE username = 'admin'")
        result = cursor.fetchone()
        
        if not result:
            default_pw = base64.b64decode("YWRtaW5fMUAzJC4=").decode("utf-8")
            default_hash = _hash_password(default_pw)
            cursor.execute("INSERT INTO users (username, password_hash) VALUES ('admin', ?)", (default_hash,))

def has_password(username: str) -> bool:
    """检查指定用户是否设置了密码"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        return bool(result and result[0])

def verify_password(username: str, password: str) -> bool:
    """校验用户的密码是否正确"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        
    if result and result[0]:
        stored_hash = result[0]
        if stored_hash.startswith("pbkdf2:sha256:"):
            try:
                parts = stored_hash.split("$")
                salt = bytes.fromhex(parts[1])
                hash_val = parts[2]
                pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
                return pwdhash.hex() == hash_val
            except Exception:
                return False
        return False
    # 如果该用户本来就没有密码，输入为空则算正确
    return not password

def update_password(username: str, new_password: str):
    """更新或设置用户的密码"""
    new_hash = _hash_password(new_password) if new_password else ""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash
        """, (username, new_hash))

# 在模块加载时自动初始化数据库
init_db()
