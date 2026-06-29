from __future__ import annotations

import html
from datetime import datetime, date
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import config
from database.sqlite_db import db
import web_server as ws

_WEB_PATCHED = False
_SCHEDULE_PATCHED = False


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def money(v: Any) -> str:
    try:
        return f"{round(float(v or 0)):,}".replace(",", " ")
    except Exception:
        return "0"


def now_dt() -> datetime:
    return datetime.now(config.get_timezone_obj()).replace(tzinfo=None)


def parse_dt(v: Any):
    try:
        return datetime.fromisoformat(str(v)).replace(tzinfo=None) if v else None
    except Exception:
        return None


def fmt_dt(v: Any) -> str:
    d = parse_dt(v)
    return d.strftime("%d.%m.%Y %H:%M") if d else "—"


def worked(mins: Any) -> str:
    m = max(0, int(mins or 0))
    return f"{m // 60} ч {m % 60:02d} м"


def paid_from_raw(raw: int) -> int:
    raw = max(0, int(raw or 0))
    h = raw // 60
    m = raw % 60
    if m >= 30:
        h += 1
    if h >= 5:
        h -= 1
    return max(0, h * 60)


def raw_minutes(row) -> int:
    s = parse_dt(row["start_at"])
    e = parse_dt(row["end_at"]) if row["end_at"] else now_dt()
    return max(0, int((e - s).total_seconds() // 60)) if s and e else 0


def rate(tid: str) -> float:
    r = db._execute(
        "SELECT hourly_rate FROM users WHERE company_id=? AND telegram_id=?",
        (db._current_cid(), str(tid)),
        "one",
    )
    try:
        return float(r["hourly_rate"] or 0) if r else 0.0
    except Exception:
        return 0.0


def status(row):
    pl = db._execute(
        """
        SELECT start_time FROM schedules
        WHERE company_id=? AND telegram_id=? AND work_date=? AND kind='shift'
        ORDER BY start_time LIMIT 1
        """,
        (db._current_cid(), str(row["telegram_id"]), str(row["business_date"])),
        "one",
    )
    if not pl or not pl["start_time"]:
        return "Rejasiz", "violet", "—"
    st = parse_dt(row["start_at"])
    try:
        planned = datetime.combine(
            date.fromisoformat(row["business_date"]),
            datetime.strptime(pl["start_time"], "%H:%M").time(),
        )
    except Exception:
        return "Rejasiz", "violet", "—"
    diff = int((st - planned).total_seconds() // 60) if st else 0
    if diff > 5:
        return f"Kechikdi {diff}m", "red", pl["start_time"]
    if diff < -5:
        return f"Erta {abs(diff)}m", "blue", pl["start_time"]
    return "Vaqtida", "green", pl["start_time"]


CSS = r'''
body{margin:0;background:radial-gradient(circle at top left,#dbeafe,#f8fafc 45%,#eef2ff);color:#0f172a;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}.app{display:grid;grid-template-columns:285px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#07142e,#0b1f46);color:white;padding:24px;position:sticky;top:0;height:100vh;overflow:auto;box-shadow:20px 0 60px rgba(15,23,42,.22)}.brand{font-size:24px;font-weight:800;margin-bottom:18px}.mini{font-size:12px;color:#64748b}.side .mini{color:#93c5fd}.nav{display:grid;gap:8px;margin-top:16px}.nav a{color:#dbeafe;text-decoration:none;padding:13px;border-radius:16px;font-weight:700;transition:.18s}.nav a:hover,.nav a.active{background:rgba(255,255,255,.14);transform:translateX(3px)}.main{padding:32px 38px}.h1{font-size:35px;font-weight:800;letter-spacing:-.04em}.sub{color:#64748b;font-weight:650;margin-top:6px}.grid{display:grid;gap:18px}.cards{grid-template-columns:repeat(4,minmax(0,1fr));margin:22px 0}.card{background:rgba(255,255,255,.84);border:1px solid rgba(255,255,255,.9);border-radius:28px;box-shadow:0 24px 70px rgba(15,23,42,.12);padding:22px;backdrop-filter:blur(18px);animation:rise .35s ease}.label{font-weight:750;color:#64748b}.value{font-size:38px;font-weight:800;margin-top:8px}.split{display:grid;grid-template-columns:1.25fr .75fr;gap:18px}.pill{display:inline-flex;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:800;background:#f1f5f9}.green{background:#dcfce7;color:#166534}.red{background:#fee2e2;color:#991b1b}.blue{background:#dbeafe;color:#1d4ed8}.violet{background:#ede9fe;color:#5b21b6}.amber{background:#fef3c7;color:#92400e}.progress{height:12px;background:#e2e8f0;border-radius:99px;overflow:hidden}.progress i{display:block;height:100%;background:linear-gradient(90deg,#06b6d4,#2563eb)}.chart{display:grid;grid-template-columns:120px 1fr 45px;gap:10px;align-items:center;margin:12px 0}.table{width:100%;border-collapse:separate;border-spacing:0 10px}.table th{text-align:left;color:#64748b;font-size:12px;text-transform:uppercase}.table td{background:white;border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;padding:13px}.table td:first-child{border-left:1px solid #e2e8f0;border-radius:16px 0 0 16px}.table td:last-child{border-right:1px solid #e2e8f0;border-radius:0 16px 16px 0}.live-card{background:white;border:1px solid #e2e8f0;border-radius:22px;padding:16px;margin:10px 0}.live-sec{font-size:26px;font-weight:800}.avatar{width:88px;height:88px;border-radius:24px;background:linear-gradient(135deg,#dbeafe,#ede9fe);display:grid;place-items:center;font-size:34px}.profile{display:flex;align-items:center;gap:18px}.mobile{display:none;position:sticky;top:0;background:#07142e;color:white;padding:12px 15px;z-index:20;justify-content:space-between}.hamb{border:0;border-radius:14px;background:#172554;color:white;padding:10px 14px;font-weight:800}.btn{border:0;border-radius:16px;background:#2563eb;color:white;padding:12px 16px;font-weight:750;text-decoration:none;display:inline-flex}b,strong{font-weight:750}.empty{border:1px dashed #cbd5e1;border-radius:20px;padding:22px;text-align:center;color:#64748b}@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}@media(max-width:1000px){.cards{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}@media(max-width:820px){.mobile{display:flex}.app{display:block}.side{display:none;height:auto}.side.open{display:block}.main{padding:18px}.cards{grid-template-columns:1fr}.h1{font-size:28px}.chart{grid-template-columns:90px 1fr 35px}.table td,.table th{font-size:13px}}
'''


def remove_route(app, path: str, method: str = "GET"):
    app.router.routes = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path and method in getattr(r, "methods", set()))
    ]


def page(req: Request, active: str, title: str, sub: str, body: str):
    user = ws.current_user(req) or {"name": "", "role": ""}
    links = [
        ("cabinet", "/cabinet", "👤 Kabinet"),
        ("dashboard", "/dashboard", "🏠 Dashboard"),
        ("verification", "/verification", "🧠 AI tekshiruv"),
        ("checkin", "/checkin", "🟢 Web Keldim"),
        ("checkout", "/checkout", "🔴 Web Ketdim"),
        ("employees", "/employees", "👥 Xodimlar"),
        ("shifts", "/shifts", "🟢 Smenalar"),
        ("schedule", "/schedule", "📅 Grafik"),
        ("quick", "/quick-schedule", "⚡ Tez grafik"),
        ("salary", "/salary", "💰 Oylik"),
        ("requests", "/requests", "📝 Arizalar"),
        ("export", "/export", "📤 Export"),
    ]
    nav = "".join(f'<a class="{"active" if k == active else ""}" href="{h}">{t}</a>' for k, h, t in links)
    side = f'<aside class="side" id="side"><div class="brand">KKB</div><b>{esc(user.get("name"))}</b><div class="mini">{esc(user.get("role"))}</div><div class="nav">{nav}</div><form method="post" action="/logout"><button class="btn" style="margin-top:20px;width:100%;justify-content:center;background:white;color:#0f172a">Chiqish</button></form></aside>'
    js = """<script>addEventListener('beforeunload',()=>sessionStorage.setItem('sy',scrollY));addEventListener('load',()=>{let y=sessionStorage.getItem('sy');if(y)setTimeout(()=>scrollTo(0,+y),40)});</script>"""
    mob = f'<div class="mobile"><b>KKB · {esc(title)}</b><button class="hamb" onclick="document.getElementById(\'side\').classList.toggle(\'open\')">☰ Menu</button></div>'
    return HTMLResponse(f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style><title>{esc(title)}</title></head><body>{mob}<div class="app">{side}<main class="main"><div class="h1">{esc(title)}</div><div class="sub">{sub}</div>{body}<p class="mini">DB: {esc(db.db_path)}</p></main></div>{js}</body></html>')


def bars(data: dict) -> str:
    if not data:
        return '<div class="empty">Maʼlumot yo‘q</div>'
    mx = max([float(v or 0) for v in data.values()] + [1])
    out = ""
    for k, v in data.items():
        pc = int(float(v or 0) / mx * 100) if mx else 0
        val = round(float(v), 1) if isinstance(v, float) else int(v or 0)
        out += f'<div class="chart"><b>{esc(k)}</b><div class="progress"><i style="width:{pc}%"></i></div><span>{val}</span></div>'
    return out


def payload():
    cid = db._current_cid()
    today = now_dt().date()
    start = today.replace(day=1)
    users = db._execute("SELECT * FROM users WHERE company_id=? AND active=1 ORDER BY full_name", (cid,), "all")
    open_rows = db._execute("SELECT * FROM shifts WHERE company_id=? AND status='open' ORDER BY start_at", (cid,), "all")
    month = db._execute("SELECT * FROM shifts WHERE company_id=? AND business_date>=? ORDER BY start_at DESC", (cid, start.isoformat()), "all")
    today_rows = db._execute("SELECT * FROM shifts WHERE company_id=? AND business_date=?", (cid, today.isoformat()), "all")
    paid = sum(int(r["worked_minutes"] or 0) for r in month)
    raw = sum(raw_minutes(r) for r in month if r["end_at"])
    punctual = {"Vaqtida": 0, "Kechikdi": 0, "Erta": 0, "Rejasiz": 0}
    shop_live = {}
    top_emp = {}
    for r in today_rows:
        lab, _, _ = status(r)
        if lab.startswith("Kechikdi"):
            punctual["Kechikdi"] += 1
        elif lab.startswith("Erta"):
            punctual["Erta"] += 1
        elif lab == "Vaqtida":
            punctual["Vaqtida"] += 1
        else:
            punctual["Rejasiz"] += 1
    for r in open_rows:
        shop_live[r["shop"] or "—"] = shop_live.get(r["shop"] or "—", 0) + 1
    for r in month:
        top_emp[r["name"] or r["telegram_id"]] = top_emp.get(r["name"] or r["telegram_id"], 0) + int(r["worked_minutes"] or 0) / 60
    top_emp = dict(sorted(top_emp.items(), key=lambda x: x[1], reverse=True)[:7])
    return users, open_rows, month, paid, raw, punctual, shop_live, top_emp


def live_cards(open_rows):
    if not open_rows:
        return '<div class="empty">Hozir ochiq smena yo‘q</div>'
    out = ""
    for r in open_rows:
        rm = raw_minutes(r)
        pm = paid_from_raw(rm)
        rt = rate(r["telegram_id"])
        st = parse_dt(r["start_at"])
        out += f'<div class="live-card" data-start="{int(st.timestamp()) if st else 0}" data-rate="{rt}"><b>{esc(r["name"])}</b><div class="mini">{esc(r["shop"])} · {fmt_dt(r["start_at"])}</div><div class="live-sec" data-live>{worked(rm)}</div><span class="pill blue" data-money>{money(pm/60*rt)} so‘m</span></div>'
    return out


def dashboard_body():
    users, open_rows, month, paid, raw, punctual, shop_live, top_emp = payload()
    rows = ""
    for r in month[:18]:
        rm = raw_minutes(r)
        pm = int(r["worked_minutes"] or (paid_from_raw(rm) if r["end_at"] else 0))
        lab, cls, plan = status(r)
        rt = rate(r["telegram_id"])
        rows += f'<tr><td><a href="/employees/{esc(r["telegram_id"])}"><b>{esc(r["name"])}</b></a></td><td>{esc(r["shop"])}</td><td>{esc(plan)}</td><td>{fmt_dt(r["start_at"])}</td><td>{fmt_dt(r["end_at"])}</td><td><span class="pill {cls}">{esc(lab)}</span></td><td>Real {worked(rm)}<br><b>Yozildi {worked(pm)}</b></td><td>{money(pm/60*rt)}</td></tr>'
    table = f'<div style="overflow:auto"><table class="table"><tr><th>Xodim</th><th>Shop</th><th>Reja</th><th>Keldi</th><th>Ketdi</th><th>Holat</th><th>Real/yozildi</th><th>Pul</th></tr>{rows}</table></div>'
    js = '<script>function f(s){s=Math.max(0,s|0);let h=Math.floor(s/3600),m=Math.floor((s%3600)/60),x=s%60;return `${h}ч ${String(m).padStart(2,"0")}м ${String(x).padStart(2,"0")}с`}function p(r){let h=Math.floor(r/60),m=r%60;if(m>=30)h++;if(h>=5)h--;return Math.max(0,h*60)}function tick(){document.querySelectorAll(".live-card").forEach(e=>{let st=+e.dataset.start,rt=+e.dataset.rate;if(!st)return;let sec=Math.floor(Date.now()/1000)-st,pm=p(Math.floor(sec/60));e.querySelector("[data-live]").textContent=f(sec);e.querySelector("[data-money]").textContent=new Intl.NumberFormat("ru-RU").format(Math.round(pm/60*rt))+" so‘m"})}tick();setInterval(tick,1000)</script>'
    inner = f'<div class="grid cards"><div class="card"><div class="label">Faol xodimlar</div><div class="value">{len(users)}</div></div><div class="card"><div class="label">Hozir ishda</div><div class="value">{len(open_rows)}</div></div><div class="card"><div class="label">Bu oy yozilgan</div><div class="value">{round(paid/60,1)}</div><div class="mini">real {round(raw/60,1)} soat</div></div><div class="card"><div class="label">Farq</div><div class="value">{round((paid-raw)/60,1)}</div><div class="mini">yozilgan - real</div></div></div><div class="split"><div class="card"><h2>🟢 Online smenalar</h2>{live_cards(open_rows)}</div><div class="card"><h2>🏪 Online shoplar</h2>{bars(shop_live)}<h2>⏰ Punctuality</h2>{bars(punctual)}</div></div><div class="card" style="margin-top:18px"><h2>🏆 Top xodimlar</h2>{bars(top_emp)}</div><div class="card" style="margin-top:18px"><h2>Oxirgi smenalar</h2>{table}</div>'
    return f'<div id="dash-live">{inner}</div>{js}'


def employee_html(tid: str) -> str:
    cid = db._current_cid()
    today = now_dt().date()
    start = today.replace(day=1)
    u = db._execute("SELECT * FROM users WHERE company_id=? AND telegram_id=?", (cid, str(tid)), "one")
    if not u:
        return '<div class="empty">Xodim topilmadi</div>'
    shifts = db._execute("SELECT * FROM shifts WHERE company_id=? AND telegram_id=? AND business_date>=? ORDER BY start_at DESC", (cid, str(tid), start.isoformat()), "all")
    sched = db._execute("SELECT * FROM schedules WHERE company_id=? AND telegram_id=? AND work_date>=? ORDER BY work_date,start_time LIMIT 12", (cid, str(tid), today.isoformat()), "all")
    rt = rate(tid)
    paid = sum(int(r["worked_minutes"] or 0) for r in shifts)
    raw = sum(raw_minutes(r) for r in shifts if r["end_at"])
    late = early = ontime = rej = 0
    rows = ""
    for r in shifts[:24]:
        rm = raw_minutes(r)
        pm = int(r["worked_minutes"] or (paid_from_raw(rm) if r["end_at"] else 0))
        lab, cls, plan = status(r)
        if lab.startswith("Kechikdi"):
            late += 1
        elif lab.startswith("Erta"):
            early += 1
        elif lab == "Vaqtida":
            ontime += 1
        else:
            rej += 1
        rows += f'<tr><td>{esc(r["business_date"])}</td><td>{esc(r["shop"])}</td><td>{esc(plan)}</td><td>{fmt_dt(r["start_at"])}</td><td>{fmt_dt(r["end_at"])}</td><td><span class="pill {cls}">{esc(lab)}</span></td><td>Real {worked(rm)}<br><b>Yozildi {worked(pm)}</b></td><td>{money(pm/60*rt)}</td></tr>'
    sched_rows = "".join(f'<tr><td>{esc(s["work_date"])}</td><td>{esc(s["shop"])}</td><td>{esc(s["start_time"])}</td><td>{esc(s["end_time"])}</td></tr>' for s in sched)
    return f'<div class="card"><div class="profile"><div class="avatar">{esc(u["emoji"] or "👤")}</div><div><h2 style="margin:0;font-size:30px">{esc(u["full_name"])}</h2><div class="mini">{esc(u["role"])} · ID {esc(u["telegram_id"])} · {esc(u["phone"] or "telefon yo‘q")}</div></div></div></div><div class="grid cards"><div class="card"><div class="label">Yozilgan</div><div class="value">{round(paid/60,1)}</div></div><div class="card"><div class="label">Real</div><div class="value">{round(raw/60,1)}</div></div><div class="card"><div class="label">Oylik</div><div class="value">{money(paid/60*rt)}</div></div><div class="card"><div class="label">Kechikish</div><div class="value">{late}</div></div></div><div class="split"><div class="card"><h2>⏰ Punctuality</h2>{bars({"Vaqtida": ontime, "Kechikdi": late, "Erta": early, "Rejasiz": rej})}</div><div class="card"><h2>📅 Yaqin grafik</h2><div style="overflow:auto"><table class="table"><tr><th>Sana</th><th>Shop</th><th>Keldi</th><th>Ketdi</th></tr>{sched_rows}</table></div></div></div><div class="card" style="margin-top:18px"><h2>Smena tarixi</h2><div style="overflow:auto"><table class="table"><tr><th>Sana</th><th>Shop</th><th>Reja</th><th>Keldi</th><th>Ketdi</th><th>Holat</th><th>Real/yozilgan</th><th>Pul</th></tr>{rows}</table></div></div>'


def apply_final_premium_patch(app):
    global _WEB_PATCHED
    if _WEB_PATCHED:
        return
    _WEB_PATCHED = True
    for p in ["/dashboard", "/api/dashboard/live", "/employees", "/employees/{telegram_id}", "/cabinet"]:
        remove_route(app, p)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(req: Request):
        red = ws.require_admin(req)
        if red:
            return red
        return page(req, "dashboard", "Dashboard", "live monitoring, payroll insight va xodim profillari", dashboard_body())

    @app.get("/api/dashboard/live", response_class=HTMLResponse)
    async def api_dashboard(req: Request):
        if not ws.current_user(req):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return HTMLResponse(dashboard_body().split("<script>")[0])

    @app.get("/employees", response_class=HTMLResponse)
    async def employees(req: Request, q: str = ""):
        red = ws.require_admin(req)
        if red:
            return red
        users = db._execute("SELECT * FROM users WHERE company_id=? AND active=1 ORDER BY full_name", (db._current_cid(),), "all")
        if q:
            users = [u for u in users if q.lower() in f"{u['full_name']} {u['phone']} {u['telegram_id']}".lower()]
        cards = "".join(f'<a class="card" style="display:block;text-decoration:none;color:inherit" href="/employees/{esc(u["telegram_id"])}"><div class="profile"><div class="avatar">{esc(u["emoji"] or "👤")}</div><div><h2>{esc(u["full_name"])}</h2><div class="mini">{esc(u["role"])} · {esc(u["phone"] or "telefon yo‘q")}</div></div></div></a>' for u in users)
        body = f'<form method="get" style="margin:20px 0"><input name="q" value="{esc(q)}" placeholder="Xodim qidirish" style="height:46px;border:1px solid #cbd5e1;border-radius:16px;padding:0 14px;min-width:280px"><button class="btn">Qidirish</button></form><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">{cards}</div>'
        return page(req, "employees", "Xodimlar", "har bir xodim uchun alohida sahifa", body)

    @app.get("/employees/{telegram_id}", response_class=HTMLResponse)
    async def employee_detail(req: Request, telegram_id: str):
        red = ws.require_admin(req)
        if red:
            return red
        return page(req, "employees", "Xodim profili", "oylik, real/yozilgan soat, punctuality va smena tarixi", employee_html(telegram_id))

    @app.get("/cabinet", response_class=HTMLResponse)
    async def cabinet(req: Request):
        red = ws.require_login(req)
        if red:
            return red
        u = ws.current_user(req)
        tid = str(u["telegram_id"])
        if tid == "admin_password":
            return RedirectResponse("/dashboard", status_code=303)
        return page(req, "cabinet", "Shaxsiy kabinet", "oylik, real/yozilgan soat va grafik", employee_html(tid))

    print("[final_patch] web applied")


def patch_schedule_messages():
    global _SCHEDULE_PATCHED
    if _SCHEDULE_PATCHED:
        return
    _SCHEDULE_PATCHED = True
    try:
        from services import quick_schedule as qs
        from handlers import admin_schedule as adm
    except Exception as e:
        print(f"[final_patch] schedule skipped: {e}")
        return
    old_preview = qs.render_quick_schedule_preview

    def tmin(v):
        h, m = map(int, str(v).split(":"))
        total = h * 60 + m
        return total + 1440 if h < 8 else total

    def short(shop):
        s = (shop or "").lower()
        if "samarkand" in s or "darvoza" in s:
            return "SD"
        if "tashkent" in s or "city" in s:
            return "TCM"
        if "family" in s:
            return "FP"
        if "next" in s:
            return "NEXT"
        return shop or "SHOP"

    def item_range(it):
        if str(it.get("start", "")).startswith("STATUS:"):
            return "Status"
        return f"{it.get('start')}–{it.get('end')}"

    def group_text(date_str, items):
        shops = {}
        total = 0
        for it in items:
            shops.setdefault(it.get("shop") or "Nomaʼlum", []).append(it)
            try:
                total += max(0, tmin(it["end"]) - tmin(it["start"]))
            except Exception:
                pass
        text = f"📅 KELDI-KETDI · {date_str}\n\n"
        for shop, lst in shops.items():
            text += f"🏪 {short(shop)} — {shop}\n"
            for it in sorted(lst, key=lambda x: x.get("start") or "99:99"):
                text += f"   {item_range(it):<13} {it.get('name') or it.get('tid')}\n"
            text += "\n"
        return (text + f"👥 Jami xodim: {len(items)}\n🕒 Jami reja: {round(total/60,1)} soat\n✅ Grafik saqlandi").strip()

    def preview(result, for_html=False):
        if for_html:
            return old_preview(result, for_html=True)
        text = group_text(result.get("date") or "sana yo‘q", result.get("items") or [])
        if result.get("errors"):
            text += "\n\n❌ Xatolar:\n" + "\n".join(f"• {x}" for x in result["errors"])
        if result.get("unresolved"):
            text += "\n\n❌ Aniqlanmagan:\n" + "\n".join(f"• {x.get('raw')} — {x.get('reason')}" for x in result["unresolved"][:10])
        if result.get("warnings"):
            text += "\n\n⚠️ Taxminlar:\n" + "\n".join(f"• {x}" for x in result["warnings"][:10])
        text += "\n\n✅ Saqlashga tayyor." if result.get("can_save") else "\n\nMatnni tuzatib qayta yuboring."
        return text.strip()

    qs.render_quick_schedule_preview = preview
    adm.render_quick_schedule_preview = preview
    adm._group_graphic_text = group_text
    print("[final_patch] schedule messages applied")
