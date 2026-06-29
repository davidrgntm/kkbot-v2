"""Hard reset SQLite data and migrate again from Google Sheets.

Use this when Railway bot sees only 1 auto-created admin / 0 shops after migration.
It deletes local SQLite operational tables and imports fresh data from Google Sheets.
Google Sheets is NOT changed.

Usage:
  python scripts/reset_and_migrate.py
  python scripts/reset_and_migrate.py --sheet-id YOUR_SHEET_ID
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import config
from utils.ctx import sheet_id_ctx
from database.google_sheets import db as sheets_db
from database.sqlite_db import db as sqlite_db

TABLES_TO_CLEAR = [
    "user_shops",
    "employee_requests",
    "inventory",
    "audit_log",
    "export_jobs",
    "schedules",
    "shifts",
    "shops",
    "users",
]


async def reset_and_migrate(sheet_id: str | None = None):
    sid = sheet_id or config.google_sheet_id
    token = sheet_id_ctx.set(sid)
    try:
        print("=" * 64)
        print("RESET + MIGRATION STARTED")
        print(f"Sheet ID: {sid}")
        print(f"SQLite DB: {sqlite_db.db_path}")
        print("=" * 64)

        print("\n🧹 Clearing SQLite operational tables...")
        for table in TABLES_TO_CLEAR:
            try:
                sqlite_db._execute(f"DELETE FROM {table}")
                print(f"  cleared: {table}")
            except Exception as e:
                print(f"  skip/error {table}: {e}")

        print("\n⬇️ Reading Google Sheets...")
        staff = await sheets_db.get_all_staff(force_refresh=True, strict=False)
        shops = await sheets_db.get_shops_with_coords()
        schedules = await sheets_db.get_schedule_rows()
        shifts = await sheets_db.get_shift_rows()

        print("\n⬆️ Importing into SQLite...")
        staff_count = await sqlite_db.import_staff_records(staff)
        shops_count = await sqlite_db.import_shops_records(shops)
        schedules_count = await sqlite_db.import_schedule_rows(schedules)
        shifts_count = await sqlite_db.import_shift_rows(shifts)

        print("\nRESULT")
        print(f"✅ Сотрудники → SQLite: {staff_count}")
        print(f"✅ Магазины → SQLite: {shops_count}")
        print(f"✅ График → SQLite: {schedules_count}")
        print(f"✅ Смены → SQLite: {shifts_count}")

        sqlite_staff = await sqlite_db.get_all_staff(force_refresh=True, strict=False)
        sqlite_shops = await sqlite_db.get_shops()
        sqlite_shifts = await sqlite_db.get_shift_rows()
        sqlite_schedule = await sqlite_db.get_schedule_rows()

        print("\nCHECK CURRENT BOT CONTEXT")
        print(f"👥 Active staff visible to bot: {len(sqlite_staff)}")
        print(f"🏪 Shops visible to bot: {len(sqlite_shops)}")
        print(f"📅 Schedule rows visible to bot: {len(sqlite_schedule)}")
        print(f"🧾 Shift rows visible to bot: {len(sqlite_shifts)}")
        print("\nSHOP LIST:")
        for shop in sqlite_shops:
            print(f"  - {shop}")

        print("\n🎉 DONE. Set Railway Start Command back to: python main.py")
    finally:
        sheet_id_ctx.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet-id", default=None)
    args = parser.parse_args()
    asyncio.run(reset_and_migrate(args.sheet_id))
