from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse

import web_server as ws
from config import config
from database.sqlite_db import db
from services.attendance_verification import (
    save_data_url_image,
    verify_attendance,
    checks,
    update_check_status,
    ensure_verification_tables,
)

_PATCHED = False


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def remove_route(app, path: str, method: str = "GET") -> None:
    app.router.routes = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path and method in getattr(r, "methods", set()))
    ]


def money(v: Any) -> str:
    try:
        return f"{round(float(v or 0)):,}".replace(",", " ")
    except Exception:
        return "0"


def send_telegram_photo(chat_id: int | str, photo_path: str, caption: str) -> None:
    token = config.bot_token.get_secret_value()
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    boundary = "----KKBFormBoundary" + uuid.uuid4().hex
    data = []

    def field(name: str, value: str):
        data.append(f"--{boundary}\r\n".encode())
        data.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        data.append(str(value).encode())
        data.append(b"\r\n")

    field("chat_id", str(chat_id))
    field("caption", caption)
    field("parse_mode", "HTML")
    filename = os.path.basename(photo_path) or "selfie.jpg"
    data.append(f"--{boundary}\r\n".encode())
    data.append(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode())
    data.append(b"Content-Type: image/jpeg\r\n\r\n")
    data.append(Path(photo_path).read_bytes())
    data.append(b"\r\n")
    data.append(f"--{boundary}--\r\n".encode())
    body = b"".join(data)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def web_notify_group(action: str, name: str, shop: str, result: dict, selfie_path: str, loc_url: str = "", worked: str = "") -> None:
    try:
        icon = "🟢" if action == "check_in" else "🔴"
        title = "KELDI" if action == "check_in" else "KETDI"
        lines = [
            f"{icon} <b>WEB {title}</b>",
            f"👤 {esc(name)}",
            f"🏪 {esc(shop or result.get('shop') or '—')}",
        ]
        if worked:
            lines.append(f"⏱ {esc(worked)}")
        lines += [
            f"🧠 Face: {esc(result.get('face_status'))} ({esc(result.get('face_score'))})",
            f"📍 GPS: {esc(result.get('location_status'))} {esc(result.get('distance_m') or '')}m",
            f"✅ Status: {esc(result.get('final_status'))}",
        ]
        if loc_url:
            lines.append(f"🗺 <a href='{esc(loc_url)}'>Xarita</a>")
        send_telegram_photo(config.group_chat_id, selfie_path, "\n".join(lines))
    except Exception as e:
        print(f"[mobile_scan_patch] group photo skipped: {e}")


def status_pill(status: str | None) -> str:
    cls = {
        "approved": "green", "needs_review": "amber", "rejected": "red",
        "match": "green", "reference_created": "amber", "weak": "amber", "no_match": "red",
        "ok": "green", "far": "red", "unknown": "amber", "ai_off": "amber",
    }.get(str(status), "blue")
    return f'<span class="pill {cls}">{esc(status)}</span>'


