from __future__ import annotations

import asyncio
import calendar
import hashlib
import hmac
import html
import json
import os
import random
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import FastAPI, Form, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse

from config import config
from database.sqlite_db import db, _time_to_minutes
from services.google_export import export_employees, export_shifts, export_schedule, export_month_timesheet
from services.quick_schedule import parse_quick_schedule, render_quick_schedule_preview, find_conflicts

APP_TITLE = "KKB Web Panel"
SESSION_COOKIE = "kkb_session"
SESSION_TTL = 60 * 60 * 24 * 14
OTP_TTL = 10 * 60

app = FastAPI(title=APP_TITLE)


# -----------------------------
# Core helpers
# -----------------------------
def now_tz() -> datetime:
    return datetime.now(config.get_timezone_obj())


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def money(v: Any) -> str:
    try:
        return f"{round(float(v or 0)):,}".replace(",", " ")
    except Exception:
        return "0"


def normalize_phone(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def parse_date(value: str | None, default: Optional[date] = None) -> Optional[date]:
    if not value:
        return default
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except Exception:
            pass
    return default


def parse_dt_local(d: str, t: str) -> Optional[datetime]:
    parsed = parse_date(d)
    if not parsed:
        return None
    try:
        tm = datetime.strptime(t, "%H:%M").time()
        return datetime.combine(parsed, tm)
    except Exception:
        return None


def month_name(m: int) -> str:
    return {
        1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel", 5: "May", 6: "Iyun",
        7: "Iyul", 8: "Avgust", 9: "Sentabr", 10: "Oktabr", 11: "Noyabr", 12: "Dekabr",
    }.get(int(m), str(m))


def worked_text(minutes: int | float | None) -> str:
    m = max(0, int(minutes or 0))
    return f"{m // 60} ч {m % 60:02d} м"


def legacy_paid_minutes_from_total(raw_minutes: int) -> tuple[int, int]:
    """Eski botdagi aynan o'sha oylik/tabel qoidasi."""
    raw_minutes = max(0, int(raw_minutes or 0))
    h = raw_minutes // 60
    m = raw_minutes % 60
    if m >= 30:
        h += 1
    break_minutes = 60 if h >= 5 else 0
    if h >= 5:
        h -= 1
    return max(0, h * 60), break_minutes


def legacy_paid_minutes(start_at: datetime, end_at: datetime) -> tuple[int, int, int]:
    raw = max(0, int((end_at - start_at).total_seconds() // 60))
    paid, br = legacy_paid_minutes_from_total(raw)
    return raw, paid, br


def iso_short(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def sign(value: str) -> str:
    secret = os.getenv("WEB_SECRET") or config.bot_token.get_secret_value()
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_session(tid: str, role: str) -> str:
    exp = int(time.time()) + SESSION_TTL
    base = f"{tid}|{role}|{exp}"
    return f"{base}|{sign(base)}"


def verify_session(raw: str | None) -> Optional[dict]:
    if not raw:
        return None
    parts = str(raw).split("|")
    if len(parts) != 4:
        return None
    tid, role, exp, sig = parts
    base = f"{tid}|{role}|{exp}"
    if not hmac.compare_digest(sig, sign(base)):
        return None
    if int(exp) < int(time.time()):
        return None
    if tid == "admin_password":
        return {"telegram_id": tid, "role": "admin", "name": "Admin", "phone": ""}
    row = db._execute(
        "SELECT * FROM users WHERE company_id=? AND telegram_id=? AND active=1",
        (db._current_cid(), str(tid)),
        "one",
    )
    if not row:
        return None
    return {
        "telegram_id": str(row["telegram_id"]),
        "role": str(row["role"] or "staff").lower(),
        "name": row["full_name"] or "Xodim",
        "phone": row["phone"] or "",
    }


def current_user(request: Request) -> Optional[dict]:
    return verify_session(request.cookies.get(SESSION_COOKIE))


def is_admin(user: Optional[dict]) -> bool:
    return bool(user and user.get("role") in {"admin", "manager", "super_admin"})


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def require_login(request: Request) -> Optional[RedirectResponse]:
    return None if current_user(request) else redirect("/login")


def require_admin(request: Request) -> Optional[RedirectResponse]:
    u = current_user(request)
    return None if is_admin(u) else redirect("/cabinet")


def ensure_web_tables() -> None:
    db._execute(
        """
        CREATE TABLE IF NOT EXISTS web_login_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            phone TEXT DEFAULT '',
            code_hash TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


ensure_web_tables()


def find_user_by_phone_or_id(value: str) -> Optional[Any]:
    target = normalize_phone(value)
    if not target:
        return None
    rows = db._execute(
        "SELECT * FROM users WHERE company_id=? AND active=1",
        (db._current_cid(),),
        "all",
    )
    for r in rows:
        tid = normalize_phone(str(r["telegram_id"]))
        phone = normalize_phone(str(r["phone"] or ""))
        if target == tid:
            return r
        if phone and (target == phone or phone.endswith(target) or target.endswith(phone[-9:])):
            return r
    return None


def send_telegram_message(chat_id: str, text: str) -> None:
    token = config.bot_token.get_secret_value()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


async def send_otp(tid: str, code: str) -> None:
    text = f"KKB Web Panel uchun login kod: {code}\nKod 10 daqiqa amal qiladi."
    await asyncio.to_thread(send_telegram_message, tid, text)


def create_otp(tid: str, phone: str) -> str:
    code = f"{random.randint(100000, 999999)}"
    code_hash = hashlib.sha256((code + sign(tid)).encode()).hexdigest()
    db._execute(
        "INSERT INTO web_login_codes(company_id, telegram_id, phone, code_hash, expires_at) VALUES (?, ?, ?, ?, ?)",
        (db._current_cid(), str(tid), phone, code_hash, int(time.time()) + OTP_TTL),
    )
    return code


def verify_otp(tid: str, code: str) -> bool:
    code_hash = hashlib.sha256((str(code).strip() + sign(tid)).encode()).hexdigest()
    row = db._execute(
        """
        SELECT * FROM web_login_codes
        WHERE company_id=? AND telegram_id=? AND code_hash=? AND used=0 AND expires_at>=?
        ORDER BY id DESC LIMIT 1
        """,
        (db._current_cid(), str(tid), code_hash, int(time.time())),
        "one",
    )
    if not row:
        return False
    db._execute("UPDATE web_login_codes SET used=1 WHERE id=?", (row["id"],))
    return True


# -----------------------------
# UI helpers
# -----------------------------
CSS = """
:root{--bg:#f5f7fb;--card:#fff;--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--brand:#2563eb;--brand2:#1d4ed8;--green:#16a34a;--red:#dc2626;--amber:#d97706;--purple:#7c3aed;--shadow:0 14px 44px rgba(15,23,42,.08);--r:22px}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{text-decoration:none;color:inherit}.app{display:grid;grid-template-columns:280px 1fr;min-height:100vh}.side{background:#07132c;color:#fff;padding:24px;position:sticky;top:0;height:100vh;z-index:50;transition:.2s}.logo{display:flex;align-items:center;gap:12px;font-size:21px;font-weight:900;margin-bottom:20px}.logo-badge{width:44px;height:44px;border-radius:15px;background:linear-gradient(135deg,#60a5fa,#1d4ed8);display:grid;place-items:center}.nav{display:flex;flex-direction:column;gap:8px}.nav a{padding:13px 14px;border-radius:14px;color:#cbd5e1;font-weight:700}.nav a:hover,.nav a.active{background:rgba(255,255,255,.12);color:#fff}.main{padding:28px 34px}.mobile-head{display:none;position:sticky;top:0;z-index:60;background:#07132c;color:#fff;padding:12px 14px;align-items:center;justify-content:space-between;box-shadow:0 10px 24px rgba(15,23,42,.2)}.hamb{border:0;background:#172554;color:#fff;border-radius:12px;padding:10px 14px;font-weight:900}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:22px}.h1{font-size:30px;font-weight:900;letter-spacing:-.03em}.sub{color:var(--muted);margin-top:5px}.btn{border:0;background:var(--brand);color:#fff;border-radius:13px;padding:11px 15px;font-weight:800;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px}.btn:hover{background:var(--brand2)}.btn.secondary{background:#eef2ff;color:#1e40af}.btn.gray{background:#f1f5f9;color:#0f172a}.btn.danger{background:var(--red)}.grid{display:grid;gap:18px}.cards{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:18px}.card{background:var(--card);border:1px solid rgba(226,232,240,.9);border-radius:var(--r);box-shadow:var(--shadow);padding:20px}.metric .label{color:var(--muted);font-weight:800}.metric .value{font-size:33px;font-weight:950;margin-top:6px;letter-spacing:-.04em}.metric .hint{font-size:12px;color:var(--muted);margin-top:6px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.form{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}.input,.select,textarea{height:42px;border:1px solid var(--line);background:white;border-radius:13px;padding:0 13px;font:inherit;min-width:170px}textarea{height:auto;padding:12px}.table-wrap{overflow:auto}.table{width:100%;border-collapse:separate;border-spacing:0 9px}.table th{text-align:left;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;padding:0 12px;white-space:nowrap}.table td{background:#fff;padding:13px 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:middle}.table td:first-child{border-left:1px solid var(--line);border-radius:15px 0 0 15px}.table td:last-child{border-right:1px solid var(--line);border-radius:0 15px 15px 0}.pill{display:inline-flex;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:900;background:#f1f5f9;color:#334155}.pill.green{background:#dcfce7;color:#166534}.pill.red{background:#fee2e2;color:#991b1b}.pill.blue{background:#dbeafe;color:#1d4ed8}.pill.amber{background:#fef3c7;color:#92400e}.pill.purple{background:#ede9fe;color:#5b21b6}.split{display:grid;grid-template-columns:1.25fr .75fr;gap:18px}.login{min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#0f172a,#1d4ed8)}.login-card{width:min(460px,92vw);background:white;border-radius:28px;padding:30px;box-shadow:0 30px 80px rgba(0,0,0,.25)}.login-card h1{margin:0 0 8px;font-size:30px}.login-card p{color:var(--muted);margin:0 0 18px}.login-card input{width:100%;height:50px;border:1px solid var(--line);border-radius:16px;padding:0 15px;font-size:16px}.login-card button{width:100%;height:50px;margin-top:12px}.alert{padding:12px 14px;border-radius:14px;margin-bottom:14px}.alert.ok{background:#dcfce7;color:#166534}.alert.err{background:#fee2e2;color:#991b1b}.footer{margin-top:26px;color:var(--muted);font-size:13px}.bar{height:12px;background:#e2e8f0;border-radius:999px;overflow:hidden}.bar>i{display:block;height:100%;background:linear-gradient(90deg,#60a5fa,#2563eb);border-radius:999px}.chart-row{display:grid;grid-template-columns:120px 1fr 70px;gap:10px;align-items:center;margin:10px 0}.live-list{display:grid;gap:10px}.live-item{border:1px solid var(--line);border-radius:18px;padding:14px;background:#fff}.live-item .name{font-weight:900}.live-seconds{font-size:22px;font-weight:950}.avatar{width:92px;height:92px;border-radius:28px;object-fit:cover;background:#e2e8f0;display:inline-grid;place-items:center;font-size:34px}.mini{font-size:12px;color:var(--muted)}@media(max-width:980px){.mobile-head{display:flex}.app{display:block}.side{display:none;height:auto;position:sticky;top:52px;border-radius:0 0 24px 24px}.side.open{display:block}.nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.main{padding:18px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.split{grid-template-columns:1fr}.top{align-items:center}.h1{font-size:26px}}@media(max-width:620px){.cards{grid-template-columns:1fr}.form{display:grid}.input,.select,.btn,textarea{width:100%}.h1{font-size:24px}.nav{grid-template-columns:1fr}.table td,.table th{font-size:13px;padding:10px}.chart-row{grid-template-columns:90px 1fr 55px}.metric .value{font-size:30px}}
"""


def nav(active: str, user: dict) -> str:
    admin = is_admin(user)
    items = [("cabinet", "/cabinet", "👤 Kabinetim")]
    if admin:
        items += [
            ("dashboard", "/dashboard", "🏠 Dashboard"),
            ("employees", "/employees", "👥 Xodimlar"),
            ("shops", "/shops", "🏪 Shoplar"),
            ("shifts", "/shifts", "🟢 Smenalar"),
            ("schedule", "/schedule", "📅 Grafik"),
            ("quick", "/quick-schedule", "⚡ Tez grafik"),
            ("salary", "/salary", "💰 Oylik"),
            ("requests", "/requests", "📝 Arizalar"),
            ("inventory", "/inventory", "📦 Inventar"),
            ("export", "/export", "📤 Export"),
        ]
    else:
        items += [("my_shifts", "/my-shifts", "🟢 Smenalarim"), ("my_schedule", "/my-schedule", "📅 Grafikim")]
    links = "".join(f'<a class="{"active" if k == active else ""}" href="{h}">{lab}</a>' for k, h, lab in items)
    return f"""
    <aside class="side" id="sideNav">
      <div class="logo"><div class="logo-badge">K</div><div>KKB<br><span style="font-size:12px;color:#93c5fd;font-weight:700">Web Panel</span></div></div>
      <div style="margin-bottom:16px;color:#bfdbfe;font-size:14px">{esc(user.get('name'))}<br>{esc(user.get('role'))}</div>
      <nav class="nav">{links}</nav>
      <form method="post" action="/logout" style="margin-top:22px"><button class="btn gray" style="width:100%">Chiqish</button></form>
    </aside>
    """


def layout(request: Request, active: str, title: str, subtitle: str, content: str) -> HTMLResponse:
    user = current_user(request) or {"name": "", "role": ""}
    mobile = f"""<div class="mobile-head"><b>KKB · {esc(title)}</b><button class="hamb" onclick="document.getElementById('sideNav').classList.toggle('open')">☰ Menu</button></div>"""
    script = """
    <script>
    window.addEventListener('beforeunload',()=>sessionStorage.setItem('scrollY', String(window.scrollY||0)));
    window.addEventListener('load',()=>{const y=sessionStorage.getItem('scrollY'); if(y){setTimeout(()=>window.scrollTo(0, Number(y)),30)}});
    </script>
    """
    return HTMLResponse(f"""<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · {APP_TITLE}</title><style>{CSS}</style></head>
    <body>{mobile}<div class="app">{nav(active, user)}<main class="main"><div class="top"><div><div class="h1">{esc(title)}</div><div class="sub">{subtitle}</div></div><button class="btn secondary" onclick="if(window.softRefresh)softRefresh();else location.reload()">Yangilash</button></div>{content}<div class="footer">DB: {esc(db.db_path)} · Company: {esc(db._current_cid())}</div></main></div>{script}</body></html>""")


def table(headers: list[str], rows: str, empty_cols: int) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = rows or f"<tr><td colspan='{empty_cols}'>Ma'lumot yo‘q</td></tr>"
    return f"<div class='table-wrap'><table class='table'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


def staff_options(selected: str = "") -> str:
    rows = db._execute("SELECT telegram_id, full_name FROM users WHERE company_id=? AND active=1 ORDER BY full_name", (db._current_cid(),), "all")
    return "".join(f"<option value='{esc(r['telegram_id'])}' {'selected' if str(r['telegram_id'])==str(selected) else ''}>{esc(r['full_name'])}</option>" for r in rows)


def shop_options(selected: str = "", include_empty: bool = True) -> str:
    opts = "<option value=''>Barcha shoplar</option>" if include_empty else ""
    for sh in db._execute("SELECT name FROM shops WHERE company_id=? AND active=1 ORDER BY name", (db._current_cid(),), "all"):
        name = sh["name"]
        opts += f"<option value='{esc(name)}' {'selected' if name==selected else ''}>{esc(name)}</option>"
    return opts


# -----------------------------
# Auth routes
# -----------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", sent: str = "", phone: str = ""):
    if current_user(request):
        return redirect("/dashboard")
    alert = ""
    if error:
        alert = f"<div class='alert err'>{esc(error)}</div>"
    if sent:
        alert = f"<div class='alert ok'>Kod Telegramga yuborildi. Kodni kiriting.</div>"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Login · {APP_TITLE}</title><style>{CSS}</style></head>
    <body class="login"><div class="login-card"><h1>KKB Web Panel</h1><p>Telefon raqamingizni kiriting. Kod Telegram bot orqali keladi.</p>{alert}
    <form method="post" action="/login/request"><input name="phone" value="{esc(phone)}" placeholder="Telefon: +998..." required><button class="btn">Kod olish</button></form>
    <form method="post" action="/login/verify"><input name="phone" value="{esc(phone)}" placeholder="Telefon" required style="margin-top:12px"><input name="code" placeholder="6 xonali kod" required style="margin-top:12px"><button class="btn">Kirish</button></form>
    <details style="margin-top:18px"><summary>Admin parol bilan kirish</summary><form method="post" action="/login/password"><input type="password" name="password" placeholder="WEB_ADMIN_PASSWORD" style="margin-top:12px"><button class="btn gray">Admin kirish</button></form></details>
    </div></body></html>""")


@app.post("/login/request")
async def login_request(phone: str = Form(...)):
    user = find_user_by_phone_or_id(phone)
    if not user:
        return redirect(f"/login?error={urllib.parse.quote('Telefon bazadan topilmadi. Сотрудники → Phone ustunini tekshiring.')}&phone={urllib.parse.quote(phone)}")
    tid = str(user["telegram_id"])
    code = create_otp(tid, str(user["phone"] or phone))
    try:
        await send_otp(tid, code)
    except Exception as e:
        return redirect(f"/login?error={urllib.parse.quote('Telegramga kod yuborilmadi: ' + str(e))}&phone={urllib.parse.quote(phone)}")
    return redirect(f"/login?sent=1&phone={urllib.parse.quote(phone)}")


@app.post("/login/verify")
async def login_verify(phone: str = Form(...), code: str = Form(...)):
    user = find_user_by_phone_or_id(phone)
    if not user or not verify_otp(str(user["telegram_id"]), code):
        return redirect(f"/login?error={urllib.parse.quote('Kod noto‘g‘ri yoki muddati tugagan')}&phone={urllib.parse.quote(phone)}")
    role = str(user["role"] or "staff").lower()
    res = redirect("/dashboard" if role in {"admin", "manager", "super_admin"} else "/cabinet")
    res.set_cookie(SESSION_COOKIE, make_session(str(user["telegram_id"]), role), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return res


@app.post("/login/password")
async def login_password(password: str = Form(...)):
    expected = os.getenv("WEB_ADMIN_PASSWORD") or os.getenv("WEB_PASSWORD") or (str(config.get_admin_ids()[0]) if config.get_admin_ids() else "admin")
    if not hmac.compare_digest(str(password), str(expected)):
        return redirect("/login?error=Admin parol noto‘g‘ri")
    res = redirect("/dashboard")
    res.set_cookie(SESSION_COOKIE, make_session("admin_password", "admin"), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return res


@app.post("/logout")
async def logout():
    res = redirect("/login")
    res.delete_cookie(SESSION_COOKIE)
    return res


@app.get("/")
async def root(request: Request):
    u = current_user(request)
    if not u:
        return redirect("/login")
    return redirect("/dashboard" if is_admin(u) else "/cabinet")



# -----------------------------
# Live dashboard helpers
# -----------------------------
def _dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _raw_minutes_for_row(r: Any, end_at: Optional[datetime] = None) -> int:
    start = _dt(r["start_at"])
    end = end_at or _dt(r["end_at"])
    if not start or not end:
        return 0
    return max(0, int((end - start).total_seconds() // 60))


def _rate_map() -> dict[str, float]:
    rows = db._execute("SELECT telegram_id, hourly_rate FROM users WHERE company_id=?", (db._current_cid(),), "all")
    return {str(r["telegram_id"]): float(r["hourly_rate"] or 0) for r in rows}


def _planned_for_shift(r: Any) -> Optional[Any]:
    return db._execute(
        """
        SELECT * FROM schedules
        WHERE company_id=? AND telegram_id=? AND work_date=? AND kind='shift'
        ORDER BY id DESC LIMIT 1
        """,
        (db._current_cid(), str(r["telegram_id"]), str(r["business_date"])),
        "one",
    )


def _punctuality(r: Any) -> dict[str, Any]:
    planned = _planned_for_shift(r)
    start = _dt(r["start_at"])
    if not planned or not start or not planned["start_time"]:
        return {"kind":"unknown","label":"Rejasiz","minutes":0,"class":"blue","planned_start":"—","planned_end":"—"}
    try:
        planned_start = datetime.combine(parse_date(planned["work_date"]) or start.date(), datetime.strptime(planned["start_time"], "%H:%M").time())
        diff = int((start.replace(tzinfo=None) - planned_start).total_seconds() // 60)
        if diff > 5:
            return {"kind":"late","label":f"Kechikdi {diff}m","minutes":diff,"class":"red","planned_start":planned["start_time"],"planned_end":planned["end_time"]}
        if diff < -5:
            return {"kind":"early","label":f"Erta {abs(diff)}m","minutes":abs(diff),"class":"amber","planned_start":planned["start_time"],"planned_end":planned["end_time"]}
        return {"kind":"ontime","label":"Vaqtida","minutes":0,"class":"green","planned_start":planned["start_time"],"planned_end":planned["end_time"]}
    except Exception:
        return {"kind":"unknown","label":"Reja xato","minutes":0,"class":"blue","planned_start":planned["start_time"],"planned_end":planned["end_time"]}


def _dashboard_payload() -> dict[str, Any]:
    n = now_tz()
    today = n.date()
    month_start = today.replace(day=1)
    cid = db._current_cid()
    staff_count = db._execute("SELECT COUNT(*) AS c FROM users WHERE company_id=? AND active=1", (cid,), "one")["c"]
    shop_count = db._execute("SELECT COUNT(*) AS c FROM shops WHERE company_id=? AND active=1", (cid,), "one")["c"]
    rates = _rate_map()
    open_rows = db._execute("SELECT * FROM shifts WHERE company_id=? AND status='open' ORDER BY start_at ASC", (cid,), "all")
    closed_today = db._execute("SELECT * FROM shifts WHERE company_id=? AND business_date=? AND status='closed'", (cid, today.isoformat()), "all")
    month_row = db._execute("SELECT COALESCE(SUM(worked_minutes),0) AS paid, COUNT(*) AS c FROM shifts WHERE company_id=? AND business_date>=?", (cid, month_start.isoformat()), "one")
    month_closed = db._execute("SELECT * FROM shifts WHERE company_id=? AND business_date>=? AND status='closed'", (cid, month_start.isoformat()), "all")
    raw_month = sum(_raw_minutes_for_row(r) for r in month_closed)
    shop_online = {}
    open_list = []
    for r in open_rows:
        start = _dt(r["start_at"])
        elapsed = max(0, int((n - start).total_seconds())) if start else 0
        paid_now, br = legacy_paid_minutes_from_total(elapsed // 60)
        rate = rates.get(str(r["telegram_id"]), 0)
        shop_online[r["shop"] or "—"] = shop_online.get(r["shop"] or "—", 0) + 1
        open_list.append({
            "id": r["id"], "name": r["name"], "shop": r["shop"], "start_at": r["start_at"],
            "start_ts": int(start.timestamp()) if start else 0, "elapsed_seconds": elapsed,
            "paid_minutes": paid_now, "raw_minutes": elapsed//60, "earned": round((paid_now/60)*rate), "rate": rate,
        })
    p_counts = {"ontime":0,"late":0,"early":0,"unknown":0}
    for r in closed_today:
        p = _punctuality(r)
        p_counts[p["kind"]] = p_counts.get(p["kind"], 0) + 1
    recent = []
    recent_rows = db._execute("SELECT * FROM shifts WHERE company_id=? ORDER BY start_at DESC LIMIT 16", (cid,), "all")
    for r in recent_rows:
        raw = _raw_minutes_for_row(r)
        paid = int(r["worked_minutes"] or 0)
        rate = rates.get(str(r["telegram_id"]), 0)
        p = _punctuality(r)
        recent.append({
            "name": r["name"], "shop": r["shop"], "start": iso_short(r["start_at"]), "end": iso_short(r["end_at"]),
            "status": r["status"], "raw": worked_text(raw), "paid": worked_text(paid), "break": worked_text(r["break_minutes"] or 0),
            "punctuality": p["label"], "p_class": p["class"], "planned": f"{p['planned_start']} - {p['planned_end']}",
            "earned": money((paid/60)*rate),
        })
    return {
        "staff": int(staff_count or 0), "shops": int(shop_count or 0), "open": len(open_rows), "closed_today": len(closed_today),
        "month_paid_minutes": int(month_row["paid"] or 0), "month_raw_minutes": int(raw_month), "month_shifts": int(month_row["c"] or 0),
        "open_list": open_list, "shop_online": shop_online, "punctuality": p_counts, "recent": recent,
        "updated_at": n.strftime("%H:%M:%S"),
    }


def _chart_bars(data: dict[str, int], total: int | None = None) -> str:
    total = total or max(sum(data.values()), 1)
    out = ""
    for k, v in data.items():
        pct = min(100, int((v / total) * 100)) if total else 0
        out += f"<div class='chart-row'><b>{esc(k)}</b><div class='bar'><i style='width:{pct}%'></i></div><span>{v}</span></div>"
    return out or "<p class='sub'>Ma'lumot yo‘q</p>"


def _render_dashboard(payload: dict[str, Any]) -> str:
    p = payload["punctuality"]
    live_rows = "".join(
        f"<div class='live-item' data-start='{x['start_ts']}' data-rate='{x['rate']}'><div class='row' style='justify-content:space-between'><div><div class='name'>{esc(x['name'])}</div><div class='mini'>{esc(x['shop'])} · {iso_short(x['start_at'])}</div></div><span class='pill green'>online</span></div><div class='row' style='margin-top:10px'><div class='live-seconds' data-live>—</div><span class='pill blue' data-money>{money(x['earned'])} so‘m</span></div></div>"
        for x in payload["open_list"]
    ) or "<p class='sub'>Hozir ochiq smena yo‘q.</p>"
    recent_rows = "".join(
        f"<tr><td>{esc(r['name'])}</td><td>{esc(r['shop'])}</td><td>{esc(r['planned'])}</td><td>{esc(r['start'])}</td><td>{esc(r['end'])}</td><td><span class='pill {r['p_class']}'>{esc(r['punctuality'])}</span></td><td>{esc(r['raw'])}</td><td><b>{esc(r['paid'])}</b><br><span class='mini'>-{esc(r['break'])}</span></td><td>{esc(r['earned'])}</td></tr>"
        for r in payload["recent"]
    )
    return f"""
    <div class="grid cards">
      <div class="card metric"><div class="label">Faol xodimlar</div><div class="value">{payload['staff']}</div><div class="hint">bazadagi active xodimlar</div></div>
      <div class="card metric"><div class="label">Hozir ishda</div><div class="value">{payload['open']}</div><div class="hint">live ochiq smena</div></div>
      <div class="card metric"><div class="label">Bugun yopilgan</div><div class="value">{payload['closed_today']}</div><div class="hint">closed smenalar</div></div>
      <div class="card metric"><div class="label">Bu oy yozilgan</div><div class="value">{round(payload['month_paid_minutes']/60,1)}</div><div class="hint">real {round(payload['month_raw_minutes']/60,1)} soat</div></div>
    </div>
    <div class="split">
      <div class="card"><div class='row' style='justify-content:space-between'><h2>🟢 Online smenalar</h2><span class='pill blue'>auto live</span></div><div class='live-list'>{live_rows}</div></div>
      <div class="card"><h2>🏪 Hozir qaysi magazinda nechta odam?</h2>{_chart_bars(payload['shop_online'])}<hr style='border:0;border-top:1px solid var(--line);margin:18px 0'><h2>⏰ Bugungi punctuality</h2>{_chart_bars({'Vaqtida':p.get('ontime',0),'Kechikdi':p.get('late',0),'Erta keldi':p.get('early',0),'Rejasiz':p.get('unknown',0)})}</div>
    </div>
    <div class="card" style="margin-top:18px"><div class='row' style='justify-content:space-between'><h2>Oxirgi smenalar: reja / fakt / hisob</h2><span class='pill'>Yangilandi: {payload['updated_at']}</span></div>{table(['Ism','Shop','Reja','Keldi','Ketdi','Holat','Real ishladi','Yozildi','Pul'], recent_rows, 9)}</div>
    """

# -----------------------------
# Cabinet
# -----------------------------
@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(request: Request):
    if red := require_login(request):
        return red
    u = current_user(request)
    tid = str(u["telegram_id"])
    if tid == "admin_password":
        return redirect("/dashboard")
    profile = await db.get_staff_profile(tid)
    row = db._execute("SELECT * FROM users WHERE company_id=? AND telegram_id=?", (db._current_cid(), tid), "one")
    today = now_tz().date()
    period_start = today.replace(day=1)
    summary = await db.get_staff_period_summary(tid, period_start, today, include_future_schedule=True)
    live = await db.get_current_live_earning(tid)
    shifts = await db.get_shift_rows(tid, period_start, today)
    raw_month = 0
    for r in shifts:
        if r.get('end'):
            start = datetime.combine(r['date'], datetime.strptime(r['start'], '%H:%M').time())
            end_date = r['date'] + timedelta(days=1) if r['end'] < r['start'] else r['date']
            end = datetime.combine(end_date, datetime.strptime(r['end'], '%H:%M').time())
            raw_month += max(0, int((end-start).total_seconds()//60))
    avatar = row["avatar_file_id"] if row and row["avatar_file_id"] else ""
    avatar_html = f"<img class='avatar' src='/uploads/{esc(avatar)}'>" if avatar else f"<div class='avatar'>{esc(profile.get('emoji','🙂'))}</div>"
    rows = "".join(
        f"<tr><td>{r['date'].strftime('%d.%m.%Y')}</td><td>{esc(r.get('shop'))}</td><td>{esc(r.get('start'))}</td><td>{esc(r.get('end') or '—')}</td><td>—</td><td><b>{esc(r.get('worked') or worked_text(r.get('worked_minutes')))}</b></td></tr>"
        for r in reversed(shifts[-20:])
    )
    live_text = "Damda ishda emas"
    if live.get("active"):
        live_text = f"Ishda: {esc(live.get('shop'))}, {esc(live.get('start'))}, hozircha {money(live.get('earned'))} so‘m"
    content = f"""
    <div class="grid cards"><div class="card metric"><div class="label">Bu oy yozilgan</div><div class="value">{summary['hours']}</div><div class='hint'>pullik soat</div></div><div class="card metric"><div class="label">Bu oy real</div><div class="value">{round(raw_month/60,1)}</div><div class='hint'>fakt ishlagan vaqt</div></div><div class="card metric"><div class="label">Oylik</div><div class="value">{money(summary['earnings'])}</div></div><div class="card metric"><div class="label">Status</div><div class="value" style="font-size:18px">{live_text}</div></div></div>
    <div class="split"><div class="card"><div class='row'>{avatar_html}<div><h2>{esc(profile.get('name',''))}</h2><p>Rol: <b>{esc(profile.get('role'))}</b></p><p>Shop: <b>{esc(profile.get('shop') or '—')}</b></p><p>Stavka: <b>{money(profile.get('rate'))}</b> so‘m/soat</p></div></div><form method='post' enctype='multipart/form-data' action='/cabinet/avatar' class='form' style='margin-top:16px'><input class='input' type='file' name='avatar' accept='image/*'><button class='btn secondary'>Rasmni saqlash</button></form></div><div class="card"><h2>Ariza yuborish</h2><form class="grid" method="post" action="/requests/add"><select class="select" name="type"><option value="day_off">Dam olish</option><option value="vacation">Otpusk</option><option value="sick_leave">Bolnichniy</option><option value="other">Boshqa</option></select><textarea name="reason" rows="4" placeholder="Sabab"></textarea><button class="btn">Yuborish</button></form></div></div>
    <div class="card" style="margin-top:18px"><h2>Oxirgi smenalarim</h2>{table(['Sana','Shop','Keldi','Ketdi','Real','Yozildi'], rows, 6)}</div>
    """
    return layout(request, "cabinet", "Shaxsiy kabinet", "O‘z smena, oylik, rasm va arizalaringiz", content)


@app.post("/cabinet/avatar")
async def cabinet_avatar(request: Request, avatar: UploadFile = File(...)):
    if red := require_login(request):
        return red
    u = current_user(request)
    tid = str(u["telegram_id"])
    if tid == "admin_password":
        return redirect("/dashboard")
    raw = await avatar.read()
    if len(raw) > 4 * 1024 * 1024:
        return redirect("/cabinet")
    ext = os.path.splitext(avatar.filename or "avatar.jpg")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    folder = os.path.join(os.path.dirname(db.db_path), "uploads")
    os.makedirs(folder, exist_ok=True)
    name = hashlib.sha256((tid + str(time.time())).encode()).hexdigest()[:16] + ext
    with open(os.path.join(folder, name), "wb") as f:
        f.write(raw)
    db._execute("UPDATE users SET avatar_file_id=?, updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND telegram_id=?", (name, db._current_cid(), tid))
    return redirect("/cabinet")


@app.get("/uploads/{filename}")
async def uploaded_file(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(os.path.dirname(db.db_path), "uploads", safe)
    if not os.path.exists(path):
        return JSONResponse({"error":"not_found"}, status_code=404)
    return FileResponse(path)


@app.get("/my-shifts", response_class=HTMLResponse)
async def my_shifts(request: Request):
    if red := require_login(request):
        return red
    u = current_user(request)
    return await shifts_page(request, telegram_id=str(u["telegram_id"]))


@app.get("/my-schedule", response_class=HTMLResponse)
async def my_schedule(request: Request):
    if red := require_login(request):
        return red
    u = current_user(request)
    return await schedule_page(request, telegram_id=str(u["telegram_id"]))


# -----------------------------
# Admin dashboard
# -----------------------------
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if red := require_admin(request):
        return red
    payload = _dashboard_payload()
    content = f"""
    <div id="dashboard-live">{_render_dashboard(payload)}</div>
    <script>
    function fmt(sec){{sec=Math.max(0, Math.floor(sec)); const h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec%60; return `${{h}}:${{String(m).padStart(2,'0')}}:${{String(s).padStart(2,'0')}}`;}}
    function legacyPaidMinutes(rawMin){{let h=Math.floor(rawMin/60), m=rawMin%60; if(m>=30) h+=1; if(h>=5) h-=1; return Math.max(0,h*60);}}
    function tickLive(){{document.querySelectorAll('.live-item').forEach(el=>{{const st=Number(el.dataset.start||0); const rate=Number(el.dataset.rate||0); if(!st)return; const sec=Math.floor(Date.now()/1000)-st; const paid=legacyPaidMinutes(Math.floor(sec/60)); const live=el.querySelector('[data-live]'); const mon=el.querySelector('[data-money]'); if(live) live.textContent=fmt(sec); if(mon) mon.textContent=new Intl.NumberFormat('ru-RU').format(Math.round(paid/60*rate))+' so‘m';}})}}
    async function softRefresh(){{const y=window.scrollY; try{{const r=await fetch('/api/dashboard/live'); if(!r.ok)return; const html=await r.text(); document.getElementById('dashboard-live').innerHTML=html; tickLive(); window.scrollTo(0,y);}}catch(e){{console.log(e)}}}}
    tickLive(); setInterval(tickLive,1000); setInterval(softRefresh,8000);
    </script>
    """
    return layout(request, "dashboard", "Dashboard", "Live: kechikish, online, real/pullik soat va magazin yuklamasi", content)


@app.get("/api/dashboard/live")
async def api_dashboard_live(request: Request):
    if red := require_admin(request):
        return HTMLResponse("unauthorized", status_code=401)
    return HTMLResponse(_render_dashboard(_dashboard_payload()))


# -----------------------------
# Employees
# -----------------------------
@app.get("/employees", response_class=HTMLResponse)
async def employees(request: Request, q: str = ""):
    if red := require_admin(request):
        return red
    staff = await db.search_staff(q, limit=500)
    rows = "".join(
        f"<tr><td><b>{esc(s.get('Смайлик','🙂'))} {esc(s.get('Имя'))}</b><br><span class='sub'>ID: {esc(s.get('TelegramID'))} · {esc(s.get('Phone'))}</span></td><td>{esc(s.get('Роль'))}</td><td>{esc(s.get('Магазин') or '—')}</td><td>{money(s.get('Ставка'))}</td><td><a class='btn secondary' href='/employees/{esc(s.get('TelegramID'))}'>Ochish</a></td></tr>"
        for s in staff
    )
    content = f"""
    <div class="split"><div class="card"><form class="form" method="get"><input class="input" name="q" value="{esc(q)}" placeholder="Qidirish"><button class="btn">Qidirish</button><a class="btn gray" href="/employees">Tozalash</a></form>{table(['Xodim','Rol','Shop','Stavka',''], rows, 5)}</div>
    <div class="card"><h2>Yangi xodim</h2><form class="grid" method="post" action="/employees/add"><input class="input" name="telegram_id" placeholder="Telegram ID" required><input class="input" name="name" placeholder="Ism" required><input class="input" name="phone" placeholder="Telefon"><select class="select" name="role"><option>staff</option><option>manager</option><option>admin</option></select><select class="select" name="shop">{shop_options('', False)}</select><input class="input" name="rate" placeholder="Stavka"><button class="btn">Qo‘shish</button></form></div></div>
    """
    return layout(request, "employees", "Xodimlar", f"Jami: {len(staff)}", content)


@app.post("/employees/add")
async def add_employee(request: Request, telegram_id: str = Form(...), name: str = Form(...), phone: str = Form(""), role: str = Form("staff"), shop: str = Form(""), rate: str = Form("0")):
    if red := require_admin(request):
        return red
    await db.add_new_staff(telegram_id, name, role, shop)
    await db.update_staff_field(telegram_id, "Phone", phone)
    await db.update_staff_field(telegram_id, "Ставка", rate or "0")
    await db.append_audit_log(current_user(request)["telegram_id"], current_user(request)["role"], "web_employee_add", {"target": telegram_id})
    return redirect("/employees")


@app.get("/employees/{telegram_id}", response_class=HTMLResponse)
async def employee_profile(request: Request, telegram_id: str):
    if red := require_admin(request):
        return red
    profile = await db.get_staff_profile(telegram_id)
    if not profile:
        return layout(request, "employees", "Xodim topilmadi", telegram_id, "<div class='card'>Topilmadi</div>")
    user_row = db._execute("SELECT * FROM users WHERE company_id=? AND telegram_id=?", (db._current_cid(), telegram_id), "one")
    content = f"""
    <div class="split"><div class="card"><h2>{esc(profile.get('emoji'))} {esc(profile.get('name'))}</h2><form class="grid" method="post" action="/employees/{esc(telegram_id)}/update"><input class="input" name="name" value="{esc(profile.get('name'))}"><input class="input" name="phone" value="{esc(user_row['phone'] if user_row else '')}" placeholder="Telefon"><select class="select" name="role"><option {'selected' if profile.get('role')=='staff' else ''}>staff</option><option {'selected' if profile.get('role')=='manager' else ''}>manager</option><option {'selected' if profile.get('role')=='admin' else ''}>admin</option></select><select class="select" name="shop">{shop_options(profile.get('shop','').split(',')[0].strip() if profile.get('shop') else '', False)}</select><input class="input" name="rate" value="{esc(profile.get('rate'))}"><input class="input" name="emoji" value="{esc(profile.get('emoji'))}"><button class="btn">Saqlash</button></form><form method="post" action="/employees/{esc(telegram_id)}/delete" style="margin-top:12px"><button class="btn danger" onclick="return confirm('Deaktivatsiya qilinsinmi?')">Deaktivatsiya</button></form></div>
    <div class="card"><h2>Tezkor harakat</h2><a class="btn secondary" href="/shifts?telegram_id={esc(telegram_id)}">Smenalarini ko‘rish</a><br><br><a class="btn secondary" href="/schedule?telegram_id={esc(telegram_id)}">Grafigini ko‘rish</a></div></div>
    """
    return layout(request, "employees", "Xodim profili", profile.get("name", ""), content)


@app.post("/employees/{telegram_id}/update")
async def update_employee(request: Request, telegram_id: str, name: str = Form(...), phone: str = Form(""), role: str = Form(...), shop: str = Form(""), rate: str = Form("0"), emoji: str = Form("🙂")):
    if red := require_admin(request):
        return red
    await db.update_staff_field(telegram_id, "Имя", name)
    await db.update_staff_field(telegram_id, "Phone", phone)
    await db.update_staff_field(telegram_id, "Роль", role)
    await db.update_staff_field(telegram_id, "Магазин", shop)
    await db.update_staff_field(telegram_id, "Ставка", rate)
    await db.update_staff_field(telegram_id, "Смайлик", emoji)
    await db.append_audit_log(current_user(request)["telegram_id"], current_user(request)["role"], "web_employee_update", {"target": telegram_id})
    return redirect(f"/employees/{urllib.parse.quote(telegram_id)}")


@app.post("/employees/{telegram_id}/delete")
async def delete_employee(request: Request, telegram_id: str):
    if red := require_admin(request):
        return red
    await db.deactivate_staff(telegram_id)
    await db.append_audit_log(current_user(request)["telegram_id"], current_user(request)["role"], "web_employee_deactivate", {"target": telegram_id})
    return redirect("/employees")


# -----------------------------
# Shops
# -----------------------------
@app.get("/shops", response_class=HTMLResponse)
async def shops(request: Request):
    if red := require_admin(request):
        return red
    rows_db = db._execute("SELECT * FROM shops WHERE company_id=? ORDER BY name", (db._current_cid(),), "all")
    rows = "".join(
        f"<tr><td><form class='form' method='post' action='/shops/{r['id']}/update'><input class='input' name='name' value='{esc(r['name'])}'><input class='input' name='lat' value='{esc(r['lat'])}'><input class='input' name='lon' value='{esc(r['lon'])}'><input class='input' name='radius' value='{esc(r['radius_m'])}'><button class='btn'>Saqlash</button></form></td><td><form method='post' action='/shops/{r['id']}/delete'><button class='btn danger'>O‘chirish</button></form></td></tr>"
        for r in rows_db
    )
    content = f"""
    <div class="split"><div class="card">{table(['Shop',''], rows, 2)}</div><div class="card"><h2>Yangi shop</h2><form class="grid" method="post" action="/shops/add"><input class="input" name="name" placeholder="Nom" required><input class="input" name="lat" placeholder="Lat"><input class="input" name="lon" placeholder="Lon"><input class="input" name="radius" value="500"><button class="btn">Qo‘shish</button></form></div></div>
    """
    return layout(request, "shops", "Shoplar", "GPS va radius", content)


@app.post("/shops/add")
async def shop_add(request: Request, name: str = Form(...), lat: str = Form(""), lon: str = Form(""), radius: str = Form("500")):
    if red := require_admin(request):
        return red
    sid = db._ensure_shop_sync(name, float(lat) if lat else None, float(lon) if lon else None)
    if sid:
        db._execute("UPDATE shops SET radius_m=?, active=1 WHERE id=?", (int(radius or 500), sid))
    return redirect("/shops")


@app.post("/shops/{shop_id}/update")
async def shop_update(request: Request, shop_id: int, name: str = Form(...), lat: str = Form(""), lon: str = Form(""), radius: str = Form("500")):
    if red := require_admin(request):
        return red
    db._execute("UPDATE shops SET name=?, lat=?, lon=?, radius_m=?, active=1 WHERE company_id=? AND id=?", (name, float(lat) if lat else None, float(lon) if lon else None, int(radius or 500), db._current_cid(), shop_id))
    return redirect("/shops")


@app.post("/shops/{shop_id}/delete")
async def shop_delete(request: Request, shop_id: int):
    if red := require_admin(request):
        return red
    db._execute("UPDATE shops SET active=0 WHERE company_id=? AND id=?", (db._current_cid(), shop_id))
    return redirect("/shops")


# -----------------------------
# Shifts
# -----------------------------
@app.get("/shifts", response_class=HTMLResponse)
async def shifts_page(request: Request, date_from: str = "", date_to: str = "", shop: str = "", status: str = "", telegram_id: str = ""):
    if current_user(request) and not is_admin(current_user(request)):
        telegram_id = str(current_user(request)["telegram_id"])
    elif red := require_admin(request):
        return red
    today = now_tz().date()
    start = parse_date(date_from, today.replace(day=1))
    end = parse_date(date_to, today)
    shifts = await db.get_shift_rows(telegram_id=telegram_id or None, start_date=start, end_date=end)
    if shop:
        shifts = [r for r in shifts if r.get("shop") == shop]
    if status:
        shifts = [r for r in shifts if r.get("status") == status]
    rows = "".join(
        f"<tr><td>{r['date'].strftime('%d.%m.%Y')}</td><td>{esc(r.get('name'))}<br><span class='sub'>{esc(r.get('telegram_id'))}</span></td><td>{esc(r.get('shop'))}</td><td>{esc(r.get('start'))}</td><td>{esc(r.get('end') or '—')}</td><td>{esc(r.get('worked') or worked_text(r.get('worked_minutes')))}</td><td><span class='pill {'green' if r.get('status')=='closed' else 'amber'}'>{esc(r.get('status'))}</span></td><td><a class='btn secondary' href='/shifts/{r['row']}'>Edit</a></td></tr>"
        for r in reversed(shifts[-700:])
    )
    add_form = "" if not is_admin(current_user(request)) else f"""
    <div class="card"><h2>Qo‘lda smena qo‘shish</h2><form class="grid" method="post" action="/shifts/add"><select class="select" name="telegram_id">{staff_options()}</select><select class="select" name="shop">{shop_options('', False)}</select><input class="input" type="date" name="work_date" value="{today.isoformat()}"><input class="input" type="time" name="start_time" required><input class="input" type="time" name="end_time"><button class="btn">Qo‘shish</button></form></div>
    """
    content = f"""
    <div class="split"><div class="card"><form class="form" method="get"><input class="input" type="date" name="date_from" value="{esc(start.isoformat() if start else '')}"><input class="input" type="date" name="date_to" value="{esc(end.isoformat() if end else '')}"><select class="select" name="shop">{shop_options(shop)}</select><select class="select" name="status"><option value="">Barcha status</option><option value="open" {'selected' if status=='open' else ''}>open</option><option value="closed" {'selected' if status=='closed' else ''}>closed</option></select><button class="btn">Filter</button></form>{table(['Sana','Xodim','Shop','Keldi','Ketdi','Ishladi','Status',''], rows, 8)}</div>{add_form}</div>
    """
    return layout(request, "shifts" if is_admin(current_user(request)) else "my_shifts", "Smenalar", f"{len(shifts)} ta qator", content)


@app.post("/shifts/add")
async def shift_add(request: Request, telegram_id: str = Form(...), shop: str = Form(...), work_date: str = Form(...), start_time: str = Form(...), end_time: str = Form("")):
    if red := require_admin(request):
        return red
    user = await db.get_staff_profile(telegram_id)
    start_at = parse_dt_local(work_date, start_time)
    if not user or not start_at:
        return redirect("/shifts")
    end_at = None
    status = "open"
    paid = 0
    br = 0
    if end_time:
        end_date = start_at.date() + timedelta(days=1) if _time_to_minutes(end_time) < _time_to_minutes(start_time) else start_at.date()
        end_at = datetime.combine(end_date, datetime.strptime(end_time, "%H:%M").time())
        _, paid, br = legacy_paid_minutes(start_at, end_at)
        status = "closed"
    uid = db._ensure_user_sync(telegram_id, user["name"], user["role"], shop)
    sid = db._ensure_shop_sync(shop)
    db._execute("""
        INSERT INTO shifts(company_id,user_id,telegram_id,name,shop_id,shop,business_date,start_at,end_at,status,worked_minutes,break_minutes,source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'web')
    """, (db._current_cid(), uid, telegram_id, user["name"], sid, shop, start_at.date().isoformat(), start_at.isoformat(), end_at.isoformat() if end_at else None, status, paid, br))
    return redirect("/shifts")


@app.get("/shifts/{shift_id}", response_class=HTMLResponse)
async def shift_edit_page(request: Request, shift_id: int):
    if red := require_admin(request):
        return red
    r = await db.get_shift_by_id(shift_id)
    if not r:
        return layout(request, "shifts", "Smena topilmadi", str(shift_id), "<div class='card'>Topilmadi</div>")
    content = f"""
    <div class="card"><h2>Smenani tahrirlash</h2><form class="grid" method="post" action="/shifts/{shift_id}/update"><select class="select" name="telegram_id">{staff_options(str(r['telegram_id']))}</select><select class="select" name="shop">{shop_options(r.get('shop',''), False)}</select><input class="input" type="date" name="work_date" value="{r['date'].isoformat()}"><input class="input" type="time" name="start_time" value="{esc(r.get('start'))}"><input class="input" type="time" name="end_time" value="{esc(r.get('end'))}"><button class="btn">Saqlash</button></form><form style="margin-top:12px" method="post" action="/shifts/{shift_id}/delete"><button class="btn danger">O‘chirish</button></form></div>
    """
    return layout(request, "shifts", "Smena edit", f"#{shift_id}", content)


@app.post("/shifts/{shift_id}/update")
async def shift_update(request: Request, shift_id: int, telegram_id: str = Form(...), shop: str = Form(...), work_date: str = Form(...), start_time: str = Form(...), end_time: str = Form("")):
    if red := require_admin(request):
        return red
    user = await db.get_staff_profile(telegram_id)
    start_at = parse_dt_local(work_date, start_time)
    if not user or not start_at:
        return redirect(f"/shifts/{shift_id}")
    end_at = None
    status = "open"
    paid = 0
    br = 0
    if end_time:
        end_date = start_at.date() + timedelta(days=1) if _time_to_minutes(end_time) < _time_to_minutes(start_time) else start_at.date()
        end_at = datetime.combine(end_date, datetime.strptime(end_time, "%H:%M").time())
        _, paid, br = legacy_paid_minutes(start_at, end_at)
        status = "closed"
    uid = db._ensure_user_sync(telegram_id, user["name"], user["role"], shop)
    sid = db._ensure_shop_sync(shop)
    db._execute("""
        UPDATE shifts SET user_id=?, telegram_id=?, name=?, shop_id=?, shop=?, business_date=?, start_at=?, end_at=?, status=?, worked_minutes=?, break_minutes=?, updated_at=CURRENT_TIMESTAMP
        WHERE company_id=? AND id=?
    """, (uid, telegram_id, user["name"], sid, shop, start_at.date().isoformat(), start_at.isoformat(), end_at.isoformat() if end_at else None, status, paid, br, db._current_cid(), shift_id))
    return redirect("/shifts")


@app.post("/shifts/{shift_id}/delete")
async def shift_delete(request: Request, shift_id: int):
    if red := require_admin(request):
        return red
    await db.delete_shift_row(shift_id)
    return redirect("/shifts")


# -----------------------------
# Schedule
# -----------------------------

async def quick_existing_items(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    dates = sorted({x.get("date") for x in items if x.get("date")})
    for ds in dates:
        d = parse_date(ds)
        if not d:
            continue
        for row in await db.get_schedule_rows(start_date=d, end_date=d):
            result.append({
                "date": row["date"].strftime("%d-%m-%Y"),
                "tid": str(row.get("telegram_id", "")).replace(".0", ""),
                "name": row.get("name", ""),
                "shop": row.get("shop", ""),
                "start": row.get("start", ""),
                "end": row.get("end", ""),
                "kind": "status" if row.get("status") else "shift",
                "status_code": row.get("status"),
            })
    return result


def quick_schedule_form(default_date: date | None = None, text: str = "", preview: str = "", can_save: bool = False, alert: str = "") -> str:
    d = default_date or now_tz().date()
    example = """SD\nDilnavoz 10-16\nJaxongir 16-22\n\nTCM\nIxtiyor 9-14\nMuxabbat 14-22\nIzzat 14-23\n\nFP\nShuxrat 10-17\nShamsiddin 16-22"""
    alert_html = f"<div class='alert ok'>{esc(alert)}</div>" if alert else ""
    save_btn = "<button class='btn' name='action' value='save'>✅ Saqlash</button><button class='btn secondary' name='action' value='save_publish'>📣 Saqlash va guruhga yuborish</button>" if can_save else ""
    return f"""
    {alert_html}
    <div class="split">
      <div class="card"><h2>⚡ Tez grafik import</h2><p class="sub">SD/TCM/FP/NEXT, lotin/kiril, username va ismdagi kichik xatolarni tushunadi. Avval Preview qiling, keyin saqlang.</p><form class="grid" method="post" action="/quick-schedule"><input class="input" type="date" name="default_date" value="{d.isoformat()}"><textarea name="text" rows="16" placeholder="{esc(example)}">{esc(text)}</textarea><div class="row"><button class="btn" name="action" value="preview">Preview</button>{save_btn}</div></form></div>
      <div class="card"><h2>Format namunasi</h2><pre style="white-space:pre-wrap;background:#f8fafc;border-radius:14px;padding:14px">{esc(example)}</pre><p class="sub">Vaqtlar: 10-16, 10:00-16:00, 10.00-16.00. Shoplar: SD, TCM/TSM, FP, NEXT.</p></div>
    </div>
    <div class="card" style="margin-top:18px">{preview or '<h2>Preview shu yerda chiqadi</h2>'}</div>
    """


@app.get("/quick-schedule", response_class=HTMLResponse)
async def quick_schedule_page(request: Request, msg: str = ""):
    if red := require_admin(request):
        return red
    content = quick_schedule_form(default_date=now_tz().date(), alert=msg)
    return layout(request, "quick_schedule", "⚡ Tez grafik", "Copy-paste grafikni avtomatik jadvalga aylantirish", content)


@app.post("/quick-schedule", response_class=HTMLResponse)
async def quick_schedule_post(request: Request, default_date: str = Form(""), text: str = Form(""), action: str = Form("preview")):
    if red := require_admin(request):
        return red
    default_d = parse_date(default_date, now_tz().date()) or now_tz().date()
    default_date_str = default_d.strftime("%d-%m-%Y")
    staff = await db.get_all_staff(force_refresh=True)
    shops = await db.get_shops()
    result = parse_quick_schedule(text, staff, shops, default_date=default_date_str)
    preview = render_quick_schedule_preview(result, for_html=True)

    if action.startswith("save"):
        if not result.get("can_save"):
            content = quick_schedule_form(default_d, text, preview + "<div class='alert err'>Xatolar bor. Avval matnni tuzating.</div>", False)
            return layout(request, "quick_schedule", "⚡ Tez grafik", "Xatolarni tuzatish kerak", content)
        conflicts = find_conflicts(result.get("items") or [], await quick_existing_items(result.get("items") or []))
        if conflicts:
            conflict_html = "<div class='alert err'><b>Konflikt:</b><br>" + "<br>".join(esc(x) for x in conflicts[:8]) + "</div>"
            content = quick_schedule_form(default_d, text, preview + conflict_html, False)
            return layout(request, "quick_schedule", "⚡ Tez grafik", "Konflikt topildi", content)
        ok = await db.append_schedule_rows(result.get("items") or [])
        if not ok:
            content = quick_schedule_form(default_d, text, preview + "<div class='alert err'>Bazaga yozishda xatolik chiqdi.</div>", False)
            return layout(request, "quick_schedule", "⚡ Tez grafik", "Saqlash xatosi", content)
        if action == "save_publish":
            try:
                send_telegram_message(str(config.group_chat_id), render_quick_schedule_preview(result).replace("✅ Saqlashga tayyor.", ""))
            except Exception:
                pass
        return redirect("/quick-schedule?msg=" + urllib.parse.quote(f"Tez grafik saqlandi: {len(result.get('items') or [])} qator"))

    content = quick_schedule_form(default_d, text, preview, bool(result.get("can_save")))
    return layout(request, "quick_schedule", "⚡ Tez grafik", "Preview natijasi", content)


@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request, date_from: str = "", date_to: str = "", shop: str = "", telegram_id: str = ""):
    if current_user(request) and not is_admin(current_user(request)):
        telegram_id = str(current_user(request)["telegram_id"])
    elif red := require_admin(request):
        return red
    today = now_tz().date()
    start = parse_date(date_from, today)
    end = parse_date(date_to, today + timedelta(days=14))
    data = await db.get_schedule_rows(telegram_id=telegram_id or None, start_date=start, end_date=end)
    if shop:
        data = [r for r in data if r.get("shop") == shop]
    rows = "".join(f"<tr><td>{r['date'].strftime('%d.%m.%Y')}</td><td>{esc(r.get('name'))}</td><td>{esc(r.get('shop'))}</td><td>{esc(r.get('start'))}</td><td>{esc(r.get('end'))}</td><td>{esc(r.get('status') or 'shift')}</td><td><a class='btn secondary' href='/schedule/{r['row']}'>Edit</a></td></tr>" for r in data[:1000])
    add_form = "" if not is_admin(current_user(request)) else f"""
    <div class="card"><h2>Grafik qo‘shish</h2><form class="grid" method="post" action="/schedule/add"><select class="select" name="telegram_id">{staff_options()}</select><select class="select" name="shop">{shop_options('', False)}</select><input class="input" type="date" name="work_date" value="{today.isoformat()}"><select class="select" name="kind"><option value="shift">Ish smenasi</option><option value="day_off">Dam olish</option><option value="vacation">Otpusk</option><option value="sick_leave">Bolnichniy</option></select><input class="input" type="time" name="start_time"><input class="input" type="time" name="end_time"><button class="btn">Qo‘shish</button></form></div>
    """
    content = f"<div class='split'><div class='card'><form class='form' method='get'><input class='input' type='date' name='date_from' value='{esc(start.isoformat() if start else '')}'><input class='input' type='date' name='date_to' value='{esc(end.isoformat() if end else '')}'><select class='select' name='shop'>{shop_options(shop)}</select><button class='btn'>Filter</button></form>{table(['Sana','Xodim','Shop','Boshlanish','Tugash','Tur',''], rows, 7)}</div>{add_form}</div>"
    return layout(request, "schedule" if is_admin(current_user(request)) else "my_schedule", "Grafik", f"{len(data)} qator", content)


@app.post("/schedule/add")
async def schedule_add(request: Request, telegram_id: str = Form(...), shop: str = Form(...), work_date: str = Form(...), kind: str = Form("shift"), start_time: str = Form(""), end_time: str = Form("")):
    if red := require_admin(request):
        return red
    user = await db.get_staff_profile(telegram_id)
    item = {"date": work_date, "tid": telegram_id, "name": user["name"] if user else "Xodim", "shop": shop, "kind": kind, "start": start_time, "end": end_time, "status_code": ""}
    if kind != "shift":
        item["status_code"] = kind
        item["start"] = f"STATUS:{kind}"
    await db.append_schedule_rows([item])
    return redirect("/schedule")


@app.get("/schedule/{sched_id}", response_class=HTMLResponse)
async def schedule_edit_page(request: Request, sched_id: int):
    if red := require_admin(request):
        return red
    r = await db.get_schedule_by_id(sched_id)
    if not r:
        return layout(request, "schedule", "Grafik topilmadi", str(sched_id), "<div class='card'>Topilmadi</div>")
    kind = r.get("status") or "shift"
    content = f"""
    <div class="card"><h2>Grafikni tahrirlash</h2><form class="grid" method="post" action="/schedule/{sched_id}/update"><select class="select" name="telegram_id">{staff_options(str(r['telegram_id']))}</select><select class="select" name="shop">{shop_options(r.get('shop',''), False)}</select><input class="input" type="date" name="work_date" value="{r['date'].isoformat()}"><select class="select" name="kind"><option value="shift" {'selected' if kind=='shift' else ''}>Ish smenasi</option><option value="day_off" {'selected' if kind=='day_off' else ''}>Dam olish</option><option value="vacation" {'selected' if kind=='vacation' else ''}>Otpusk</option><option value="sick_leave" {'selected' if kind=='sick_leave' else ''}>Bolnichniy</option></select><input class="input" type="time" name="start_time" value="{esc(r.get('start') if not str(r.get('start')).startswith('STATUS:') else '')}"><input class="input" type="time" name="end_time" value="{esc(r.get('end') if kind=='shift' else '')}"><button class="btn">Saqlash</button></form><form method="post" action="/schedule/{sched_id}/delete" style="margin-top:12px"><button class="btn danger">O‘chirish</button></form></div>
    """
    return layout(request, "schedule", "Grafik edit", f"#{sched_id}", content)


@app.post("/schedule/{sched_id}/update")
async def schedule_update(request: Request, sched_id: int, telegram_id: str = Form(...), shop: str = Form(...), work_date: str = Form(...), kind: str = Form("shift"), start_time: str = Form(""), end_time: str = Form("")):
    if red := require_admin(request):
        return red
    user = await db.get_staff_profile(telegram_id)
    uid = db._ensure_user_sync(telegram_id, user["name"] if user else "Xodim", user["role"] if user else "staff", shop)
    sid = db._ensure_shop_sync(shop)
    if kind == "shift":
        db._execute("UPDATE schedules SET user_id=?,telegram_id=?,name=?,shop_id=?,shop=?,work_date=?,kind='shift',status_code='',start_time=?,end_time=?,updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (uid, telegram_id, user["name"] if user else "Xodim", sid, shop, work_date, start_time, end_time, db._current_cid(), sched_id))
    else:
        db._execute("UPDATE schedules SET user_id=?,telegram_id=?,name=?,shop_id=?,shop=?,work_date=?,kind=?,status_code=?,start_time='',end_time='',updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (uid, telegram_id, user["name"] if user else "Xodim", sid, shop, work_date, kind, kind, db._current_cid(), sched_id))
    return redirect("/schedule")


@app.post("/schedule/{sched_id}/delete")
async def schedule_delete(request: Request, sched_id: int):
    if red := require_admin(request):
        return red
    await db.delete_schedule_row(sched_id)
    return redirect("/schedule")


# -----------------------------
# Salary, requests, inventory, export
# -----------------------------
@app.get("/salary", response_class=HTMLResponse)
async def salary(request: Request, year: int | None = None, month: int | None = None):
    if red := require_admin(request):
        return red
    n = now_tz()
    y = year or n.year
    m = month or n.month
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    rows = ""
    total = 0.0
    for s in await db.get_all_staff(force_refresh=True):
        tid = str(s.get("TelegramID"))
        summary = await db.get_staff_period_summary(tid, start, end)
        total += float(summary.get("earnings") or 0)
        rows += f"<tr><td>{esc(s.get('Имя'))}</td><td>{esc(s.get('Магазин'))}</td><td>{summary['hours']}</td><td>{money(summary['rate'])}</td><td><b>{money(summary['earnings'])}</b></td></tr>"
    month_opts = "".join(f"<option value='{i}' {'selected' if i==m else ''}>{month_name(i)}</option>" for i in range(1, 13))
    content = f"<div class='card'><form class='form'><input class='input' name='year' value='{y}'><select class='select' name='month'>{month_opts}</select><button class='btn'>Hisoblash</button></form><h2>{month_name(m)} {y}: {money(total)} so‘m</h2>{table(['Xodim','Shop','Soat','Stavka','Jami'], rows, 5)}</div>"
    return layout(request, "salary", "Oylik", "Eski botdagi yaxlitlash qoidasi bilan", content)


@app.post("/requests/add")
async def request_add(request: Request, type: str = Form(...), reason: str = Form("")):
    if red := require_login(request):
        return red
    u = current_user(request)
    row = db._execute("SELECT id FROM users WHERE company_id=? AND telegram_id=?", (db._current_cid(), str(u["telegram_id"])), "one")
    db._execute("INSERT INTO employee_requests(company_id,user_id,type,reason,status) VALUES (?,?,?,?, 'pending')", (db._current_cid(), row["id"] if row else None, type, reason))
    return redirect("/cabinet")


@app.get("/requests", response_class=HTMLResponse)
async def requests_page(request: Request):
    if red := require_admin(request):
        return red
    rows_db = db._execute("SELECT er.*, u.full_name FROM employee_requests er LEFT JOIN users u ON u.id=er.user_id WHERE er.company_id=? ORDER BY er.created_at DESC", (db._current_cid(),), "all")
    rows = "".join(f"<tr><td>{esc(r['created_at'])}</td><td>{esc(r['full_name'])}</td><td>{esc(r['type'])}</td><td>{esc(r['reason'])}</td><td>{esc(r['status'])}</td><td><form class='row' method='post' action='/requests/{r['id']}/status'><select class='select' name='status'><option>pending</option><option>approved</option><option>rejected</option></select><button class='btn'>Saqlash</button></form></td></tr>" for r in rows_db)
    return layout(request, "requests", "Arizalar", "Xodimlardan kelgan arizalar", f"<div class='card'>{table(['Sana','Xodim','Tur','Sabab','Status',''], rows, 6)}</div>")


@app.post("/requests/{rid}/status")
async def request_status(request: Request, rid: int, status: str = Form(...)):
    if red := require_admin(request):
        return red
    db._execute("UPDATE employee_requests SET status=?, decided_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?", (status, db._current_cid(), rid))
    return redirect("/requests")


@app.get("/inventory", response_class=HTMLResponse)
async def inventory(request: Request):
    if red := require_admin(request):
        return red
    rows_db = db._execute("SELECT i.*, u.full_name FROM inventory i LEFT JOIN users u ON u.id=i.user_id WHERE i.company_id=? ORDER BY i.id DESC", (db._current_cid(),), "all")
    rows = "".join(f"<tr><td>{esc(r['full_name'])}</td><td>{esc(r['item_name'])}</td><td>{esc(r['quantity'])}</td><td>{esc(r['given_date'])}</td><td>{esc(r['status'])}</td></tr>" for r in rows_db)
    content = f"<div class='split'><div class='card'>{table(['Xodim','Narsa','Soni','Berilgan sana','Status'], rows, 5)}</div><div class='card'><h2>Inventar berish</h2><form class='grid' method='post' action='/inventory/add'><select class='select' name='telegram_id'>{staff_options()}</select><input class='input' name='item_name' placeholder='Narsa nomi'><input class='input' name='quantity' value='1'><input class='input' type='date' name='given_date' value='{now_tz().date().isoformat()}'><button class='btn'>Qo‘shish</button></form></div></div>"
    return layout(request, "inventory", "Inventar", "Xodimlarga biriktirilgan narsalar", content)


@app.post("/inventory/add")
async def inventory_add(request: Request, telegram_id: str = Form(...), item_name: str = Form(...), quantity: int = Form(1), given_date: str = Form("")):
    if red := require_admin(request):
        return red
    row = db._execute("SELECT id FROM users WHERE company_id=? AND telegram_id=?", (db._current_cid(), telegram_id), "one")
    db._execute("INSERT INTO inventory(company_id,user_id,item_name,quantity,given_date,status) VALUES (?,?,?,?,?, 'given')", (db._current_cid(), row["id"] if row else None, item_name, quantity, given_date or now_tz().date().isoformat()))
    return redirect("/inventory")


@app.get("/export", response_class=HTMLResponse)
async def export_page(request: Request, msg: str = ""):
    if red := require_admin(request):
        return red
    n = now_tz()
    alert = f"<div class='alert ok'>{esc(msg)}</div>" if msg else ""
    month_opts = "".join(f"<option value='{i}' {'selected' if i==n.month else ''}>{month_name(i)}</option>" for i in range(1, 13))
    content = f"""
    {alert}<div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr))"><div class="card"><h2>SQLite → Google Sheets</h2><form class="grid" method="post" action="/export/run"><select class="select" name="export_type"><option value="employees">Xodimlar</option><option value="shifts">Smenalar</option><option value="schedule">Grafik</option></select><button class="btn">Export</button></form></div><div class="card"><h2>Oy tabeli</h2><form class="grid" method="post" action="/export/run"><input type="hidden" name="export_type" value="tabel"><input class="input" name="year" value="{n.year}"><select class="select" name="month">{month_opts}</select><select class="select" name="shop">{shop_options('')}</select><button class="btn">Tabel export</button></form></div></div>
    """
    return layout(request, "export", "Export", "Google Sheetsga hisobot chiqarish", content)


@app.post("/export/run")
async def export_run(request: Request, export_type: str = Form(...), year: int = Form(0), month: int = Form(0), shop: str = Form("")):
    if red := require_admin(request):
        return red
    try:
        if export_type == "employees":
            count = await export_employees()
            msg = f"Xodimlar export qilindi: {count}"
        elif export_type == "shifts":
            count = await export_shifts()
            msg = f"Smenalar export qilindi: {count}"
        elif export_type == "schedule":
            count = await export_schedule()
            msg = f"Grafik export qilindi: {count}"
        elif export_type == "tabel":
            count = await export_month_timesheet(None, int(year), int(month), shop or None)
            msg = f"Tabel export qilindi: {count}"
        else:
            msg = "Noto‘g‘ri export turi"
    except Exception as e:
        msg = f"Xato: {e}"
    return redirect(f"/export?msg={urllib.parse.quote(msg)}")


@app.get("/health")
async def health():
    return {"ok": True, "db_path": db.db_path, "company_id": db._current_cid()}


@app.get("/api/stats")
async def api_stats(request: Request):
    if not current_user(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"ok": True, "company_id": db._current_cid(), "db_path": db.db_path}

# AI verification routes are applied from main.py after web_server import.
