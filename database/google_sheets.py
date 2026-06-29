import json
import logging
import calendar
import time
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any

import gspread_asyncio
from google.oauth2.service_account import Credentials

from config import config
from utils.ctx import sheet_id_ctx

logger = logging.getLogger(__name__)


def get_creds():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if config.google_creds_json:
        try:
            creds_dict = json.loads(config.google_creds_json)
            return Credentials.from_service_account_info(creds_dict).with_scopes(scopes)
        except Exception:
            pass
    return Credentials.from_service_account_file(config.google_creds_path).with_scopes(scopes)


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").strip().lower() if ch.isalnum())


def _money(v: float) -> float:
    return round(float(v or 0), 2)


class AsyncGoogleSheets:
    _instance = None

    def __init__(self):
        self.agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)
        self._staff_cache = {}
        self._staff_cache_time = {}
        self.CACHE_TTL = 5

        self._spreadsheet_cache = {}
        self._worksheet_cache = {}
        self._values_cache = {}
        self._audit_ready = {}
        self._sheet_obj_ttl = 300
        self._values_ttl = {
            "Сотрудники": 60,
            "Магазины": 300,
            "Смены": 20,
            "График": 20,
            "AuditLog": 30,
        }
        self._slow_threshold = 2.0

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _current_sid(self) -> str:
        return sheet_id_ctx.get() or config.google_sheet_id

    def _sheet_key(self, title: str) -> tuple[str, str]:
        return self._current_sid(), title

    def _log_slow(self, name: str, started_at: float, extra: str = ""):
        elapsed = time.perf_counter() - started_at
        if elapsed >= self._slow_threshold:
            suffix = f" | {extra}" if extra else ""
            logger.warning("SLOW %s: %.2fs%s", name, elapsed, suffix)

    def _invalidate_staff_cache(self):
        sid = self._current_sid()
        self._staff_cache.pop(sid, None)
        self._staff_cache_time.pop(sid, None)

    def invalidate_sheet_cache(self, *titles: str):
        sid = self._current_sid()
        if not titles:
            keys = [k for k in self._values_cache.keys() if k[0] == sid]
        else:
            keys = [(sid, t) for t in titles]
        for key in keys:
            self._values_cache.pop(key, None)
        if not titles or "Сотрудники" in titles:
            self._invalidate_staff_cache()
        if not titles or "AuditLog" in titles:
            self._audit_ready.pop(sid, None)

    async def _get_spreadsheet(self):
        sid = self._current_sid()
        cached = self._spreadsheet_cache.get(sid)
        now = time.time()
        if cached and now - cached[1] < self._sheet_obj_ttl:
            return cached[0]

        started = time.perf_counter()
        agc = await self.agcm.authorize()
        ss = await agc.open_by_key(sid)
        self._spreadsheet_cache[sid] = (ss, now)
        self._log_slow("open_spreadsheet", started, sid)
        return ss

    async def _get_worksheet(self, title: str):
        key = self._sheet_key(title)
        cached = self._worksheet_cache.get(key)
        now = time.time()
        if cached and now - cached[1] < self._sheet_obj_ttl:
            return cached[0]

        started = time.perf_counter()
        ss = await self._get_spreadsheet()
        ws = await ss.worksheet(title)
        self._worksheet_cache[key] = (ws, now)
        self._log_slow("get_worksheet", started, title)
        return ws

    async def get_or_create_worksheet(self, title: str, rows: int = 1000, cols: int = 20):
        ss = await self._get_spreadsheet()
        try:
            ws = await ss.worksheet(title)
        except Exception:
            logger.info("Worksheet '%s' topilmadi, yangisi yaratilmoqda", title)
            ws = await ss.add_worksheet(title=title, rows=rows, cols=cols)
        self._worksheet_cache[self._sheet_key(title)] = (ws, time.time())
        return ws

    async def _get_values_cached(self, title: str, ttl: int | None = None, force_refresh: bool = False) -> list[list[str]]:
        key = self._sheet_key(title)
        ttl = self._values_ttl.get(title, 20) if ttl is None else ttl
        cached = self._values_cache.get(key)
        now = time.time()
        if not force_refresh and cached and now - cached[1] < ttl:
            return cached[0]

        started = time.perf_counter()
        try:
            ws = await self._get_worksheet(title)
            values = await ws.get_all_values()
            self._values_cache[key] = (values, now)
            self._log_slow("get_all_values", started, f"{title} rows={len(values)}")
            return values
        except Exception:
            if cached:
                return cached[0]
            raise

    def _rows_to_records(self, values: list[list[str]]) -> list[dict]:
        if not values:
            return []
        headers = values[0]
        records = []
        width = len(headers)
        for row in values[1:]:
            padded = (row + [""] * width)[:width]
            records.append({headers[i]: padded[i] for i in range(width)})
        return records

    def _is_same_date(self, date_str: str, target_date: date) -> bool:
        parsed = self._parse_date(date_str)
        return bool(parsed and parsed == target_date)

    def _parse_date(self, value: str | Any) -> Optional[date]:
        s = str(value or "").strip().replace("/", ".").replace("-", ".")
        for fmt in ["%d.%m.%Y", "%d.%m.%y", "%Y.%m.%d"]:
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

    def _time_to_minutes(self, time_str: str) -> int:
        h, m = map(int, str(time_str).strip().split(":"))
        total = h * 60 + m
        if h < 8:
            total += 24 * 60
        return total

    def _hours_between(self, start: str, end: str) -> float:
        try:
            mins = self._time_to_minutes(end) - self._time_to_minutes(start)
            return max(0.0, mins / 60)
        except Exception:
            return 0.0

    def _hours_from_worked(self, worked: str, start: str = "", end: str = "") -> float:
        s = str(worked or "").strip().lower()
        if s:
            try:
                h = 0
                m = 0
                if "ч" in s:
                    h = int(s.split("ч")[0].strip())
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
        return self._hours_between(start, end)

    def _month_bounds(self, year: int, month: int) -> tuple[date, date]:
        last = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last)

    def _shift_status_from_schedule(self, start_value: str) -> Optional[str]:
        raw = str(start_value or "").strip()
        if raw.startswith("STATUS:"):
            return raw.split(":", 1)[1].strip()
        return None

    async def get_all_staff(self, force_refresh: bool = False, strict: bool = False) -> List[Dict]:
        now = datetime.now()
        sid = self._current_sid()

        if not force_refresh and sid in self._staff_cache and sid in self._staff_cache_time:
            if (now - self._staff_cache_time[sid]) < timedelta(minutes=self.CACHE_TTL):
                return self._staff_cache[sid]

        try:
            values = await self._get_values_cached("Сотрудники", ttl=60, force_refresh=force_refresh)
            records = self._rows_to_records(values)
            active_staff = [
                r for r in records if str(r.get("Активен", "TRUE")).strip().upper() == "TRUE"
            ]
            self._staff_cache[sid] = active_staff
            self._staff_cache_time[sid] = now
            return active_staff
        except Exception as e:
            logger.error("Xodimlarni olishda xato (%s): %s", sid, e)
            old_cache = self._staff_cache.get(sid)
            if old_cache:
                return old_cache
            if strict:
                raise
            return []

    async def _get_staff_headers_and_rows(self):
        ws = await self._get_worksheet("Сотрудники")
        values = await self._get_values_cached("Сотрудники", ttl=60)
        headers = values[0] if values else []
        rows = values[1:] if len(values) > 1 else []
        return ws, headers, rows

    def _find_header_idx(self, headers: list[str], variants: list[str]) -> Optional[int]:
        target = {_norm(v) for v in variants}
        for i, h in enumerate(headers, start=1):
            if _norm(h) in target:
                return i
        return None

    async def ensure_staff_columns(self):
        try:
            ws, headers, _ = await self._get_staff_headers_and_rows()
            needed = ["Ставка", "Смайлик"]
            existing = {_norm(h) for h in headers}
            next_col = len(headers) + 1
            added_any = False
            for header in needed:
                if _norm(header) not in existing:
                    await ws.update_cell(1, next_col, header)
                    next_col += 1
                    added_any = True
            if added_any:
                self.invalidate_sheet_cache("Сотрудники")
        except Exception as e:
            logger.error("ensure_staff_columns xato: %s", e)

    async def get_user_by_telegram_id(self, telegram_id: int, strict: bool = False) -> Optional[Dict]:
        staff_list = await self.get_all_staff(strict=strict)
        target = str(telegram_id)
        for user in staff_list:
            try:
                row_id = str(user.get("TelegramID", 0)).replace(".0", "")
                if row_id == target:
                    return user
            except Exception:
                continue
        return None

    async def get_staff_row_meta(self, telegram_id: int | str) -> Optional[dict]:
        await self.ensure_staff_columns()
        ws, headers, rows = await self._get_staff_headers_and_rows()
        tid_idx = self._find_header_idx(headers, ["TelegramID", "telegram_id", "telegram id", "id"])
        if not tid_idx:
            return None
        target = str(telegram_id)
        for offset, row in enumerate(rows, start=2):
            value = str((row[tid_idx - 1] if len(row) >= tid_idx else "")).replace(".0", "").strip()
            if value == target:
                return {"ws": ws, "headers": headers, "row_index": offset, "row": row}
        return None

    async def get_staff_profile(self, telegram_id: int | str) -> Optional[dict]:
        user = await self.get_user_by_telegram_id(int(telegram_id))
        if not user:
            return None
        await self.ensure_staff_columns()
        meta = await self.get_staff_row_meta(telegram_id)
        headers = meta["headers"] if meta else []
        row = meta["row"] if meta else []
        rate_idx = self._find_header_idx(headers, ["Ставка", "rate", "hourly_rate"])
        emoji_idx = self._find_header_idx(headers, ["Смайлик", "emoji", "smile"])
        rate_raw = row[rate_idx - 1] if meta and rate_idx and len(row) >= rate_idx else user.get("Ставка", 0)
        emoji = row[emoji_idx - 1] if meta and emoji_idx and len(row) >= emoji_idx else user.get("Смайлик", "🙂")
        try:
            rate = float(str(rate_raw).replace(" ", "").replace(",", ".")) if str(rate_raw).strip() else 0.0
        except Exception:
            rate = 0.0
        shops = [x.strip() for x in str(user.get("Магазин", "")).split(",") if x.strip()]
        return {
            "telegram_id": str(user.get("TelegramID", "")).replace(".0", ""),
            "name": user.get("Имя", "Xodim"),
            "role": str(user.get("Роль", "staff")).lower(),
            "shop": user.get("Магазин", ""),
            "shops": shops,
            "active": str(user.get("Активен", "TRUE")).strip().upper() == "TRUE",
            "rate": rate,
            "emoji": emoji or "🙂",
        }

    async def update_staff_field(self, telegram_id: int | str, field_name: str, value: str) -> bool:
        try:
            await self.ensure_staff_columns()
            meta = await self.get_staff_row_meta(telegram_id)
            if not meta:
                return False
            headers = meta["headers"]
            ws = meta["ws"]
            row_index = meta["row_index"]
            idx = self._find_header_idx(headers, [field_name])
            if not idx:
                idx = len(headers) + 1
                await ws.update_cell(1, idx, field_name)
            await ws.update_cell(row_index, idx, str(value))
            self.invalidate_sheet_cache("Сотрудники")
            return True
        except Exception as e:
            logger.error("update_staff_field xato: %s", e)
            return False

    async def search_staff(self, query: str = "", limit: int = 100) -> List[dict]:
        staff = await self.get_all_staff(force_refresh=False)
        q = str(query or "").strip().lower()
        res = []
        for item in staff:
            tid = str(item.get("TelegramID", "")).replace(".0", "")
            name = str(item.get("Имя", ""))
            shop = str(item.get("Магазин", ""))
            role = str(item.get("Роль", "staff"))
            text = f"{tid} {name} {shop} {role}".lower()
            if not q or q in text:
                res.append(item)
            if len(res) >= limit:
                break
        return res

    async def get_shops(self) -> List[str]:
        shops = await self.get_shops_with_coords()
        return [s["name"] for s in shops]

    async def get_shops_with_coords(self) -> List[Dict]:
        try:
            values = await self._get_values_cached("Магазины", ttl=300)
            shops = []
            for row in values[1:]:
                if len(row) >= 1 and row[0].strip():
                    shop = {"name": row[0].strip(), "lat": None, "lon": None}
                    if len(row) >= 3:
                        try:
                            shop["lat"] = float(row[1].replace(",", "."))
                            shop["lon"] = float(row[2].replace(",", "."))
                        except Exception:
                            pass
                    shops.append(shop)
            return shops
        except Exception:
            return []

    async def get_active_shift_row(self, telegram_id: int) -> Optional[int]:
        try:
            today = datetime.now(config.get_timezone_obj()).date()
            rows = await self.get_shift_rows(telegram_id, today, today)
            for row in reversed(rows):
                if not row.get("end"):
                    return row["row"]
            return None
        except Exception:
            return None

    async def start_shift(self, user_data: Dict, photo_id: str, location: str = "") -> bool:
        try:
            ws = await self._get_worksheet("Смены")
            now = datetime.now(config.get_timezone_obj())
            row = [
                now.strftime("%d-%m-%Y"),
                str(user_data.get("TelegramID")),
                user_data.get("Имя"),
                user_data.get("Магазин"),
                now.strftime("%H:%M"),
                "",
                "",
                photo_id,
                location,
            ]
            await ws.append_row(row)
            self.invalidate_sheet_cache("Смены")
            return True
        except Exception:
            return False

    async def end_shift(self, row_index: int, start_time_str: str) -> str:
        try:
            ws = await self._get_worksheet("Смены")
            now = datetime.now(config.get_timezone_obj())
            end_time = now.strftime("%H:%M")
            try:
                s_dt = datetime.strptime(start_time_str, "%H:%M")
                e_dt = datetime.strptime(end_time, "%H:%M")
                if e_dt < s_dt:
                    e_dt += timedelta(days=1)
                diff = e_dt - s_dt
                h = int(diff.total_seconds() // 3600)
                m = int((diff.total_seconds() % 3600) // 60)
                if m >= 30:
                    h += 1
                if h >= 5:
                    h -= 1
                worked = f"{h} ч {0:02d} м"
            except Exception:
                worked = "0 ч 00 м"
            await ws.batch_update(
                [
                    {"range": f"F{row_index}", "values": [[end_time]]},
                    {"range": f"G{row_index}", "values": [[worked]]},
                ]
            )
            self.invalidate_sheet_cache("Смены")
            return worked
        except Exception:
            return "Error"

    async def get_today_live_status(self) -> dict:
        today = datetime.now(config.get_timezone_obj()).date()
        working_now = {}
        completed_today = {}
        today_schedule = {}

        for r in await self.get_shift_rows(start_date=today, end_date=today):
            tid = str(r["telegram_id"]).strip()
            shop_fact = str(r.get("shop", "")).strip()
            if not r.get("end"):
                working_now[tid] = shop_fact
            else:
                completed_today[tid] = {"start": r.get("start", ""), "end": r.get("end", ""), "shop": shop_fact}

        for r in await self.get_schedule_rows(start_date=today, end_date=today):
            today_schedule[str(r["telegram_id"]).strip()] = {"start": r.get("start", ""), "end": r.get("end", ""), "shop": r.get("shop", "")}

        return {"working": working_now, "schedule": today_schedule, "completed": completed_today}

    async def get_shift_rows(self, telegram_id: int | str | None = None, start_date: date | None = None, end_date: date | None = None) -> List[dict]:
        started = time.perf_counter()
        try:
            rows = await self._get_values_cached("Смены", ttl=20)
            result = []
            target_tid = str(telegram_id) if telegram_id is not None else None
            for idx, r in enumerate(rows[1:], start=2):
                r = (r + [""] * 9)[:9]
                d = self._parse_date(r[0])
                if not d:
                    continue
                tid = str(r[1]).replace(".0", "").strip()
                if target_tid is not None and tid != target_tid:
                    continue
                if start_date and d < start_date:
                    continue
                if end_date and d > end_date:
                    continue
                result.append(
                    {
                        "row": idx,
                        "date": d,
                        "telegram_id": tid,
                        "name": r[2].strip(),
                        "shop": r[3].strip(),
                        "start": r[4].strip(),
                        "end": r[5].strip(),
                        "worked": r[6].strip(),
                        "photo_id": r[7].strip(),
                        "location": r[8].strip(),
                    }
                )
            self._log_slow("get_shift_rows", started, f"result={len(result)}")
            return result
        except Exception as e:
            logger.error("get_shift_rows xato: %s", e)
            return []

    async def get_schedule_rows(self, telegram_id: int | str | None = None, start_date: date | None = None, end_date: date | None = None) -> List[dict]:
        started = time.perf_counter()
        try:
            rows = await self._get_values_cached("График", ttl=20)
            result = []
            target_tid = str(telegram_id) if telegram_id is not None else None
            for idx, r in enumerate(rows[1:], start=2):
                r = (r + ["", "", "", "", "", ""])[:6]
                d = self._parse_date(r[0])
                if not d:
                    continue
                tid = str(r[2]).replace(".0", "").strip()
                if target_tid is not None and tid != target_tid:
                    continue
                if start_date and d < start_date:
                    continue
                if end_date and d > end_date:
                    continue
                status = self._shift_status_from_schedule(r[4])
                result.append(
                    {
                        "row": idx,
                        "date": d,
                        "telegram_id": tid,
                        "name": r[1].strip(),
                        "shop": r[3].strip(),
                        "start": r[4].strip(),
                        "end": r[5].strip(),
                        "status": status,
                    }
                )
            self._log_slow("get_schedule_rows", started, f"result={len(result)}")
            return result
        except Exception as e:
            logger.error("get_schedule_rows xato: %s", e)
            return []

    async def get_user_schedule(self, tid, date_str):
        try:
            target_date = self._parse_date(date_str)
            if not target_date:
                return []
            rows = await self.get_schedule_rows(tid, target_date, target_date)
            return [
                {
                    "Дата": r["date"].strftime("%d-%m-%Y"),
                    "Магазин": r["shop"],
                    "Время начала": r["start"],
                    "Время конца": r["end"],
                }
                for r in rows
            ]
        except Exception:
            return []

    async def get_user_schedule_range(self, tid, start_d, end_d):
        try:
            rows = await self.get_schedule_rows(tid, start_d, end_d)
            res = [
                {
                    "Дата": r["date"].strftime("%d-%m-%Y"),
                    "Магазин": r["shop"],
                    "Время начала": r["start"],
                    "Время конца": r["end"],
                }
                for r in rows
            ]
            res.sort(key=lambda x: datetime.strptime(x["Дата"], "%d-%m-%Y"))
            return res
        except Exception as e:
            logger.error("get_user_schedule_range xato: %s", e)
            return []

    async def get_staff_period_summary(self, telegram_id: int | str, start_date: date, end_date: date, include_future_schedule: bool = False) -> dict:
        started = time.perf_counter()
        profile = await self.get_staff_profile(telegram_id)
        rate = float(profile["rate"]) if profile else 0.0
        shifts = await self.get_shift_rows(telegram_id, start_date, end_date)
        worked_days = set()
        total_hours = 0.0
        earnings = 0.0
        longest_shift = 0.0
        busiest_shop = {}
        live_minutes = 0

        for row in shifts:
            worked_days.add(row["date"])
            hours = self._hours_from_worked(row.get("worked", ""), row.get("start", ""), row.get("end", ""))
            total_hours += hours
            earnings += hours * rate
            longest_shift = max(longest_shift, hours)
            if row.get("shop"):
                busiest_shop[row["shop"]] = busiest_shop.get(row["shop"], 0.0) + hours

        today = datetime.now(config.get_timezone_obj()).date()
        if start_date <= today <= end_date:
            for row in reversed(shifts):
                if row["date"] == today and not row.get("end"):
                    try:
                        live_minutes = max(0, self._time_to_minutes(datetime.now(config.get_timezone_obj()).strftime("%H:%M")) - self._time_to_minutes(row.get("start", "")))
                    except Exception:
                        live_minutes = 0
                    break

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
                hours = self._hours_between(row.get("start", ""), row.get("end", ""))
                projected_hours += hours
                projected_earnings += hours * rate

        self._log_slow("get_staff_period_summary", started, f"tid={telegram_id} shifts={len(shifts)}")
        return {
            "profile": profile,
            "start_date": start_date,
            "end_date": end_date,
            "days_worked": len(worked_days),
            "shifts": len(shifts),
            "hours": round(total_hours, 2),
            "earnings": _money(earnings),
            "rate": rate,
            "avg_shift_hours": round(total_hours / len(shifts), 2) if shifts else 0.0,
            "longest_shift_hours": round(longest_shift, 2),
            "busiest_shop": max(busiest_shop, key=busiest_shop.get) if busiest_shop else "—",
            "busiest_shop_hours": round(busiest_shop[max(busiest_shop, key=busiest_shop.get)], 2) if busiest_shop else 0.0,
            "projected_hours": round(projected_hours, 2),
            "projected_earnings": _money(projected_earnings),
            "live_earning": _money((live_minutes / 60) * rate),
            "live_minutes": live_minutes,
        }

    async def get_monthly_breakdown(self, telegram_id: int | str, months: int = 6) -> List[dict]:
        started = time.perf_counter()
        now = datetime.now(config.get_timezone_obj()).date()
        breakdown = []
        year, month = now.year, now.month
        month_defs = []
        min_start = None
        max_end = None
        for _ in range(months):
            start_d, end_d = self._month_bounds(year, month)
            month_defs.append((year, month, start_d, end_d))
            min_start = start_d if min_start is None else min(min_start, start_d)
            max_end = end_d if max_end is None else max(max_end, end_d)
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        shifts = await self.get_shift_rows(telegram_id, min_start, max_end)
        buckets = {
            f"{y:04d}-{m:02d}": {"hours": 0.0, "earnings": 0.0, "shifts": 0, "days": set()}
            for y, m, _, _ in month_defs
        }
        profile = await self.get_staff_profile(telegram_id)
        rate = float(profile["rate"]) if profile else 0.0

        for row in shifts:
            key = f"{row['date'].year:04d}-{row['date'].month:02d}"
            if key not in buckets:
                continue
            hours = self._hours_from_worked(row.get("worked", ""), row.get("start", ""), row.get("end", ""))
            buckets[key]["hours"] += hours
            buckets[key]["earnings"] += hours * rate
            buckets[key]["shifts"] += 1
            buckets[key]["days"].add(row["date"])

        for y, m, _, _ in month_defs:
            key = f"{y:04d}-{m:02d}"
            bucket = buckets[key]
            breakdown.append(
                {
                    "key": key,
                    "label": f"{calendar.month_name[m]} {y}",
                    "hours": round(bucket["hours"], 2),
                    "earnings": _money(bucket["earnings"]),
                    "shifts": bucket["shifts"],
                    "days_worked": len(bucket["days"]),
                }
            )

        self._log_slow("get_monthly_breakdown", started, f"tid={telegram_id} months={months}")
        return breakdown

    async def get_current_live_earning(self, telegram_id: int | str) -> dict:
        profile = await self.get_staff_profile(telegram_id)
        rate = float(profile["rate"]) if profile else 0.0
        today = datetime.now(config.get_timezone_obj())
        shifts = await self.get_shift_rows(telegram_id, today.date(), today.date())
        active = None
        for row in reversed(shifts):
            if not row.get("end"):
                active = row
                break
        if not active:
            return {"active": False, "earned": 0.0, "projected": 0.0, "minutes": 0, "start": None, "end": None, "shop": None}
        try:
            start_time = active.get("start", "")
            minutes = max(0, self._time_to_minutes(today.strftime("%H:%M")) - self._time_to_minutes(start_time))
            sched_rows = await self.get_schedule_rows(telegram_id, today.date(), today.date())
            sched_end = None
            for row in sched_rows:
                raw_end = row.get("end", "")
                if raw_end and not str(row.get("start", "")).startswith("STATUS:"):
                    sched_end = raw_end
                    break
            projected = 0.0
            if sched_end:
                projected = self._hours_between(start_time, sched_end) * rate
            return {
                "active": True,
                "earned": _money((minutes / 60) * rate),
                "projected": _money(projected),
                "minutes": minutes,
                "start": start_time,
                "end": sched_end,
                "shop": active.get("shop"),
            }
        except Exception as e:
            logger.error("get_current_live_earning xato: %s", e)
            return {"active": False, "earned": 0.0, "projected": 0.0, "minutes": 0, "start": None, "end": None, "shop": None}

    async def append_audit_log(self, actor_tid: str | int, actor_role: str, action: str, payload: Dict[str, Any]):
        try:
            sid = self._current_sid()
            ws = await self.get_or_create_worksheet("AuditLog", rows=2000, cols=10)
            if not self._audit_ready.get(sid):
                rows = await self._get_values_cached("AuditLog", ttl=30, force_refresh=True)
                if not rows:
                    await ws.append_row(["Timestamp", "ActorTelegramID", "ActorRole", "Action", "PayloadJSON"])
                self._audit_ready[sid] = True
            await ws.append_row(
                [
                    datetime.now(config.get_timezone_obj()).strftime("%d-%m-%Y %H:%M:%S"),
                    str(actor_tid),
                    str(actor_role),
                    str(action),
                    json.dumps(payload, ensure_ascii=False),
                ]
            )
            self.invalidate_sheet_cache("AuditLog")
        except Exception as e:
            logger.error("Audit log yozishda xato: %s", e)

    async def append_schedule_rows(self, items: List[dict]) -> bool:
        if not items:
            return True
        try:
            ws = await self._get_worksheet("График")
            rows = []
            for item in items:
                start = str(item.get("start", ""))
                if start.startswith("STATUS:") or item.get("kind") == "status":
                    code = item.get("status_code") or start.split(":", 1)[-1]
                    rows.append(
                        [
                            item["date"],
                            item["name"],
                            str(item["tid"]),
                            item["shop"],
                            f"STATUS:{code}",
                            item.get("end") or code,
                        ]
                    )
                else:
                    rows.append([item["date"], item["name"], str(item["tid"]), item["shop"], item["start"], item["end"]])
            try:
                await ws.append_rows(rows)
            except Exception:
                for row in rows:
                    await ws.append_row(row)
            self.invalidate_sheet_cache("График")
            return True
        except Exception as e:
            logger.error("append_schedule_rows xato: %s", e)
            return False

    async def add_new_staff(self, tid, name, role, shop):
        try:
            await self.ensure_staff_columns()
            ws, headers, _ = await self._get_staff_headers_and_rows()
            vals = [""] * len(headers)
            mapping = {
                "telegramid": str(tid),
                "имя": name,
                "роль": role,
                "магазин": shop,
                "активен": "TRUE",
                "ставка": "0",
                "смайлик": "🙂",
            }
            for i, h in enumerate(headers):
                key = _norm(h)
                for mk, mv in mapping.items():
                    if key == _norm(mk):
                        vals[i] = mv
            if not any(vals):
                vals = [str(tid), "", "", name, role, shop, "TRUE", "0", "🙂"]
            await ws.append_row(vals)
            self.invalidate_sheet_cache("Сотрудники")
            return True
        except Exception:
            return False

    async def deactivate_staff(self, tid):
        try:
            meta = await self.get_staff_row_meta(tid)
            if not meta:
                return False
            idx = self._find_header_idx(meta["headers"], ["Активен", "active"])
            if not idx:
                idx = len(meta["headers"]) + 1
                await meta["ws"].update_cell(1, idx, "Активен")
            await meta["ws"].update_cell(meta["row_index"], idx, "FALSE")
            self.invalidate_sheet_cache("Сотрудники")
            return True
        except Exception:
            return False

    async def get_user_shifts_history(self, tid, days):
        try:
            start_date = datetime.now(config.get_timezone_obj()).date() - timedelta(days=days)
            rows = await self.get_shift_rows(tid, start_date, None)
            out = []
            for r in rows:
                out.append(
                    {
                        "Дата": r["date"].strftime("%d-%m-%Y"),
                        "Магазин": r["shop"],
                        "Время начала": r["start"],
                        "Время конца": r["end"],
                        "Отработано": r["worked"],
                    }
                )
            return out
        except Exception:
            return []


db = AsyncGoogleSheets.get_instance()