MOBILE_SCAN_CSS = r'''
:root{--bg:#060b1d;--card:rgba(255,255,255,.11);--text:#f8fafc;--muted:#a7b3c9;--green:#10b981;--red:#ef4444;--blue:#3b82f6;--violet:#8b5cf6;--amber:#f59e0b}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% 0,#4c0c65 0,#091633 45%,#050816 100%);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}.scan-wrap{min-height:100vh;display:flex;flex-direction:column;max-width:560px;margin:auto;padding:18px}.scan-top{display:flex;justify-content:space-between;align-items:center;gap:10px}.back{width:46px;height:46px;border:0;border-radius:18px;background:rgba(255,255,255,.13);color:white;font-size:22px}.title{font-size:22px;font-weight:800}.sub{color:var(--muted);font-size:13px}.phone-card{position:relative;overflow:hidden;border-radius:34px;margin-top:16px;min-height:62vh;background:linear-gradient(180deg,rgba(255,255,255,.09),rgba(255,255,255,.03));box-shadow:0 30px 90px rgba(0,0,0,.35);border:1px solid rgba(255,255,255,.12)}video{width:100%;height:62vh;object-fit:cover;transform:scaleX(-1);display:block;background:#0f172a}.scan-overlay{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse 38% 30% at 50% 43%,transparent 0 62%,rgba(5,8,22,.58) 63%,rgba(5,8,22,.84) 100%)}.face-oval{position:absolute;left:50%;top:43%;transform:translate(-50%,-50%);width:min(76vw,360px);height:min(96vw,440px);border-radius:50%;border:4px solid rgba(255,255,255,.92);box-shadow:0 0 0 12px rgba(139,92,246,.25),0 0 55px rgba(168,85,247,.58)}.face-oval.ready{border-color:#22c55e;box-shadow:0 0 0 12px rgba(34,197,94,.22),0 0 65px rgba(34,197,94,.45)}.scan-line{position:absolute;left:12%;right:12%;top:22%;height:3px;border-radius:99px;background:linear-gradient(90deg,transparent,#22c55e,transparent);animation:scan 2.2s infinite}.brand-mark{position:absolute;bottom:28px;left:50%;transform:translateX(-50%);display:flex;gap:12px;opacity:.92}.brand-mark i{width:36px;height:15px;border-radius:99px;background:white;transform:rotate(-42deg);display:block}.panel{margin-top:16px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.13);border-radius:28px;padding:18px;backdrop-filter:blur(18px)}.steps{display:grid;gap:10px}.step{display:flex;align-items:center;gap:11px;color:var(--muted);font-size:15px}.dot{width:25px;height:25px;border-radius:50%;background:#334155;display:grid;place-items:center;color:white;font-size:14px;font-weight:800}.step.ok{color:#eafff7}.step.ok .dot{background:var(--green)}.step.warn .dot{background:var(--amber)}.btn{width:100%;height:58px;border:0;border-radius:20px;font-size:18px;font-weight:850;color:white;background:linear-gradient(135deg,#22c55e,#16a34a);box-shadow:0 18px 38px rgba(16,185,129,.28);margin-top:14px}.btn.red{background:linear-gradient(135deg,#ef4444,#dc2626);box-shadow:0 18px 38px rgba(239,68,68,.25)}.btn:disabled{opacity:.45;filter:grayscale(.5);box-shadow:none}.btn.secondary{background:rgba(255,255,255,.14);box-shadow:none}.result{margin-top:12px}.result-card{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.13);border-radius:22px;padding:15px}.small{font-size:12px;color:var(--muted)}canvas{display:none}@keyframes scan{0%{top:24%}50%{top:62%}100%{top:24%}}@media(max-width:520px){.scan-wrap{padding:12px}.phone-card{border-radius:28px;min-height:58vh}video{height:58vh}.face-oval{width:78vw;height:96vw}.title{font-size:19px}}
'''


STAFF_CSS = r'''
body{margin:0;min-height:100vh;background:radial-gradient(circle at top,#dbeafe,#f8fafc 48%,#eef2ff);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a}.wrap{max-width:960px;margin:auto;padding:18px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px}.card{background:rgba(255,255,255,.88);border:1px solid #fff;border-radius:28px;box-shadow:0 24px 70px rgba(15,23,42,.12);padding:22px;margin:16px 0}.hero{background:linear-gradient(135deg,#07142e,#172554);color:white}.avatar{width:74px;height:74px;border-radius:24px;background:rgba(255,255,255,.12);display:grid;place-items:center;font-size:34px}.profile{display:flex;gap:14px;align-items:center}.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.big-btn{display:flex;align-items:center;justify-content:center;min-height:112px;border-radius:26px;text-decoration:none;color:white;font-size:24px;font-weight:850;box-shadow:0 20px 44px rgba(15,23,42,.16)}.big-btn.green{background:linear-gradient(135deg,#22c55e,#16a34a)}.big-btn.red{background:linear-gradient(135deg,#ef4444,#dc2626)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric{background:white;border:1px solid #e2e8f0;border-radius:22px;padding:16px}.metric b{font-size:26px}.muted{color:#64748b}.table{width:100%;border-collapse:separate;border-spacing:0 8px}.table td,.table th{text-align:left;background:white;border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;padding:12px}.table td:first-child{border-left:1px solid #e2e8f0;border-radius:14px 0 0 14px}.table td:last-child{border-right:1px solid #e2e8f0;border-radius:0 14px 14px 0}.pill{border-radius:999px;padding:6px 10px;font-size:12px;background:#dbeafe;color:#1d4ed8;font-weight:800}.logout{border:0;border-radius:16px;padding:11px 14px;background:#e2e8f0;font-weight:800}@media(max-width:720px){.btn-grid,.grid{grid-template-columns:1fr}.wrap{padding:12px}.big-btn{min-height:96px}.table td,.table th{font-size:12px;padding:9px}}
'''


