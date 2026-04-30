from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database.sqlite_db import db
from config import config

print("DB_PATH:", db.db_path)
print("GOOGLE_SHEET_ID:", config.google_sheet_id)
print("CURRENT_CID:", db._current_cid())
for row in db._execute("""
SELECT company_id,
       (SELECT COUNT(*) FROM users u WHERE u.company_id=c.company_id AND u.active=1) users,
       (SELECT COUNT(*) FROM shops s WHERE s.company_id=c.company_id AND s.active=1) shops,
       (SELECT COUNT(*) FROM shifts sh WHERE sh.company_id=c.company_id) shifts,
       (SELECT COUNT(*) FROM schedules sc WHERE sc.company_id=c.company_id) schedules
FROM (
  SELECT company_id FROM users
  UNION SELECT company_id FROM shops
  UNION SELECT company_id FROM shifts
  UNION SELECT company_id FROM schedules
) c
ORDER BY shifts DESC, shops DESC, users DESC
""", (), "all"):
    print(dict(row))
