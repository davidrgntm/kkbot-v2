from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import config
from database.sqlite_db import db

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

AI_MODE = os.environ.get("FACE_AI_MODE", "auto").lower()  # auto | phash | off
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.72"))
FACE_WEAK_THRESHOLD = float(os.environ.get("FACE_WEAK_THRESHOLD", "0.58"))
DEFAULT_RADIUS_M = int(os.environ.get("LOCATION_DEFAULT_RADIUS_M", "250"))
ALLOW_FIRST_REFERENCE = os.environ.get("FACE_ALLOW_FIRST_REFERENCE", "1") not in {"0", "false", "False", "no"}
DATA_DIR = Path(os.environ.get("DB_PATH", getattr(config, "db_path", "data/kkbot.db"))).parent
ATTENDANCE_DIR = DATA_DIR / "attendance_photos"
FACE_REF_DIR = DATA_DIR / "face_refs"
ATTENDANCE_DIR.mkdir(parents=True, exist_ok=True)
FACE_REF_DIR.mkdir(parents=True, exist_ok=True)


def ensure_verification_tables() -> None:
    db._execute(
        """
        CREATE TABLE IF NOT EXISTS face_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            reference_photo_path TEXT NOT NULL,
            reference_hash TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, telegram_id)
        )
        """
    )
    db._execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            shift_id INTEGER,
            action TEXT NOT NULL,
            source TEXT DEFAULT 'web',
            selfie_path TEXT DEFAULT '',
            latitude REAL,
            longitude REAL,
            gps_accuracy REAL,
            shop TEXT DEFAULT '',
            detected_shop TEXT DEFAULT '',
            distance_m REAL,
            location_status TEXT DEFAULT 'unknown',
            face_score REAL DEFAULT 0,
            face_status TEXT DEFAULT 'unknown',
            final_status TEXT DEFAULT 'needs_review',
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            decided_by TEXT DEFAULT '',
            decided_at TEXT,
            admin_comment TEXT DEFAULT ''
        )
        """
    )
    # optional columns for old DBs
    for sql in [
        "ALTER TABLE shops ADD COLUMN radius_m INTEGER DEFAULT 500",
        "ALTER TABLE users ADD COLUMN avatar_file_id TEXT DEFAULT ''",
    ]:
        try:
            db._execute(sql)
        except Exception:
            pass


ensure_verification_tables()


def _now_str() -> str:
    return datetime.now(config.get_timezone_obj()).replace(tzinfo=None).isoformat()


def _safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def save_data_url_image(data_url: str, telegram_id: str, prefix: str = "web") -> str:
    ensure_verification_tables()
    raw = str(data_url or "")
    if "," in raw:
        raw = raw.split(",", 1)[1]
    raw_bytes = base64.b64decode(raw)
    filename = f"{telegram_id}_{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    path = ATTENDANCE_DIR / filename
    path.write_bytes(raw_bytes)
    return str(path)


def save_bytes_image(raw_bytes: bytes, telegram_id: str, prefix: str = "bot") -> str:
    ensure_verification_tables()
    filename = f"{telegram_id}_{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    path = ATTENDANCE_DIR / filename
    path.write_bytes(raw_bytes)
    return str(path)


def _image_phash(path: str) -> str:
    if Image is None:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    try:
        img = Image.open(path).convert("L").resize((8, 8))
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = ''.join('1' if p > avg else '0' for p in pixels)
        return f"{int(bits, 2):016x}"
    except Exception:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _hash_score(h1: str, h2: str) -> float:
    try:
        a = bin(int(h1, 16))[2:].zfill(64)
        b = bin(int(h2, 16))[2:].zfill(64)
        dist = sum(1 for x, y in zip(a, b) if x != y)
        return max(0.0, min(1.0, 1.0 - dist / 64.0))
    except Exception:
        return 0.0


def _get_reference(telegram_id: str):
    return db._execute(
        "SELECT * FROM face_templates WHERE company_id=? AND telegram_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (db._current_cid(), str(telegram_id)),
        "one",
    )


def _set_reference(telegram_id: str, photo_path: str, ref_hash: str) -> None:
    ref_path = FACE_REF_DIR / f"{telegram_id}_reference.jpg"
    shutil.copyfile(photo_path, ref_path)
    db._execute(
        """
        INSERT INTO face_templates(company_id, telegram_id, reference_photo_path, reference_hash, status, updated_at)
        VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
        ON CONFLICT(company_id, telegram_id) DO UPDATE SET
          reference_photo_path=excluded.reference_photo_path,
          reference_hash=excluded.reference_hash,
          status='active',
          updated_at=CURRENT_TIMESTAMP
        """,
        (db._current_cid(), str(telegram_id), str(ref_path), ref_hash),
    )


def compare_face(telegram_id: str, photo_path: str) -> dict:
    """Face verification.

    Railway-safe default uses perceptual image hash. If a heavy face-recognition
    library is later installed, this function can be swapped without changing bot/web logic.
    """
    ensure_verification_tables()
    if AI_MODE == "off":
        return {"score": 0.0, "status": "ai_off", "reason": "FACE_AI_MODE=off"}
    new_hash = _image_phash(photo_path)
    ref = _get_reference(telegram_id)
    if not ref:
        if ALLOW_FIRST_REFERENCE:
            _set_reference(telegram_id, photo_path, new_hash)
            return {"score": 0.0, "status": "reference_created", "reason": "Birinchi selfie reference sifatida saqlandi. Admin tekshirishi kerak."}
        return {"score": 0.0, "status": "no_reference", "reason": "Reference rasm yo'q"}
    ref_hash = ref["reference_hash"] or _image_phash(ref["reference_photo_path"])
    score = _hash_score(ref_hash, new_hash)
    if score >= FACE_MATCH_THRESHOLD:
        status = "match"
    elif score >= FACE_WEAK_THRESHOLD:
        status = "weak"
    else:
        status = "no_match"
    return {"score": round(score, 4), "status": status, "reason": f"face score={round(score, 3)}"}


def detect_shop_by_location(lat: float | None, lon: float | None, fallback_shop: str = "") -> dict:
    ensure_verification_tables()
    if lat is None or lon is None:
        return {"shop": fallback_shop, "detected_shop": "", "distance_m": None, "location_status": "unknown", "reason": "GPS kelmadi"}
    shops = db._execute("SELECT name, lat, lon, COALESCE(radius_m, ?) AS radius_m FROM shops WHERE company_id=? AND active=1 ORDER BY name", (DEFAULT_RADIUS_M, db._current_cid()), "all")
    best = None
    for sh in shops:
        if sh["lat"] is None or sh["lon"] is None:
            continue
        dist = haversine_m(float(lat), float(lon), float(sh["lat"]), float(sh["lon"]))
        if best is None or dist < best["distance_m"]:
            best = {"shop": sh["name"], "detected_shop": sh["name"], "distance_m": dist, "radius_m": int(sh["radius_m"] or DEFAULT_RADIUS_M)}
    if not best:
        return {"shop": fallback_shop, "detected_shop": "", "distance_m": None, "location_status": "unknown", "reason": "Shop koordinatalari yo'q"}
    if best["distance_m"] <= best["radius_m"]:
        st = "ok"
    elif best["distance_m"] <= best["radius_m"] * 1.7:
        st = "weak"
    else:
        st = "far"
    return {"shop": best["shop"], "detected_shop": best["detected_shop"], "distance_m": round(float(best["distance_m"]), 1), "location_status": st, "reason": f"{round(float(best['distance_m']),1)}m / radius {best['radius_m']}m"}


def schedule_fallback_shop(telegram_id: str) -> str:
    today = datetime.now(config.get_timezone_obj()).date()
    row = db._execute(
        "SELECT shop FROM schedules WHERE company_id=? AND telegram_id=? AND work_date=? ORDER BY start_time LIMIT 1",
        (db._current_cid(), str(telegram_id), today.isoformat()),
        "one",
    )
    if row and row["shop"]:
        return row["shop"]
    row = db._execute(
        """
        SELECT s.name FROM users u
        JOIN user_shops us ON us.user_id=u.id
        JOIN shops s ON s.id=us.shop_id
        WHERE u.company_id=? AND u.telegram_id=? AND s.active=1
        ORDER BY s.name LIMIT 1
        """,
        (db._current_cid(), str(telegram_id)),
        "one",
    )
    return row["name"] if row else ""


def final_decision(face: dict, loc: dict) -> tuple[str, str]:
    reasons = []
    face_status = face.get("status", "unknown")
    loc_status = loc.get("location_status", "unknown")
    reasons.append(face.get("reason", ""))
    reasons.append(loc.get("reason", ""))
    if face_status == "match" and loc_status == "ok":
        return "approved", "; ".join([x for x in reasons if x])
    if face_status == "no_match" and loc_status == "far":
        return "rejected", "; ".join([x for x in reasons if x])
    return "needs_review", "; ".join([x for x in reasons if x])


def log_check(telegram_id: str, action: str, selfie_path: str, lat: float | None, lon: float | None, accuracy: float | None, shop: str, detected_shop: str, distance_m: float | None, location_status: str, face_score: float, face_status: str, final_status: str, reason: str, shift_id: int | None = None, source: str = "web") -> int:
    ensure_verification_tables()
    cur = db._execute(
        """
        INSERT INTO attendance_checks(company_id, telegram_id, shift_id, action, source, selfie_path, latitude, longitude, gps_accuracy, shop, detected_shop, distance_m, location_status, face_score, face_status, final_status, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (db._current_cid(), str(telegram_id), shift_id, action, source, selfie_path, lat, lon, accuracy, shop, detected_shop, distance_m, location_status, face_score, face_status, final_status, reason),
    )
    return int(cur.lastrowid)


