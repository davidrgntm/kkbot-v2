PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    telegram_id TEXT NOT NULL,
    username TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    full_name TEXT NOT NULL,
    role TEXT DEFAULT 'staff',
    active INTEGER DEFAULT 1,
    hourly_rate REAL DEFAULT 0,
    emoji TEXT DEFAULT '🙂',
    department TEXT DEFAULT '',
    position TEXT DEFAULT '',
    hire_date TEXT DEFAULT '',
    avatar_file_id TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lat REAL,
    lon REAL,
    radius_m INTEGER DEFAULT 500,
    active INTEGER DEFAULT 1,
    UNIQUE(company_id, name)
);

CREATE TABLE IF NOT EXISTS user_shops (
    user_id INTEGER NOT NULL,
    shop_id INTEGER NOT NULL,
    UNIQUE(user_id, shop_id)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    user_id INTEGER,
    telegram_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    shop_id INTEGER,
    shop TEXT DEFAULT '',
    work_date TEXT NOT NULL,
    kind TEXT DEFAULT 'shift',
    status_code TEXT DEFAULT '',
    start_time TEXT DEFAULT '',
    end_time TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    user_id INTEGER,
    telegram_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    shop_id INTEGER,
    shop TEXT DEFAULT '',
    business_date TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    status TEXT DEFAULT 'open',
    start_photo_id TEXT DEFAULT '',
    end_photo_id TEXT DEFAULT '',
    start_location TEXT DEFAULT '',
    end_location TEXT DEFAULT '',
    worked_minutes INTEGER DEFAULT 0,
    break_minutes INTEGER DEFAULT 0,
    late_minutes INTEGER DEFAULT 0,
    source TEXT DEFAULT 'bot',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    actor_tid TEXT DEFAULT '',
    actor_role TEXT DEFAULT '',
    action TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
