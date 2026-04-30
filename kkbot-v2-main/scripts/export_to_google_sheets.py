"""Export SQLite data back to Google Sheets.

Examples:
  python scripts/export_to_google_sheets.py employees
  python scripts/export_to_google_sheets.py shifts
  python scripts/export_to_google_sheets.py schedule
  python scripts/export_to_google_sheets.py tabel --year 2026 --month 4 --shop "TSM"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.google_export import export_employees, export_shifts, export_schedule, export_month_timesheet


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("type", choices=["employees", "shifts", "schedule", "tabel"])
    parser.add_argument("--sheet-id", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--shop", default=None)
    args = parser.parse_args()

    if args.type == "employees":
        count = await export_employees(args.sheet_id)
    elif args.type == "shifts":
        count = await export_shifts(args.sheet_id)
    elif args.type == "schedule":
        count = await export_schedule(args.sheet_id)
    else:
        if not args.year or not args.month:
            raise SystemExit("tabel export uchun --year va --month kerak")
        count = await export_month_timesheet(args.sheet_id, args.year, args.month, args.shop)
    print(f"✅ Export tayyor: {count} qator")


if __name__ == "__main__":
    asyncio.run(main())
