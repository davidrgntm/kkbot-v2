from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional
import calendar

from config import config
from utils.ctx import sheet_id_ctx

logger = logging.getLogger(__name__)

DB_FOLDER = os.environ.get("DB_FOLDER", "data")
DB_PATH = os.environ.get("DB_PATH") or getattr(config, "db_path", os.path.join(DB_FOLDER, "kkbot.db"))

STATUS_LABELS = {
    "day_off": "Dam olish",
    "vacation": "отпуск",
    "sick_leave": "больничный",
}


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").strip().lower() if ch.isalnum())


def _money(v: float) -> float:
    return round(float(v or 0), 2)


def _parse_date(value: str | Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value or "").strip().replace("/", ".").replace("-", ".")
    for fmt in ["%d.%m.%Y", "%d.%m.%y", "%Y.%m.%d"]:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _date_to_iso(d: date | str | None) -> str | None:
    parsed = _parse_date(d) if d is not None else None
    return parsed.isoformat() if parsed else None


def _time_to_minutes(time_str: str) -> int:
    h, m = map(int, str(time_str).strip().split(":"))
    total = h * 60 + m
    # Bizning grafiklarda 00:00-02:00 odatda tungi smena oxiri sifatida keladi.
    if h < 8:
        total += 24 * 60
    return total


def _hours_between(start: str, end: str) -> float:
    try:
        return max(0.0, (_time_to_minutes(end) - _time_to_minutes(start)) / 60)
    except Exception:
        return 0.0


def _format_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes or 0))
    h = minutes // 60
    m = minutes % 60
    return f"{h} ч {m:02d} м"

def _legacy_paid_minutes_from_total(total_minutes: int) -> tuple[int, int]:
    """Eski botdagi oylik/tabel qoidasini aynan takrorlaydi.

    Eski logika:
    - minutlar alohida saqlanmaydi; 30 minut va undan ko'p bo'lsa 1 soat qo'shiladi;
    - yaxlitlangan soat 5 yoki undan ko'p bo'lsa 1 soat tushlik ayriladi;
    - natija doim to'liq soat: 8 ч 00 м.
    """
    total_minutes = max(0, int(total_minutes or 0))
    h = total_minutes // 60
    m = total_minutes % 60
    if m >= 30:
        h += 1
    break_minutes = 60 if h >= 5 else 0
    if h >= 5:
        h -= 1
    return max(0, h * 60), break_minutes


