import sqlite3
import logging
import os
import time

# SaaS mapping bazasi ham asosiy DB bilan bir xil persistent papkada saqlanadi.
_main_db_path = os.environ.get("DB_PATH", os.path.join("data", "kkbot.db"))
DB_FOLDER = os.environ.get("DB_FOLDER") or os.path.dirname(_main_db_path) or "data"
DB_NAME = os.path.join(DB_FOLDER, "saas.db")

class SaasDB:
    def __init__(self):
        # Papka borligini tekshiramiz, yo'q bo'lsa yaratamiz
        if not os.path.exists(DB_FOLDER):
            os.makedirs(DB_FOLDER)
            
        # Check_same_thread=False multithreading uchun kerak
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self._company_cache = {}
        self._company_cache_ttl = 60

    def create_tables(self):
        # 1. Kompaniyalar jadvali (Mijozlar)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sheet_id TEXT NOT NULL,
                admin_id INTEGER NOT NULL,
                active BOOLEAN DEFAULT 1
            )
        """)
        
        # 2. Xodimlar va Kompaniya bog'liqligi
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                company_id INTEGER,
                role TEXT DEFAULT 'staff',
                FOREIGN KEY(company_id) REFERENCES companies(id)
            )
        """)
        self.conn.commit()

    # --- KOMPANIYA BOShQARUVI ---
    def add_company(self, name, sheet_id, admin_id):
        try:
            self.cursor.execute("INSERT INTO companies (name, sheet_id, admin_id) VALUES (?, ?, ?)", 
                                (name, sheet_id, admin_id))
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            logging.error(f"Kompaniya qo'shishda xato: {e}")
            return None

    def get_company_by_user(self, telegram_id):
        cached = self._company_cache.get(int(telegram_id))
        now = time.time()
        if cached and now - cached[1] < self._company_cache_ttl:
            return cached[0]
        res = self.cursor.execute("""
            SELECT c.id, c.name, c.sheet_id 
            FROM users u 
            JOIN companies c ON u.company_id = c.id 
            WHERE u.telegram_id = ?
        """, (telegram_id,)).fetchone()
        
        value = {'id': res[0], 'name': res[1], 'sheet_id': res[2]} if res else None
        self._company_cache[int(telegram_id)] = (value, now)
        return value

    # --- FOYDALANUVCHI BOShQARUVI ---
    def register_user(self, telegram_id, company_id, role="staff"):
        try:
            self.cursor.execute("INSERT OR REPLACE INTO users (telegram_id, company_id, role) VALUES (?, ?, ?)", 
                                (telegram_id, company_id, role))
            self.conn.commit()
            self._company_cache.pop(int(telegram_id), None)
            return True
        except Exception as e:
            logging.error(f"User register xatosi: {e}")
            return False

saas_db = SaasDB()