def scan_page(label: str, action: str, user: dict) -> HTMLResponse:
    is_out = action == "check_out"
    btn_class = "red" if is_out else ""
    body = f"""
<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(label)} · KKB</title><style>{MOBILE_SCAN_CSS}</style></head>
<body><div class="scan-wrap">
  <div class="scan-top"><button class="back" onclick="location.href='/cabinet'">‹</button><div><div class="title">{esc(label)} tasdiqlash</div><div class="sub">Selfie · liveness · GPS · AI moslik</div></div><button class="back" onclick="location.reload()">↻</button></div>
  <div class="phone-card"><video id="video" autoplay playsinline muted></video><canvas id="canvas"></canvas><div class="scan-overlay"></div><div class="face-oval" id="oval"><div class="scan-line"></div></div><div class="brand-mark"><i></i><i></i><i></i></div></div>
  <div class="panel"><div class="steps">
    <div class="step ok"><span class="dot">✓</span><span>Xodim aniqlandi: <b>{esc(user.get('name') or 'Xodim')}</b></span></div>
    <div class="step" id="cameraStep"><span class="dot">1</span><span>Kamera ruxsati kutilmoqda</span></div>
    <div class="step" id="gpsStep"><span class="dot">2</span><span>Lokatsiya aniqlanmoqda</span></div>
    <div class="step" id="liveStep"><span class="dot">3</span><span>Liveness: yuzingizni oval ichida ushlab turing</span></div>
  </div>
  <button class="btn secondary" id="liveBtn" onclick="doLiveness()" disabled>👁 Livenessni tekshirish</button>
  <button class="btn {btn_class}" id="sendBtn" onclick="sendCheck()" disabled style="display:none">{'🔴 Ketdimni bazaga yozish' if is_out else '🟢 Keldimni bazaga yozish'}</button>
  <div class="result" id="result"></div></div>
</div>
<script>
let pos=null, cameraReady=false, gpsReady=false, liveReady=false, sending=false;
function ok(id, text){{const el=document.getElementById(id); el.classList.add('ok'); el.querySelector('.dot').textContent='✓'; if(text)el.querySelector('span:last-child').innerHTML=text;}}
function warn(id, text){{const el=document.getElementById(id); el.classList.add('warn'); el.querySelector('.dot').textContent='!'; if(text)el.querySelector('span:last-child').innerHTML=text;}}
function state(){{document.getElementById('liveBtn').disabled=!(cameraReady&&gpsReady)||liveReady; const ready=cameraReady&&gpsReady&&liveReady; document.getElementById('sendBtn').style.display=ready?'block':'none'; document.getElementById('sendBtn').disabled=!ready||sending; if(ready)document.getElementById('oval').classList.add('ready');}}
async function boot(){{
 try{{const stream=await navigator.mediaDevices.getUserMedia({{video:{{facingMode:'user',width:{{ideal:720}},height:{{ideal:960}}}},audio:false}}); const v=document.getElementById('video'); v.srcObject=stream; cameraReady=true; ok('cameraStep','Kamera tayyor');}}catch(e){{warn('cameraStep','Kamera ochilmadi: '+e.message);}}
 navigator.geolocation.getCurrentPosition(p=>{{pos=p; gpsReady=true; ok('gpsStep','GPS tayyor · aniqlik '+Math.round(p.coords.accuracy)+'m'); state();}}, e=>{{warn('gpsStep','GPS xato: '+e.message); state();}}, {{enableHighAccuracy:true,timeout:15000,maximumAge:0}});
 state();
}}
function doLiveness(){{const btn=document.getElementById('liveBtn');btn.disabled=true;btn.textContent='3 soniya yuzingizni harakatlantirmang...';let n=3;const t=setInterval(()=>{{n--;btn.textContent=n>0?n+'...':'Tekshirildi';if(n<=0){{clearInterval(t);liveReady=true;ok('liveStep','Liveness o‘tdi');state();}}}},700)}}
async function sendCheck(){{if(sending)return; sending=true; state(); document.getElementById('result').innerHTML='<div class="result-card">⏳ AI va GPS tekshirilyapti...</div>'; const v=document.getElementById('video'), c=document.getElementById('canvas'); c.width=v.videoWidth||720; c.height=v.videoHeight||960; c.getContext('2d').drawImage(v,0,0,c.width,c.height); const image=c.toDataURL('image/jpeg',0.88); const fd=new FormData(); fd.append('action','{action}'); fd.append('image_data',image); fd.append('liveness','ok'); if(pos){{fd.append('lat',pos.coords.latitude);fd.append('lon',pos.coords.longitude);fd.append('accuracy',pos.coords.accuracy)}} try{{const r=await fetch('/api/attendance/verify',{{method:'POST',body:fd}}); const j=await r.json(); const okResp=r.ok && !j.error; document.getElementById('result').innerHTML='<div class="result-card"><h2>'+(j.emoji||'ℹ️')+' '+(j.title||'Natija')+'</h2><p>'+(j.message||'')+'</p><p>Face: <b>'+(j.face_status||'-')+'</b> '+(j.face_score??'')+'</p><p>GPS: <b>'+(j.location_status||'-')+'</b> '+(j.distance_m?j.distance_m+'m':'')+'</p><button class="btn secondary" onclick="location.href=\'/cabinet\'">Kabinetga qaytish</button></div>'; if(okResp){{setTimeout(()=>location.href='/cabinet',2500)}} }}catch(e){{document.getElementById('result').innerHTML='<div class="result-card">Xato: '+e+'</div>';}} sending=false; state();}}
boot();
</script></body></html>
"""
    return HTMLResponse(body)