def verify_attendance(telegram_id: str, action: str, selfie_path: str, lat: float | None, lon: float | None, accuracy: float | None = None, shift_id: int | None = None, source: str = "web", fallback_shop: str = "") -> dict:
    ensure_verification_tables()
    tid = str(telegram_id).replace(".0", "").strip()
    fallback = fallback_shop or schedule_fallback_shop(tid)
    loc = detect_shop_by_location(lat, lon, fallback)
    face = compare_face(tid, selfie_path)
    final_status, reason = final_decision(face, loc)
    check_id = log_check(
        tid,
        action,
        selfie_path,
        lat,
        lon,
        accuracy,
        loc.get("shop") or fallback,
        loc.get("detected_shop") or "",
        loc.get("distance_m"),
        loc.get("location_status") or "unknown",
        float(face.get("score") or 0),
        face.get("status") or "unknown",
        final_status,
        reason,
        shift_id=shift_id,
        source=source,
    )
    return {
        "check_id": check_id,
        "telegram_id": tid,
        "action": action,
        "shop": loc.get("shop") or fallback,
        "detected_shop": loc.get("detected_shop") or "",
        "distance_m": loc.get("distance_m"),
        "location_status": loc.get("location_status"),
        "face_status": face.get("status"),
        "face_score": face.get("score"),
        "final_status": final_status,
        "reason": reason,
        "selfie_path": selfie_path,
    }


def checks(limit: int = 100) -> list[dict]:
    ensure_verification_tables()
    rows = db._execute(
        """
        SELECT ac.*, u.full_name AS name
        FROM attendance_checks ac
        LEFT JOIN users u ON u.company_id=ac.company_id AND u.telegram_id=ac.telegram_id
        WHERE ac.company_id=?
        ORDER BY ac.id DESC LIMIT ?
        """,
        (db._current_cid(), int(limit)),
        "all",
    )
    return [dict(r) for r in rows]


def update_check_status(check_id: int, status: str, admin_tid: str = "", comment: str = "") -> bool:
    ensure_verification_tables()
    db._execute(
        "UPDATE attendance_checks SET final_status=?, decided_by=?, decided_at=CURRENT_TIMESTAMP, admin_comment=? WHERE company_id=? AND id=?",
        (status, str(admin_tid), comment, db._current_cid(), int(check_id)),
    )
    return True