def _legacy_paid_minutes_between(start_at: datetime, end_at: datetime) -> tuple[int, int, int]:
    raw_minutes = max(0, int((end_at - start_at).total_seconds() // 60))
    paid_minutes, break_minutes = _legacy_paid_minutes_from_total(raw_minutes)
    return raw_minutes, paid_minutes, break_minutes


def _legacy_paid_minutes_from_times(start: str, end: str) -> tuple[int, int, int]:
    try:
        raw = max(0, _time_to_minutes(end) - _time_to_minutes(start))
    except Exception:
        raw = 0
    paid, br = _legacy_paid_minutes_from_total(raw)
    return raw, paid, br


def _hours_from_worked(worked: str, start: str = "", end: str = "") -> float:
    s = str(worked or "").strip().lower()
    if s:
        try:
            h = 0
            m = 0
            if "ч" in s:
                h = int(s.split("ч")[0].strip() or 0)
                rest = s.split("ч", 1)[1]
                if "м" in rest:
                    raw_m = "".join(ch for ch in rest.split("м")[0] if ch.isdigit())
                    if raw_m:
                        m = int(raw_m)
            elif ":" in s:
                hh, mm = s.split(":", 1)
                h, m = int(hh), int(mm)
            return max(0.0, h + m / 60)
        except Exception:
            pass
    return _hours_between(start, end)


def _status_from_schedule(start_value: str) -> Optional[str]:
    raw = str(start_value or "").strip()
    if raw.startswith("STATUS:"):
        return raw.split(":", 1)[1].strip()
    return None


class SQLiteWorksheetAdapter:
    """Compatibility layer for old handlers that used gspread worksheet methods."""

    def __init__(self, db: "AsyncSQLiteDB", title: str):
        self.db = db
        self.title = title

    async def row_values(self, row_index: int) -> list[str]:
        if self.title == "Смены":
            row = await self.db.get_shift_by_id(row_index)
            if not row:
                return []
            return [
                row["date"].strftime("%d-%m-%Y"),
                str(row["telegram_id"]),
                row.get("name", ""),
                row.get("shop", ""),
                row.get("start", ""),
                row.get("end", ""),
                row.get("worked", ""),
                row.get("photo_id", ""),
                row.get("location", ""),
            ]
        if self.title == "График":
            row = await self.db.get_schedule_by_id(row_index)
            if not row:
                return []
            return [
                row["date"].strftime("%d-%m-%Y"),
                row.get("name", ""),
                str(row.get("telegram_id", "")),
                row.get("shop", ""),
                row.get("start", ""),
                row.get("end", ""),
            ]
        if self.title == "Сотрудники" and int(row_index) == 1:
            return ["TelegramID", "Username", "Phone", "Имя", "Роль", "Магазин", "Активен", "Ставка", "Смайлик"]
        return []

    async def get_all_values(self) -> list[list[str]]:
        if self.title == "Смены":
            rows = [["Дата", "TelegramID", "Имя", "Магазин", "Время начала", "Время конца", "Отработано", "photo_id", "location"]]
            for r in await self.db.get_shift_rows():
                rows.append([
                    r["date"].strftime("%d-%m-%Y"), str(r["telegram_id"]), r.get("name", ""), r.get("shop", ""),
                    r.get("start", ""), r.get("end", ""), r.get("worked", ""), r.get("photo_id", ""), r.get("location", ""),
                ])
            return rows
        if self.title == "График":
            rows = [["Дата", "Имя", "TelegramID", "Магазин", "Время начала", "Время конца"]]
            for r in await self.db.get_schedule_rows():
                rows.append([r["date"].strftime("%d-%m-%Y"), r.get("name", ""), str(r.get("telegram_id", "")), r.get("shop", ""), r.get("start", ""), r.get("end", "")])
            return rows
        if self.title == "Сотрудники":
            rows = [["TelegramID", "Username", "Phone", "Имя", "Роль", "Магазин", "Активен", "Ставка", "Смайлик"]]
            for s in await self.db.get_all_staff(force_refresh=True):
                rows.append([str(s.get("TelegramID", "")), s.get("Username", ""), s.get("Phone", ""), s.get("Имя", ""), s.get("Роль", "staff"), s.get("Магазин", ""), s.get("Активен", "TRUE"), str(s.get("Ставка", "0")), s.get("Смайлик", "🙂")])
            return rows
        if self.title == "Магазины":
            rows = [["Магазин", "Lat", "Lon"]]
            for sh in await self.db.get_shops_with_coords():
                rows.append([sh["name"], "" if sh.get("lat") is None else str(sh["lat"]), "" if sh.get("lon") is None else str(sh["lon"])])
            return rows
        return []

    async def col_values(self, col: int) -> list[str]:
        values = await self.get_all_values()
        idx = int(col) - 1
        return [r[idx] if len(r) > idx else "" for r in values]

    async def update_cell(self, row: int, col: int, value: str):
        if self.title == "График":
            await self.db.update_schedule_cell(row, col, value)
            return True
        if self.title == "Смены":
            await self.db.update_shift_cell(row, col, value)
            return True
        if self.title == "Сотрудники":
            return True
        return True

    async def delete_rows(self, row: int):
        if self.title == "График":
            return await self.db.delete_schedule_row(row)
        if self.title == "Смены":
            return await self.db.delete_shift_row(row)
        return True

    async def append_row(self, row: list[str]):
        if self.title == "Смены":
            # Compatibility only. Main code should call start_shift().
            return True
        return True

    async def insert_row(self, row: list[str], index: int):
        return True

    async def batch_update(self, updates: list[dict]):
        for upd in updates:
            rng = upd.get("range", "")
            vals = upd.get("values", [[""]])
            value = vals[0][0] if vals and vals[0] else ""
            # Simple ranges like F12 or G12.
            if len(rng) >= 2:
                col_letter = rng[0].upper()
                try:
                    row = int(rng[1:])
                    col = ord(col_letter) - ord("A") + 1
                    await self.update_cell(row, col, value)
                except Exception:
                    pass
        return True


class AsyncSQLiteDB:
    _instance = None

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._init_db()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _current_cid(self) -> str:
        """Return the company_id that contains the real imported data.

        Old SaaS mappings or auto-created admin rows can point handlers to an
        empty company_id. This guard always prefers the context that actually
        has users + shops + shifts in SQLite.
        """
        forced = os.environ.get("FORCE_COMPANY_ID")
        if forced:
            return str(forced)

        requested = str(sheet_id_ctx.get() or config.google_sheet_id or "default")

        def counts(cid: str) -> tuple[int, int, int]:
            try:
                u = self.conn.execute("SELECT COUNT(*) AS c FROM users WHERE company_id=? AND active=1", (cid,)).fetchone()["c"]
                sh = self.conn.execute("SELECT COUNT(*) AS c FROM shops WHERE company_id=? AND active=1", (cid,)).fetchone()["c"]
                sf = self.conn.execute("SELECT COUNT(*) AS c FROM shifts WHERE company_id=?", (cid,)).fetchone()["c"]
                return int(u or 0), int(sh or 0), int(sf or 0)
            except Exception:
                return 0, 0, 0

        req_u, req_sh, req_sf = counts(requested)
        if req_u > 1 and req_sh > 0:
            return requested

        default_cid = str(config.google_sheet_id or requested or "default")
        def_u, def_sh, def_sf = counts(default_cid)
        if def_u > 1 and def_sh > 0:
            return default_cid

        try:
            row = self.conn.execute("""
                SELECT company_id,
                       (SELECT COUNT(*) FROM users u2 WHERE u2.company_id=base.company_id AND u2.active=1) AS users_count,
                       (SELECT COUNT(*) FROM shops s WHERE s.company_id=base.company_id AND s.active=1) AS shops_count,
                       (SELECT COUNT(*) FROM shifts sh WHERE sh.company_id=base.company_id) AS shifts_count
                FROM (
                    SELECT company_id FROM users
                    UNION SELECT company_id FROM shops
                    UNION SELECT company_id FROM shifts
                    UNION SELECT company_id FROM schedules
                ) base
                ORDER BY shifts_count DESC, shops_count DESC, users_count DESC
                LIMIT 1
            """).fetchone()
            if row and row["company_id"]:
                return str(row["company_id"])
        except Exception:
            pass

        return requested

    def _now(self) -> datetime:
        return datetime.now(config.get_timezone_obj())

    def _init_db(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=5000")
            c.executescript(
                """
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

                CREATE INDEX IF NOT EXISTS idx_schedules_lookup ON schedules(company_id, telegram_id, work_date);

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

                CREATE INDEX IF NOT EXISTS idx_shifts_active ON shifts(company_id, telegram_id, status, start_at);
                CREATE INDEX IF NOT EXISTS idx_shifts_dates ON shifts(company_id, business_date);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    actor_tid TEXT DEFAULT '',
                    actor_role TEXT DEFAULT '',
                    action TEXT NOT NULL,
                    payload TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS employee_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    user_id INTEGER,
                    type TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    manager_comment TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    user_id INTEGER,
                    item_name TEXT NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    given_date TEXT,
                    returned_date TEXT,
                    status TEXT DEFAULT 'given'
                );

                CREATE TABLE IF NOT EXISTS export_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    export_type TEXT NOT NULL,
                    period_start TEXT,
                    period_end TEXT,
                    status TEXT DEFAULT 'pending',
                    google_sheet_id TEXT DEFAULT '',
                    created_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT
                );
                """
            )
            self.conn.commit()

    def _execute(self, sql: str, params: tuple = (), fetch: str | None = None):
        with self.lock:
            cur = self.conn.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            self.conn.commit()
            return cur

    def _ensure_shop_sync(self, name: str, lat: float | None = None, lon: float | None = None) -> Optional[int]:
        name = str(name or "").strip()
        if not name:
            return None
        cid = self._current_cid()
        with self.lock:
            row = self.conn.execute("SELECT id FROM shops WHERE company_id=? AND name=?", (cid, name)).fetchone()
            if row:
                sid = int(row["id"])
                if lat is not None or lon is not None:
                    self.conn.execute("UPDATE shops SET lat=COALESCE(?, lat), lon=COALESCE(?, lon), active=1 WHERE id=?", (lat, lon, sid))
                    self.conn.commit()
                return sid
            cur = self.conn.execute("INSERT INTO shops(company_id, name, lat, lon) VALUES (?, ?, ?, ?)", (cid, name, lat, lon))
            self.conn.commit()
            return int(cur.lastrowid)

    def _ensure_user_sync(self, telegram_id: str | int, name: str = "Xodim", role: str = "staff", shop: str = "", active: int = 1) -> Optional[int]:
        cid = self._current_cid()
        tid = str(telegram_id).replace(".0", "").strip()
        if not tid:
            return None
        name = str(name or "Xodim").strip() or "Xodim"
        role = str(role or "staff").lower()
        with self.lock:
            row = self.conn.execute("SELECT id FROM users WHERE company_id=? AND telegram_id=?", (cid, tid)).fetchone()
            if row:
                uid = int(row["id"])
            else:
                cur = self.conn.execute(
                    "INSERT INTO users(company_id, telegram_id, full_name, role, active) VALUES (?, ?, ?, ?, ?)",
                    (cid, tid, name, role, int(active)),
                )
                uid = int(cur.lastrowid)
            self.conn.commit()
        if shop:
            for sh in str(shop).split(","):
                sid = self._ensure_shop_sync(sh.strip())
                if sid:
                    with self.lock:
                        self.conn.execute("INSERT OR IGNORE INTO user_shops(user_id, shop_id) VALUES (?, ?)", (uid, sid))
                        self.conn.commit()
        return uid

    def _staff_record(self, row: sqlite3.Row) -> dict:
        shops = self._execute(
            "SELECT s.name FROM shops s JOIN user_shops us ON us.shop_id=s.id WHERE us.user_id=? AND s.active=1 ORDER BY s.name",
            (row["id"],),
            "all",
        )
        shop_text = ", ".join([r["name"] for r in shops])
        return {
            "TelegramID": str(row["telegram_id"]),
            "Username": row["username"] or "",
            "Phone": row["phone"] or "",
            "Имя": row["full_name"] or "Xodim",
            "Роль": row["role"] or "staff",
            "Магазин": shop_text,
            "Активен": "TRUE" if int(row["active"] or 0) else "FALSE",
            "Ставка": row["hourly_rate"] or 0,
            "Смайлик": row["emoji"] or "🙂",
            "Должность": row["position"] or "",
            "Отдел": row["department"] or "",
            "Дата приема": row["hire_date"] or "",
        }

    async def _get_worksheet(self, title: str):
        return SQLiteWorksheetAdapter(self, title)

    def invalidate_sheet_cache(self, *titles: str):
        return None

    async def get_all_staff(self, force_refresh: bool = False, strict: bool = False) -> List[Dict]:
        try:
            rows = self._execute("SELECT * FROM users WHERE company_id=? AND active=1 ORDER BY full_name", (self._current_cid(),), "all")
            return [self._staff_record(r) for r in rows]
        except Exception as e:
            logger.exception("SQLite get_all_staff xato: %s", e)
            if strict:
                raise
            return []

    async def get_user_by_telegram_id(self, telegram_id: int, strict: bool = False) -> Optional[Dict]:
        try:
            row = self._execute(
                "SELECT * FROM users WHERE company_id=? AND telegram_id=? AND active=1",
                (self._current_cid(), str(telegram_id)),
                "one",
            )
            return self._staff_record(row) if row else None
        except Exception as e:
            if strict:
                raise
            logger.error("get_user_by_telegram_id xato: %s", e)
            return None

    async def get_staff_profile(self, telegram_id: int | str) -> Optional[dict]:
        user = await self.get_user_by_telegram_id(int(str(telegram_id).replace(".0", "")))
        if not user:
            return None
        shops = [x.strip() for x in str(user.get("Магазин", "")).split(",") if x.strip()]
        try:
            rate = float(str(user.get("Ставка", 0)).replace(" ", "").replace(",", ".")) if str(user.get("Ставка", "")).strip() else 0.0
        except Exception:
            rate = 0.0
        return {
            "telegram_id": str(user.get("TelegramID", "")).replace(".0", ""),
            "name": user.get("Имя", "Xodim"),
            "role": str(user.get("Роль", "staff")).lower(),
            "shop": user.get("Магазин", ""),
            "shops": shops,
            "active": str(user.get("Активен", "TRUE")).strip().upper() == "TRUE",
            "rate": rate,
            "emoji": user.get("Смайлик", "🙂") or "🙂",
        }

    async def update_staff_field(self, telegram_id: int | str, field_name: str, value: str) -> bool:
        cid = self._current_cid()
        tid = str(telegram_id).replace(".0", "").strip()
        key = _norm(field_name)
        try:
            row = self._execute("SELECT id FROM users WHERE company_id=? AND telegram_id=?", (cid, tid), "one")
            if not row:
                return False
            uid = int(row["id"])
            if key in {_norm("Ставка"), "rate", "hourlyrate"}:
                val = float(str(value).replace(" ", "").replace(",", ".") or 0)
                self._execute("UPDATE users SET hourly_rate=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (val, uid))
            elif key in {_norm("Смайлик"), "emoji", "smile"}:
                self._execute("UPDATE users SET emoji=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(value)[:8], uid))
            elif key in {_norm("Активен"), "active"}:
                active = 1 if str(value).strip().upper() in {"TRUE", "1", "YES", "ДА"} else 0
                self._execute("UPDATE users SET active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (active, uid))
            elif key in {_norm("Имя"), "name", "fullname"}:
                self._execute("UPDATE users SET full_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (value, uid))
            elif key in {_norm("Phone"), "phone", "telefon", _norm("Телефон")}:
                self._execute("UPDATE users SET phone=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(value), uid))
            elif key in {_norm("Username"), "username", "user"}:
                self._execute("UPDATE users SET username=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(value), uid))
            elif key in {_norm("Роль"), "role"}:
                self._execute("UPDATE users SET role=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(value).lower(), uid))
            elif key in {_norm("Магазин"), "shop"}:
                self._execute("DELETE FROM user_shops WHERE user_id=?", (uid,))
                for sh in str(value).split(","):
                    sid = self._ensure_shop_sync(sh.strip())
                    if sid:
                        self._execute("INSERT OR IGNORE INTO user_shops(user_id, shop_id) VALUES (?, ?)", (uid, sid))
            else:
                return False
            return True
        except Exception as e:
            logger.exception("update_staff_field xato: %s", e)
            return False

    async def search_staff(self, query: str = "", limit: int = 100) -> List[dict]:
        staff = await self.get_all_staff(force_refresh=False)
        q = str(query or "").strip().lower()
        out = []
        for item in staff:
            tid = str(item.get("TelegramID", "")).replace(".0", "")
            text = f"{tid} {item.get('Имя','')} {item.get('Магазин','')} {item.get('Роль','')}".lower()
            if not q or q in text:
                out.append(item)
            if len(out) >= limit:
                break
        return out

    async def get_shops(self) -> List[str]:
        rows = self._execute("SELECT name FROM shops WHERE company_id=? AND active=1 ORDER BY name", (self._current_cid(),), "all")
        return [r["name"] for r in rows]

    async def get_shops_with_coords(self) -> List[Dict]:
        rows = self._execute("SELECT name, lat, lon, radius_m FROM shops WHERE company_id=? AND active=1 ORDER BY name", (self._current_cid(),), "all")
        return [{"name": r["name"], "lat": r["lat"], "lon": r["lon"], "radius_m": r["radius_m"]} for r in rows]

    async def add_new_staff(self, tid, name, role, shop):
        try:
            uid = self._ensure_user_sync(tid, name, role, shop)
            if uid:
                self._execute("UPDATE users SET full_name=?, role=?, active=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (name, str(role).lower(), uid))
            return bool(uid)
        except Exception as e:
            logger.exception("add_new_staff xato: %s", e)
            return False

    async def deactivate_staff(self, tid):
        return await self.update_staff_field(tid, "Активен", "FALSE")

    async def get_active_shift_row(self, telegram_id: int) -> Optional[int]:
        row = self._execute(
            "SELECT id FROM shifts WHERE company_id=? AND telegram_id=? AND status='open' ORDER BY start_at DESC LIMIT 1",
            (self._current_cid(), str(telegram_id)),
            "one",
        )
        return int(row["id"]) if row else None

    async def get_active_shift(self, telegram_id: int | str) -> Optional[dict]:
        sid = await self.get_active_shift_row(int(str(telegram_id)))
        return await self.get_shift_by_id(sid) if sid else None

    async def start_shift(self, user_data: Dict, photo_id: str, location: str = "") -> bool:
        try:
            cid = self._current_cid()
            now = self._now()
            tid = str(user_data.get("TelegramID", "")).replace(".0", "").strip()
            name = user_data.get("Имя") or user_data.get("name") or "Xodim"
            shop = user_data.get("Магазин", "")
            uid = self._ensure_user_sync(tid, name, user_data.get("Роль", "staff"), shop)
            shop_id = self._ensure_shop_sync(shop)
            # Duplicate guard: a user can have only one open shift.
            existing = await self.get_active_shift_row(int(tid))
            if existing:
                return False
            # Schedule based late calculation.
            late_minutes = 0
            sched = await self.get_schedule_rows(tid, now.date(), now.date())
            for s in sched:
                if s.get("shop") == shop and not s.get("status") and s.get("start"):
                    try:
                        planned = datetime.combine(now.date(), datetime.strptime(s["start"], "%H:%M").time(), tzinfo=now.tzinfo)
                        late_minutes = max(0, int((now - planned).total_seconds() // 60))
                    except Exception:
                        late_minutes = 0
                    break
            self._execute(
                """
                INSERT INTO shifts(company_id, user_id, telegram_id, name, shop_id, shop, business_date, start_at, status, start_photo_id, start_location, late_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (cid, uid, tid, name, shop_id, shop, now.date().isoformat(), now.isoformat(), photo_id, location, late_minutes),
            )
            return True
        except Exception as e:
            logger.exception("start_shift xato: %s", e)
            return False

    async def end_shift(self, row_index: int, start_time_str: str = "", photo_id: str = "", location: str = "") -> str:
        try:
            row = self._execute("SELECT * FROM shifts WHERE company_id=? AND id=?", (self._current_cid(), int(row_index)), "one")
            if not row:
                return "Error"
            now = self._now()
            start_at = datetime.fromisoformat(row["start_at"])
            if start_at.tzinfo is None and now.tzinfo is not None:
                start_at = config.get_timezone_obj().localize(start_at) if hasattr(config.get_timezone_obj(), "localize") else start_at.replace(tzinfo=now.tzinfo)
            raw_minutes, worked_minutes, break_minutes = _legacy_paid_minutes_between(start_at, now)
            self._execute(
                """
                UPDATE shifts
                SET end_at=?, status='closed', end_photo_id=?, end_location=?, worked_minutes=?, break_minutes=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (now.isoformat(), photo_id or row["end_photo_id"], location or row["end_location"], worked_minutes, break_minutes, int(row_index)),
            )
            return _format_minutes(worked_minutes)
        except Exception as e:
            logger.exception("end_shift xato: %s", e)
            return "Error"

    async def get_shift_by_id(self, shift_id: int | str | None) -> Optional[dict]:
        if not shift_id:
            return None
        row = self._execute("SELECT * FROM shifts WHERE company_id=? AND id=?", (self._current_cid(), int(shift_id)), "one")
        return self._shift_record(row) if row else None

    def _shift_record(self, r: sqlite3.Row) -> dict:
        start_at = datetime.fromisoformat(r["start_at"])
        end_at = datetime.fromisoformat(r["end_at"]) if r["end_at"] else None
        d = _parse_date(r["business_date"]) or start_at.date()
        worked = _format_minutes(r["worked_minutes"] or 0) if r["end_at"] else ""
        return {
            "row": int(r["id"]),
            "date": d,
            "telegram_id": str(r["telegram_id"]),
            "name": r["name"] or "",
            "shop": r["shop"] or "",
            "start": start_at.strftime("%H:%M"),
            "end": end_at.strftime("%H:%M") if end_at else "",
            "worked": worked,
            "photo_id": r["start_photo_id"] or "",
            "location": r["start_location"] or "",
            "status": r["status"],
            "worked_minutes": int(r["worked_minutes"] or 0),
            "break_minutes": int(r["break_minutes"] or 0),
            "late_minutes": int(r["late_minutes"] or 0),
            "start_at": r["start_at"],
            "end_at": r["end_at"] or "",
        }

    async def get_shift_rows(self, telegram_id: int | str | None = None, start_date: date | None = None, end_date: date | None = None) -> List[dict]:
        sql = "SELECT * FROM shifts WHERE company_id=?"
        params: list[Any] = [self._current_cid()]
        if telegram_id is not None:
            sql += " AND telegram_id=?"
            params.append(str(telegram_id).replace(".0", ""))
        if start_date:
            sql += " AND business_date>=?"
            params.append(start_date.isoformat())
        if end_date:
            sql += " AND business_date<=?"
            params.append(end_date.isoformat())
        sql += " ORDER BY business_date, start_at, id"
        rows = self._execute(sql, tuple(params), "all")
        return [self._shift_record(r) for r in rows]

    async def update_shift_cell(self, row: int, col: int, value: str):
        # Compatibility with old F/G update code.
        if int(col) == 6:
            shift = await self.get_shift_by_id(row)
            if shift:
                start_at = datetime.fromisoformat(shift["start_at"])
                end_date = start_at.date()
                try:
                    if _time_to_minutes(value) < _time_to_minutes(shift["start"]):
                        end_date = end_date + timedelta(days=1)
                    end_dt = datetime.combine(end_date, datetime.strptime(value, "%H:%M").time())
                    raw, paid, br = _legacy_paid_minutes_between(start_at.replace(tzinfo=None), end_dt)
                    self._execute("UPDATE shifts SET end_at=?, status='closed', worked_minutes=?, break_minutes=? WHERE id=?", (end_dt.isoformat(), paid, br, row))
                except Exception:
                    pass
        elif int(col) == 7:
            # Worked text is derived; ignore.
            pass
        return True

    async def delete_shift_row(self, row: int):
        self._execute("DELETE FROM shifts WHERE company_id=? AND id=?", (self._current_cid(), int(row)))
        return True

    async def get_today_live_status(self) -> dict:
        today = self._now().date()
        working_now = {}
        completed_today = {}
        today_schedule = {}
        # Open shifts from any date are considered live.
        for r in await self.get_shift_rows():
            tid = str(r["telegram_id"]).strip()
            if r.get("status") == "open" and not r.get("end"):
                working_now[tid] = r.get("shop", "")
            elif r["date"] == today and r.get("end"):
                completed_today[tid] = {"start": r.get("start", ""), "end": r.get("end", ""), "shop": r.get("shop", "")}
        for r in await self.get_schedule_rows(start_date=today, end_date=today):
            today_schedule[str(r["telegram_id"]).strip()] = {"start": r.get("start", ""), "end": r.get("end", ""), "shop": r.get("shop", "")}
        return {"working": working_now, "schedule": today_schedule, "completed": completed_today}

    def _schedule_record(self, r: sqlite3.Row) -> dict:
        d = _parse_date(r["work_date"]) or date.today()
        kind = r["kind"] or "shift"
        status = r["status_code"] or (kind if kind != "shift" else None)
        if kind != "shift":
            start = f"STATUS:{status}"
            end = STATUS_LABELS.get(status, status or "")
        else:
            start = r["start_time"] or ""
            end = r["end_time"] or ""
        return {
            "row": int(r["id"]),
            "date": d,
            "telegram_id": str(r["telegram_id"]),
            "name": r["name"] or "",
            "shop": r["shop"] or "",
            "start": start,
            "end": end,
            "status": status if kind != "shift" else None,
        }

    async def get_schedule_by_id(self, sched_id: int | str | None) -> Optional[dict]:
        if not sched_id:
            return None
        row = self._execute("SELECT * FROM schedules WHERE company_id=? AND id=?", (self._current_cid(), int(sched_id)), "one")
        return self._schedule_record(row) if row else None

    async def get_schedule_rows(self, telegram_id: int | str | None = None, start_date: date | None = None, end_date: date | None = None) -> List[dict]:
        sql = "SELECT * FROM schedules WHERE company_id=?"
        params: list[Any] = [self._current_cid()]
        if telegram_id is not None:
            sql += " AND telegram_id=?"
            params.append(str(telegram_id).replace(".0", ""))
        if start_date:
            sql += " AND work_date>=?"
            params.append(start_date.isoformat())
        if end_date:
            sql += " AND work_date<=?"
            params.append(end_date.isoformat())
        sql += " ORDER BY work_date, shop, start_time, id"
        rows = self._execute(sql, tuple(params), "all")
        return [self._schedule_record(r) for r in rows]

    async def append_schedule_rows(self, items: List[dict]) -> bool:
        try:
            cid = self._current_cid()
            with self.lock:
                for item in items:
                    d = _date_to_iso(item.get("date"))
                    if not d:
                        continue
                    tid = str(item.get("tid") or item.get("telegram_id") or "").replace(".0", "").strip()
                    name = str(item.get("name") or "").strip()
                    shop = str(item.get("shop") or "").strip()
                    kind = str(item.get("kind") or "shift")
                    status_code = str(item.get("status_code") or "")
                    start = str(item.get("start") or "")
                    end = str(item.get("end") or "")
                    if start.startswith("STATUS:"):
                        status_code = start.split(":", 1)[1]
                        kind = status_code
                        start = ""
                        end = ""
                    elif kind == "status":
                        kind = status_code or "day_off"
                        start = ""
                        end = ""
                    uid = self._ensure_user_sync(tid, name, "staff", shop, active=0 if item.get("_import") else 1)
                    sid = self._ensure_shop_sync(shop)
                    self.conn.execute(
                        """
                        INSERT INTO schedules(company_id, user_id, telegram_id, name, shop_id, shop, work_date, kind, status_code, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cid, uid, tid, name, sid, shop, d, kind, status_code, start, end),
                    )
                self.conn.commit()
            return True
        except Exception as e:
            logger.exception("append_schedule_rows xato: %s", e)
            return False

    async def update_schedule_cell(self, row: int, col: int, value: str):
        row = int(row)
        col = int(col)
        if col == 4:
            shop = str(value)
            sid = self._ensure_shop_sync(shop)
            self._execute("UPDATE schedules SET shop=?, shop_id=?, updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (shop, sid, self._current_cid(), row))
        elif col == 5:
            val = str(value)
            if val.startswith("STATUS:"):
                code = val.split(":", 1)[1]
                self._execute("UPDATE schedules SET kind=?, status_code=?, start_time='', end_time='', updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (code, code, self._current_cid(), row))
            else:
                self._execute("UPDATE schedules SET kind='shift', status_code='', start_time=?, updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (val, self._current_cid(), row))
        elif col == 6:
            self._execute("UPDATE schedules SET end_time=?, updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (str(value), self._current_cid(), row))
        return True

    async def delete_schedule_row(self, row: int):
        self._execute("DELETE FROM schedules WHERE company_id=? AND id=?", (self._current_cid(), int(row)))
        return True

    async def get_user_schedule(self, tid, date_str):
        target_date = _parse_date(date_str)
        if not target_date:
            return []
        rows = await self.get_schedule_rows(tid, target_date, target_date)
        return [{"Дата": r["date"].strftime("%d-%m-%Y"), "Магазин": r["shop"], "Время начала": r["start"], "Время конца": r["end"]} for r in rows]

    async def get_user_schedule_range(self, tid, start_d, end_d):
        rows = await self.get_schedule_rows(tid, start_d, end_d)
        return [{"Дата": r["date"].strftime("%d-%m-%Y"), "Магазин": r["shop"], "Время начала": r["start"], "Время конца": r["end"]} for r in rows]

    async def get_staff_period_summary(self, telegram_id: int | str, start_date: date, end_date: date, include_future_schedule: bool = False) -> dict:
        profile = await self.get_staff_profile(telegram_id)
        rate = float(profile["rate"]) if profile else 0.0
        shifts = await self.get_shift_rows(telegram_id, start_date, end_date)
        worked_days = set()
        total_hours = 0.0
        earnings = 0.0
        longest_shift = 0.0
        busiest_shop: dict[str, float] = {}
        live_minutes = 0
        today = self._now().date()
        now = self._now()

        for row in shifts:
            worked_days.add(row["date"])
            if row.get("status") == "open" and not row.get("end"):
                if start_date <= today <= end_date:
                    start_at = datetime.fromisoformat(row["start_at"])
                    if start_at.tzinfo is None and now.tzinfo:
                        start_at = config.get_timezone_obj().localize(start_at) if hasattr(config.get_timezone_obj(), "localize") else start_at.replace(tzinfo=now.tzinfo)
                    live_minutes = max(live_minutes, int((now - start_at).total_seconds() // 60))
                hours = 0.0
            else:
                hours = _hours_from_worked(row.get("worked", ""), row.get("start", ""), row.get("end", ""))
            total_hours += hours
            earnings += hours * rate
            longest_shift = max(longest_shift, hours)
            if row.get("shop") and hours:
                busiest_shop[row["shop"]] = busiest_shop.get(row["shop"], 0.0) + hours

        projected_hours = total_hours
        projected_earnings = earnings
        if include_future_schedule and end_date >= today:
            sched = await self.get_schedule_rows(telegram_id, max(start_date, today), end_date)
            existing_dates = {row["date"] for row in shifts if row.get("end") or row["date"] < today}
            for row in sched:
                if row.get("status"):
                    continue
                if row["date"] in existing_dates and row["date"] < today:
                    continue
                hours = _hours_between(row.get("start", ""), row.get("end", ""))
                projected_hours += hours
                projected_earnings += hours * rate

        return {
            "profile": profile or {"name": "—", "emoji": "🙂"},
            "start_date": start_date,
            "end_date": end_date,
            "days_worked": len(worked_days),
            "shifts": len(shifts),
            "hours": round(total_hours, 2),
            "earnings": _money(earnings),
            "rate": rate,
            "avg_shift_hours": round(total_hours / len([s for s in shifts if s.get("end")]) , 2) if [s for s in shifts if s.get("end")] else 0.0,
            "longest_shift_hours": round(longest_shift, 2),
            "busiest_shop": max(busiest_shop, key=busiest_shop.get) if busiest_shop else "—",
            "busiest_shop_hours": round(busiest_shop[max(busiest_shop, key=busiest_shop.get)], 2) if busiest_shop else 0.0,
            "projected_hours": round(projected_hours, 2),
            "projected_earnings": _money(projected_earnings),
            "live_earning": _money((live_minutes / 60) * rate),
            "live_minutes": live_minutes,
        }

    async def get_monthly_breakdown(self, telegram_id: int | str, months: int = 6) -> List[dict]:
        now = self._now().date()
        out = []
        year, month = now.year, now.month
        for _ in range(months):
            start_d = date(year, month, 1)
            end_d = date(year, month, calendar.monthrange(year, month)[1])
            summary = await self.get_staff_period_summary(telegram_id, start_d, end_d)
            out.append({
                "key": f"{year:04d}-{month:02d}",
                "label": f"{calendar.month_name[month]} {year}",
                "hours": summary["hours"],
                "earnings": summary["earnings"],
                "shifts": summary["shifts"],
                "days_worked": summary["days_worked"],
            })
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        return out

    async def get_current_live_earning(self, telegram_id: int | str) -> dict:
        profile = await self.get_staff_profile(telegram_id)
        rate = float(profile["rate"]) if profile else 0.0
        shift = await self.get_active_shift(int(str(telegram_id)))
        if not shift:
            return {"active": False}
        now = self._now()
        start_at = datetime.fromisoformat(shift["start_at"])
        if start_at.tzinfo is None and now.tzinfo:
            start_at = config.get_timezone_obj().localize(start_at) if hasattr(config.get_timezone_obj(), "localize") else start_at.replace(tzinfo=now.tzinfo)
        minutes = max(0, int((now - start_at).total_seconds() // 60))
        paid_live, break_m = _legacy_paid_minutes_from_total(minutes)
        earned = (paid_live / 60) * rate
        projected = earned
        sched = await self.get_schedule_rows(telegram_id, shift["date"], shift["date"])
        for s in sched:
            if s.get("status") or not s.get("end"):
                continue
            try:
                planned_minutes = _time_to_minutes(s["end"]) - _time_to_minutes(s["start"])
                paid_plan, planned_break = _legacy_paid_minutes_from_total(planned_minutes)
                projected = max(earned, (paid_plan / 60) * rate)
            except Exception:
                pass
            break
        return {"active": True, "start": shift.get("start"), "shop": shift.get("shop"), "earned": _money(earned), "projected": _money(projected), "minutes": minutes}

    async def append_audit_log(self, actor_tid: str | int, actor_role: str, action: str, payload: Dict[str, Any]):
        try:
            self._execute(
                "INSERT INTO audit_log(company_id, actor_tid, actor_role, action, payload) VALUES (?, ?, ?, ?, ?)",
                (self._current_cid(), str(actor_tid), str(actor_role), str(action), json.dumps(payload or {}, ensure_ascii=False)),
            )
            return True
        except Exception as e:
            logger.error("append_audit_log xato: %s", e)
            return False

    async def get_user_shifts_history(self, tid, days):
        start_date = self._now().date() - timedelta(days=days)
        rows = await self.get_shift_rows(tid, start_date, None)
        return [{"Дата": r["date"].strftime("%d-%m-%Y"), "Магазин": r["shop"], "Время начала": r["start"], "Время конца": r["end"], "Отработано": r["worked"]} for r in rows]

    # -------------------------
    # Migration helpers
    # -------------------------
    async def import_staff_records(self, records: List[dict]) -> int:
        count = 0
        for r in records:
            tid = str(r.get("TelegramID") or r.get("telegram_id") or "").replace(".0", "").strip()
            if not tid:
                continue
            name = r.get("Имя") or r.get("Name") or r.get("name") or "Xodim"
            role = str(r.get("Роль") or r.get("role") or "staff").lower()
            shop = r.get("Магазин") or r.get("shop") or ""
            await self.add_new_staff(tid, name, role, shop)
            if r.get("Username") not in [None, ""]:
                await self.update_staff_field(tid, "Username", str(r.get("Username")))
            if r.get("Phone") not in [None, ""]:
                await self.update_staff_field(tid, "Phone", str(r.get("Phone")))
            if r.get("Ставка") not in [None, ""]:
                await self.update_staff_field(tid, "Ставка", str(r.get("Ставка")))
            if r.get("Смайлик"):
                await self.update_staff_field(tid, "Смайлик", str(r.get("Смайлик")))
            active_raw = str(r.get("Активен", "TRUE")).strip().upper()
            if active_raw not in {"TRUE", "1", "YES", "ДА", ""}:
                await self.update_staff_field(tid, "Активен", "FALSE")
            count += 1
        return count

    async def import_shops_records(self, records: List[dict]) -> int:
        count = 0
        for r in records:
            name = r.get("name") or r.get("Магазин") or r.get("shop") or ""
            lat = r.get("lat")
            lon = r.get("lon")
            try:
                lat = float(str(lat).replace(",", ".")) if lat not in [None, ""] else None
                lon = float(str(lon).replace(",", ".")) if lon not in [None, ""] else None
            except Exception:
                lat, lon = None, None
            if self._ensure_shop_sync(name, lat, lon):
                count += 1
        return count

    async def import_schedule_rows(self, rows: List[dict]) -> int:
        items = []
        for r in rows:
            start = r.get("start", "")
            status = r.get("status") or _status_from_schedule(start)
            if status:
                item = {"date": r["date"].strftime("%d-%m-%Y") if isinstance(r.get("date"), date) else r.get("date"), "tid": r.get("telegram_id"), "name": r.get("name"), "shop": r.get("shop"), "kind": "status", "status_code": status, "start": f"STATUS:{status}", "end": STATUS_LABELS.get(status, status), "_import": True}
            else:
                item = {"date": r["date"].strftime("%d-%m-%Y") if isinstance(r.get("date"), date) else r.get("date"), "tid": r.get("telegram_id"), "name": r.get("name"), "shop": r.get("shop"), "kind": "shift", "start": r.get("start", ""), "end": r.get("end", ""), "_import": True}
            items.append(item)
        ok = await self.append_schedule_rows(items)
        return len(items) if ok else 0

    async def import_shift_rows(self, rows: List[dict]) -> int:
        cid = self._current_cid()
        count = 0
        with self.lock:
            for r in rows:
                d = r.get("date") if isinstance(r.get("date"), date) else _parse_date(r.get("date"))
                if not d:
                    continue
                tid = str(r.get("telegram_id", "")).replace(".0", "").strip()
                name = r.get("name") or "Xodim"
                shop = r.get("shop") or ""
                existing_user = self.conn.execute("SELECT id FROM users WHERE company_id=? AND telegram_id=?", (cid, tid)).fetchone()
                uid = self._ensure_user_sync(tid, name, "staff", shop, active=1 if existing_user else 0)
                sid = self._ensure_shop_sync(shop)
                start_s = r.get("start") or "00:00"
                end_s = r.get("end") or ""
                try:
                    start_dt = datetime.combine(d, datetime.strptime(start_s, "%H:%M").time())
                except Exception:
                    continue
                end_dt = None
                status = "open"
                worked_minutes = 0
                break_minutes = 0
                if end_s:
                    try:
                        end_date = d + timedelta(days=1) if _time_to_minutes(end_s) < _time_to_minutes(start_s) else d
                        end_dt = datetime.combine(end_date, datetime.strptime(end_s, "%H:%M").time())
                        status = "closed"
                        if str(r.get("worked", "")).strip():
                            worked_minutes = int(_hours_from_worked(r.get("worked", ""), start_s, end_s) * 60)
                            # Imported Google Sheets already stores old rounded text. Detect lunch only approximately.
                            raw_minutes, _paid, break_minutes = _legacy_paid_minutes_from_times(start_s, end_s)
                        else:
                            raw_minutes, worked_minutes, break_minutes = _legacy_paid_minutes_from_times(start_s, end_s)
                    except Exception:
                        end_dt = None
                self.conn.execute(
                    """
                    INSERT INTO shifts(company_id, user_id, telegram_id, name, shop_id, shop, business_date, start_at, end_at, status, start_photo_id, start_location, worked_minutes, break_minutes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, uid, tid, name, sid, shop, d.isoformat(), start_dt.isoformat(), end_dt.isoformat() if end_dt else None, status, r.get("photo_id", ""), r.get("location", ""), worked_minutes, break_minutes),
                )
                count += 1
            self.conn.commit()
        return count


db = AsyncSQLiteDB.get_instance()