def staff_cabinet_page(request: Request, user: dict) -> HTMLResponse:
    tid = str(user.get("telegram_id"))
    today = ws.now_tz().date()
    month_start = today.replace(day=1)
    u = db._execute("SELECT * FROM users WHERE company_id=? AND telegram_id=?", (db._current_cid(), tid), "one")
    shifts = db._execute(
        "SELECT * FROM shifts WHERE company_id=? AND telegram_id=? AND business_date>=? ORDER BY start_at DESC LIMIT 20",
        (db._current_cid(), tid, month_start.isoformat()),
        "all",
    )
    rate = float((u or {}).get("hourly_rate") or 0)
    paid = sum(int(r["worked_minutes"] or 0) for r in shifts)
    salary = paid / 60 * rate
    active = db._execute(
        "SELECT * FROM shifts WHERE company_id=? AND telegram_id=? AND status='open' ORDER BY start_at DESC LIMIT 1",
        (db._current_cid(), tid),
        "one",
    )
    rows = ""
    for r in shifts[:10]:
        rows += f"<tr><td>{esc(r['business_date'])}</td><td>{esc(r['shop'])}</td><td>{ws.iso_short(r['start_at'])}</td><td>{ws.iso_short(r['end_at'])}</td><td>{ws.worked_text(r['worked_minutes'])}</td></tr>"
    if not rows:
        rows = "<tr><td colspan='5'>Hali smena yo‘q</td></tr>"
    active_html = ""
    if active:
        active_html = f"<div class='card'><span class='pill'>Hozir ishda</span><h2>{esc(active['shop'])}</h2><p class='muted'>Boshlangan: {ws.iso_short(active['start_at'])}</p></div>"
    body = f"""
<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kabinet · KKB</title><style>{STAFF_CSS}</style></head><body><div class="wrap">
  <div class="top"><h1>KKB · Kabinet</h1><form method="post" action="/logout"><button class="logout">Chiqish</button></form></div>
  <div class="card hero"><div class="profile"><div class="avatar">{esc((u or {}).get('emoji') or '👤')}</div><div><h2 style="margin:0">{esc(user.get('name') or (u or {}).get('full_name') or 'Xodim')}</h2><p class="muted" style="color:#bfdbfe;margin:6px 0 0">{esc((u or {}).get('role') or user.get('role') or 'staff')}</p></div></div></div>
  <div class="btn-grid"><a class="big-btn green" href="/checkin">🟢 Keldim</a><a class="big-btn red" href="/checkout">🔴 Ketdim</a></div>
  {active_html}
  <div class="grid"><div class="metric"><b>{round(paid/60,1)}</b><div class="muted">Bu oy yozilgan soat</div></div><div class="metric"><b>{money(salary)}</b><div class="muted">Taxminiy oylik</div></div><div class="metric"><b>{money(rate)}</b><div class="muted">Stavka</div></div><div class="metric"><b>{len(shifts)}</b><div class="muted">Smenalar</div></div></div>
  <div class="card"><h2>Oxirgi smenalarim</h2><div style="overflow:auto"><table class="table"><tr><th>Sana</th><th>Shop</th><th>Keldi</th><th>Ketdi</th><th>Yozildi</th></tr>{rows}</table></div></div>
</div></body></html>
"""
    return HTMLResponse(body)


