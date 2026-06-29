"""Compare Google Sheets data with SQLite after migration.

Usage:
  python scripts/audit_migration.py
  python scripts/audit_migration.py --sheet-id YOUR_SHEET_ID

This script does not modify data. It prints counts by source, month, and shop.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import config
from utils.ctx import sheet_id_ctx
from database.google_sheets import db as sheets_db
from database.sqlite_db import db as sqlite_db


def _month_key(d):
    if not d:
        return "unknown"
    return f"{d.year:04d}-{d.month:02d}"


def _print_counter(title: str, counter: Counter):
    print(f"\n{title}")
    if not counter:
        print("  — empty")
        return
    for key, value in sorted(counter.items()):
        print(f"  {key}: {value}")


async def main(sheet_id: str | None = None):
    sid = sheet_id or config.google_sheet_id
    token = sheet_id_ctx.set(sid)
    try:
        print("=" * 64)
        print(f"AUDIT MIGRATION | Sheet ID: {sid}")
        print(f"SQLite DB: {sqlite_db.db_path}")
        print("=" * 64)

        # Google Sheets source
        staff_active = await sheets_db.get_all_staff(force_refresh=True, strict=False)
        shops_source = await sheets_db.get_shops_with_coords()
        schedules_source = await sheets_db.get_schedule_rows()
        shifts_source = await sheets_db.get_shift_rows()

        # SQLite target
        staff_sqlite = await sqlite_db.get_all_staff(force_refresh=True, strict=False)
        shops_sqlite = await sqlite_db.get_shops_with_coords()
        schedules_sqlite = await sqlite_db.get_schedule_rows()
        shifts_sqlite = await sqlite_db.get_shift_rows()

        print("\nCOUNTS")
        print(f"  Google Sheets active staff: {len(staff_active)}")
        print(f"  SQLite active staff:       {len(staff_sqlite)}")
        print(f"  Google Sheets shops:       {len(shops_source)}")
        print(f"  SQLite shops:              {len(shops_sqlite)}")
        print(f"  Google Sheets schedule:    {len(schedules_source)}")
        print(f"  SQLite schedule:           {len(schedules_sqlite)}")
        print(f"  Google Sheets shifts:      {len(shifts_source)}")
        print(f"  SQLite shifts:             {len(shifts_sqlite)}")

        _print_counter("GOOGLE SHEETS SHIFTS BY MONTH", Counter(_month_key(r.get("date")) for r in shifts_source))
        _print_counter("SQLITE SHIFTS BY MONTH", Counter(_month_key(r.get("date")) for r in shifts_sqlite))

        _print_counter("GOOGLE SHEETS SHIFTS BY SHOP", Counter(str(r.get("shop", "")).strip() or "—" for r in shifts_source))
        _print_counter("SQLITE SHIFTS BY SHOP", Counter(str(r.get("shop", "")).strip() or "—" for r in shifts_sqlite))

        _print_counter("GOOGLE SHEETS SCHEDULE BY MONTH", Counter(_month_key(r.get("date")) for r in schedules_source))
        _print_counter("SQLITE SCHEDULE BY MONTH", Counter(_month_key(r.get("date")) for r in schedules_sqlite))

        print("\nSHOP LIST FROM SQLITE")
        for sh in shops_sqlite:
            print(f"  - {sh.get('name')} | lat={sh.get('lat')} lon={sh.get('lon')}")

        print("\nSTAFF LIST FROM SQLITE")
        for st in staff_sqlite:
            print(f"  - {st.get('TelegramID')} | {st.get('Имя')} | {st.get('Роль')} | {st.get('Магазин')}")

        print("\nDONE")
    finally:
        sheet_id_ctx.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet-id", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.sheet_id))
