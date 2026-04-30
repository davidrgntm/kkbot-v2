from __future__ import annotations

import calendar
from datetime import date
from typing import Iterable

from database.google_sheets import AsyncGoogleSheets
from database.sqlite_db import db as sqlite_db
from utils.ctx import sheet_id_ctx
from config import config


async def _ws(sheet_id: str, title: str, rows: int = 2000, cols: int = 30):
    token = sheet_id_ctx.set(sheet_id)
    try:
        sheets = AsyncGoogleSheets.get_instance()
        return await sheets.get_or_create_worksheet(title, rows=rows, cols=cols)
    finally:
        sheet_id_ctx.reset(token)


async def export_employees(sheet_id: str | None = None):
    sheet_id = sheet_id or config.google_sheet_id
    ws = await _ws(sheet_id, "Export_Сотрудники", rows=1000, cols=12)
    staff = await sqlite_db.get_all_staff(force_refresh=True)
    values = [["TelegramID", "Username", "Phone", "Имя", "Роль", "Магазин", "Активен", "Ставка", "Смайлик"]]
    for s in staff:
        values.append([s.get("TelegramID", ""), s.get("Username", ""), s.get("Phone", ""), s.get("Имя", ""), s.get("Роль", ""), s.get("Магазин", ""), s.get("Активен", ""), s.get("Ставка", ""), s.get("Смайлик", "")])
    await ws.clear()
    await ws.update("A1", values)
    return len(values) - 1


async def export_shifts(sheet_id: str | None = None, start_date: date | None = None, end_date: date | None = None):
    sheet_id = sheet_id or config.google_sheet_id
    ws = await _ws(sheet_id, "Export_Смены", rows=5000, cols=12)
    shifts = await sqlite_db.get_shift_rows(start_date=start_date, end_date=end_date)
    values = [["Дата", "TelegramID", "Имя", "Магазин", "Время начала", "Время конца", "Отработано", "Статус", "Опоздание", "Start location", "End location"]]
    for r in shifts:
        values.append([r["date"].strftime("%d-%m-%Y"), r.get("telegram_id", ""), r.get("name", ""), r.get("shop", ""), r.get("start", ""), r.get("end", ""), r.get("worked", ""), r.get("status", ""), r.get("late_minutes", 0), r.get("location", ""), ""])
    await ws.clear()
    await ws.update("A1", values)
    return len(values) - 1


async def export_schedule(sheet_id: str | None = None, start_date: date | None = None, end_date: date | None = None):
    sheet_id = sheet_id or config.google_sheet_id
    ws = await _ws(sheet_id, "Export_График", rows=5000, cols=8)
    rows = await sqlite_db.get_schedule_rows(start_date=start_date, end_date=end_date)
    values = [["Дата", "Имя", "TelegramID", "Магазин", "Время начала", "Время конца"]]
    for r in rows:
        values.append([r["date"].strftime("%d-%m-%Y"), r.get("name", ""), r.get("telegram_id", ""), r.get("shop", ""), r.get("start", ""), r.get("end", "")])
    await ws.clear()
    await ws.update("A1", values)
    return len(values) - 1


async def export_month_timesheet(sheet_id: str | None, year: int, month: int, shop: str | None = None):
    sheet_id = sheet_id or config.google_sheet_id
    start_d = date(year, month, 1)
    end_d = date(year, month, calendar.monthrange(year, month)[1])
    title = f"Export_Tabel_{year}_{month:02d}" + (f"_{shop}" if shop else "")
    ws = await _ws(sheet_id, title, rows=5000, cols=45)
    shifts = await sqlite_db.get_shift_rows(start_date=start_d, end_date=end_d)
    if shop:
        shifts = [s for s in shifts if s.get("shop") == shop]
    values = [["Дата", "TelegramID", "Имя", "Магазин", "Keldi", "Ketdi", "Ishladi"]]
    for r in shifts:
        values.append([r["date"].strftime("%d-%m-%Y"), r.get("telegram_id", ""), r.get("name", ""), r.get("shop", ""), r.get("start", ""), r.get("end", ""), r.get("worked", "")])
    await ws.clear()
    await ws.update("A1", values)
    return len(values) - 1