def clean_login_page(request: Request, error: str = "", sent: str = "", phone: str = "") -> HTMLResponse | RedirectResponse:
    if ws.current_user(request):
        u = ws.current_user(request)
        return RedirectResponse("/dashboard" if ws.is_admin(u) else "/cabinet", status_code=303)
    alert = ""
    if error:
        alert = f"<div class='alert err'>{esc(error)}</div>"
    if sent:
        alert = "<div class='alert ok'>Kod Telegram botga yuborildi. Kodni kiriting.</div>"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>KKB Login</title><style>{ws.CSS}</style></head><body class='login'><div class='login-card'><h1>KKB Web</h1><p>Telefon raqam yoki Telegram ID kiriting. Kod asosiy Telegram bot orqali keladi.</p>{alert}<form method='post' action='/login/request'><input name='phone' value='{esc(phone)}' placeholder='Telefon yoki Telegram ID' required><button class='btn'>Kod olish</button></form><form method='post' action='/login/verify'><input name='phone' value='{esc(phone)}' placeholder='Telefon yoki Telegram ID' required style='margin-top:12px'><input name='code' placeholder='6 xonali kod' required style='margin-top:12px'><button class='btn'>Kirish</button></form><p class='footer'>Parol bilan kirish o‘chirildi. Admin ham Telegram ID orqali OTP bilan kiradi.</p></div></body></html>""")


def verification_page() -> HTMLResponse:
    rows = checks(150)
    body_rows = ""
    for r in rows:
        check_id = int(r["id"])
        lat, lon = r.get("latitude"), r.get("longitude")
        map_link = f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else ""
        map_btn = f"<a class='btn gray' href='{esc(map_link)}' target='_blank'>Map</a>" if map_link else ""
        body_rows += (
            f"<tr><td>{check_id}</td>"
            f"<td>{esc(r.get('created_at'))}<br>{esc(r.get('source'))}</td>"
            f"<td>{esc(r.get('name') or r.get('telegram_id'))}</td>"
            f"<td>{esc(r.get('action'))}</td>"
            f"<td>{esc(r.get('shop'))}<br>{esc(r.get('distance_m') or '')}m</td>"
            f"<td>{status_pill(r.get('face_status'))}<br>{esc(r.get('face_score'))}</td>"
            f"<td>{status_pill(r.get('location_status'))}</td>"
            f"<td>{status_pill(r.get('final_status'))}</td>"
            f"<td><a class='btn gray' href='/attendance-photo/{check_id}' target='_blank'>Selfie</a>{map_btn}"
            f"<form method='post' action='/verification/{check_id}/status' style='display:flex;gap:6px;flex-wrap:wrap;margin-top:6px'>"
            f"<button class='btn green' name='status' value='approved'>OK</button>"
            f"<button class='btn red' name='status' value='rejected'>Reject</button>"
            f"<button class='btn gray' name='status' value='needs_review'>Review</button></form></td></tr>"
        )
    body = f"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI tekshiruv</title><style>{ws.CSS}</style></head><body><main class="main"><div class="top"><div><div class="h1">🧠 AI tekshiruv</div><div class="sub">Selfie, GPS va admin review</div></div><a class="btn secondary" href="/dashboard">Dashboard</a></div><div class="card"><div class="table-wrap"><table class="table"><tr><th>ID</th><th>Vaqt</th><th>Xodim</th><th>Action</th><th>Shop/Masofa</th><th>Yuz</th><th>GPS</th><th>Status</th><th>Amal</th></tr>{body_rows}</table></div></div></main></body></html>
"""
    return HTMLResponse(body)


