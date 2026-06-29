"""Migrate current Google Sheets data into SQLite.

Usage:
  python scripts/migrate_from_google_sheets.py
  python scripts/migrate_from_google_sheets.py --sheet-id YOUR_SHEET_ID

The script reads tabs from Google Sheets and writes them into data/kkbot.db.
It does not delete anything from Google Sheets.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.ctx import sheet_id_ctx
from config import config
from database.google_sheets import db as sheets_db
from database.sqlite_db import db as sqlite_db


async def migrate(sheet_id: str | None = None):
    sid = sheet_id or config.google_sheet_id
    token = sheet_id_ctx.set(sid)
    try:
        print(f"➡️  Migratsiya boshlandi. Sheet ID: {sid}")

        staff = await sheets_db.get_all_staff(force_refresh=True, strict=False)
        staff_count = await sqlite_db.import_staff_records(staff)
        print(f"✅ Сотрудники → SQLite: {staff_count}")

        shops = await sheets_db.get_shops_with_coords()
        shops_count = await sqlite_db.import_shops_records(shops)
        print(f"✅ Магазины → SQLite: {shops_count}")

        schedules = await sheets_db.get_schedule_rows()
        schedules_count = await sqlite_db.import_schedule_rows(schedules)
        print(f"✅ График → SQLite: {schedules_count}")

        shifts = await sheets_db.get_shift_rows()
        shifts_count = await sqlite_db.import_shift_rows(shifts)
        print(f"✅ Смены → SQLite: {shifts_count}")

        print(f"\n🎉 Tayyor. SQLite baza: {sqlite_db.db_path}")
        print("Endi bot SQLite bazadan ishlaydi. Google Sheets faqat eksport/backup uchun qoladi.")
    finally:
        sheet_id_ctx.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet-id", default=None, help="Migrate a specific Google Sheet ID")
    args = parser.parse_args()
    asyncio.run(migrate(args.sheet_id))