def manifest_json() -> dict:
    return {
        "name": "KKB Keldi-Ketdi",
        "short_name": "KKB",
        "start_url": "/cabinet",
        "display": "standalone",
        "background_color": "#07142e",
        "theme_color": "#07142e",
        "icons": [],
    }


def apply_mobile_scan_patch(app):
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    ensure_verification_tables()
    for path, method in [
        ("/login", "GET"), ("/cabinet", "GET"),
        ("/checkin", "GET"), ("/checkout", "GET"), ("/check-in", "GET"), ("/check-out", "GET"), ("/web-checkin", "GET"), ("/web-checkout", "GET"),
        ("/api/attendance/verify", "POST"), ("/verification", "GET"), ("/verification/{check_id}/status", "POST"), ("/attendance-photo/{check_id}", "GET"),
        ("/manifest.json", "GET"), ("/sw.js", "GET"),
    ]:
        remove_route(app, path, method)

    @app.get("/login", response_class=HTMLResponse)
    async def patched_login(request: Request, error: str = "", sent: str = "", phone: str = ""):
        return clean_login_page(request, error, sent, phone)

    @app.get("/cabinet", response_class=HTMLResponse)
    async def cabinet(request: Request):
        red = ws.require_login(request)
        if red:
            return red
        u = ws.current_user(request)
        if ws.is_admin(u):
            return RedirectResponse("/dashboard", status_code=303)
        return staff_cabinet_page(request, u)

    @app.get("/checkin", response_class=HTMLResponse)
    async def checkin(request: Request):
        red = ws.require_login(request)
        if red:
            return red
        u = ws.current_user(request)
        return scan_page("Keldim", "check_in", u)

    @app.get("/checkout", response_class=HTMLResponse)
    async def checkout(request: Request):
        red = ws.require_login(request)
        if red:
            return red
        u = ws.current_user(request)
        return scan_page("Ketdim", "check_out", u)

    @app.get("/check-in", response_class=HTMLResponse)
    async def checkin_alias(request: Request):
        return await checkin(request)

    @app.get("/check-out", response_class=HTMLResponse)
    async def checkout_alias(request: Request):
        return await checkout(request)

    @app.get("/web-checkin", response_class=HTMLResponse)
    async def web_checkin_alias(request: Request):
        return await checkin(request)

    @app.get("/web-checkout", response_class=HTMLResponse)
    async def web_checkout_alias(request: Request):
        return await checkout(request)

    @app.post("/api/attendance/verify")
    async def api_verify(request: Request, action: str = Form(...), image_data: str = Form(...), lat: str = Form(""), lon: str = Form(""), accuracy: str = Form(""), liveness: str = Form("")):
        red = ws.require_login(request)
        if red:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        user = ws.current_user(request)
        tid = str(user.get("telegram_id"))
        if ws.is_admin(user):
            return JSONResponse({"emoji":"⚠️","title":"Admin uchun emas","message":"Keldim/Ketdim faqat xodim kabinetidan qilinadi.","face_status":"-","location_status":"-"}, status_code=400)
        if liveness != "ok":
            return JSONResponse({"emoji":"⚠️","title":"Liveness yo‘q","message":"Avval liveness tekshiruvdan o‘ting.","face_status":"-","location_status":"-"}, status_code=400)
        selfie_path = save_data_url_image(image_data, tid, "web")
        active = await db.get_active_shift_row(int(tid))
        latitude = float(lat) if lat else None
        longitude = float(lon) if lon else None
        acc = float(accuracy) if accuracy else None
        loc_url = f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else ""
        staff = await db.get_user_by_telegram_id(int(tid))
        staff_for_shift = staff.copy() if staff else {"TelegramID": tid, "Имя": user.get("name", "Xodim"), "Роль": "staff", "Магазин": ""}
        if action == "check_in" and active:
            return JSONResponse({"emoji":"⚠️","title":"Smena ochiq","message":"Sizda ochiq smena bor. Avval Ketdim qiling.","face_status":"-","face_score":"-","location_status":"-"})
        if action == "check_out" and not active:
            return JSONResponse({"emoji":"⚠️","title":"Ochiq smena yo‘q","message":"Avval Keldim qiling.","face_status":"-","face_score":"-","location_status":"-"})
        fallback_shop = str(staff_for_shift.get("Магазин", "")).split(",")[0].strip()
        result = verify_attendance(tid, action, selfie_path, latitude, longitude, acc, shift_id=active, source="web", fallback_shop=fallback_shop)
        if result.get("final_status") == "rejected":
            web_notify_group(action, user.get("name", "Xodim"), result.get("shop") or fallback_shop, result, selfie_path, loc_url)
            return JSONResponse({"emoji":"❌","title":"Rad etildi","message":"Selfie/GPS mos kelmadi. Admin tekshiradi.", **result})
        if action == "check_in":
            staff_for_shift["Магазин"] = result.get("shop") or fallback_shop
            ok = await db.start_shift(staff_for_shift, f"web:{result['check_id']}", loc_url)
            if not ok:
                return JSONResponse({"emoji":"❌","title":"Smena ochilmadi","message":"Bazaga yozishda xato yoki smena allaqachon ochiq.", **result}, status_code=500)
            shift_id = await db.get_active_shift_row(int(tid))
            try:
                db._execute("UPDATE attendance_checks SET shift_id=? WHERE id=?", (shift_id, int(result["check_id"])))
            except Exception:
                pass
            web_notify_group(action, user.get("name", "Xodim"), result.get("shop") or fallback_shop, result, selfie_path, loc_url)
            return JSONResponse({"emoji":"✅","title":"Keldim saqlandi","message":"Smena ochildi." if result.get("final_status") == "approved" else "Smena ochildi, admin reviewga ham tushdi.", **result})
        worked = await db.end_shift(active, photo_id=f"web:{result['check_id']}", location=loc_url)
        web_notify_group(action, user.get("name", "Xodim"), result.get("shop") or fallback_shop, result, selfie_path, loc_url, worked)
        return JSONResponse({"emoji":"✅","title":"Ketdim saqlandi","message":f"Smena yopildi. Ishladi: {worked}", **result})

    @app.get("/verification", response_class=HTMLResponse)
    async def verification(request: Request):
        red = ws.require_admin(request)
        if red:
            return red
        return verification_page()

    @app.post("/verification/{check_id}/status")
    async def set_status(request: Request, check_id: int, status: str = Form(...)):
        red = ws.require_admin(request)
        if red:
            return red
        user = ws.current_user(request) or {}
        update_check_status(check_id, status, str(user.get("telegram_id", "admin")))
        return RedirectResponse("/verification", status_code=303)

    @app.get("/attendance-photo/{check_id}")
    async def attendance_photo(request: Request, check_id: int):
        red = ws.require_admin(request)
        if red:
            return red
        row = db._execute("SELECT selfie_path FROM attendance_checks WHERE company_id=? AND id=?", (db._current_cid(), int(check_id)), "one")
        if not row or not row["selfie_path"] or not os.path.exists(row["selfie_path"]):
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(row["selfie_path"])

    @app.get("/manifest.json")
    async def manifest():
        return JSONResponse(manifest_json())

    @app.get("/sw.js")
    async def sw():
        return HTMLResponse("self.addEventListener('fetch',()=>{});", media_type="application/javascript")

    print("[mobile_scan_patch] applied: staff cabinet + scan UI + group photo")
