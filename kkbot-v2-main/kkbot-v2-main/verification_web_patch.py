from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse

import web_server as ws
from database.sqlite_db import db
from services.attendance_verification import (
    save_data_url_image,
    verify_attendance,
    checks,
    update_check_status,
    ensure_verification_tables,
)


def _esc(v):
    import html
    return html.escape(str(v if v is not None else ""), quote=True)


def _pill(status: str) -> str:
    cls = {
        "approved": "green",
        "needs_review": "amber",
        "rejected": "red",
        "match": "green",
        "weak": "amber",
        "no_match": "red",
        "ok": "green",
        "far": "red",
        "unknown": "amber",
    }.get(str(status), "blue")
    return f'<span class="pill {cls}">{_esc(status)}</span>'


def _base_css():
    return r'''
    body{margin:0;background:radial-gradient(circle at top left,#dbeafe,#f8fafc 45%,#eef2ff);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a}.wrap{max-width:1100px;margin:auto;padding:22px}.card{background:rgba(255,255,255,.86);border:1px solid #fff;border-radius:26px;box-shadow:0 22px 60px rgba(15,23,42,.12);padding:22px;margin:16px 0}.btn{border:0;border-radius:16px;background:#2563eb;color:white;padding:13px 16px;font-weight:800;cursor:pointer;text-decoration:none;display:inline-flex;gap:8px}.btn.red{background:#dc2626}.btn.green{background:#16a34a}.btn.gray{background:#e2e8f0;color:#0f172a}.pill{display:inline-flex;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:800;background:#f1f5f9}.green{background:#dcfce7;color:#166534}.red{background:#fee2e2;color:#991b1b}.amber{background:#fef3c7;color:#92400e}.blue{background:#dbeafe;color:#1d4ed8}.table{width:100%;border-collapse:separate;border-spacing:0 10px}.table td,.table th{text-align:left;background:white;border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;padding:12px}.table td:first-child{border-left:1px solid #e2e8f0;border-radius:14px 0 0 14px}.table td:last-child{border-right:1px solid #e2e8f0;border-radius:0 14px 14px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}video,canvas,img.selfie{width:100%;max-width:440px;border-radius:22px;background:#0f172a}.muted{color:#64748b}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}@media(max-width:750px){.grid{grid-template-columns:1fr}.wrap{padding:14px}.table td,.table th{font-size:12px;padding:9px}.btn{width:100%;justify-content:center}}
    '''


def page(title: str, body: str):
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_esc(title)}</title><style>{_base_css()}</style></head><body><div class='wrap'>{body}</div></body></html>")


def apply_verification_patch(app):
    ensure_verification_tables()
    def remove(path, method="GET"):
        app.router.routes = [r for r in app.router.routes if not (getattr(r, "path", None) == path and method in getattr(r, "methods", set()))]
    for p,m in [("/verification","GET"),("/checkin","GET"),("/checkout","GET"),("/check-in","GET"),("/check-out","GET"),("/web-checkin","GET"),("/web-checkout","GET"),("/api/attendance/verify","POST"),("/verification/{check_id}/status","POST"),("/attendance-photo/{check_id}","GET")]:
        remove(p,m)

    @app.get("/checkin", response_class=HTMLResponse)
    async def checkin(req: Request):
        red = ws.require_login(req)
        if red: return red
        return _capture_page("Keldim", "check_in")

    @app.get("/checkout", response_class=HTMLResponse)
    async def checkout(req: Request):
        red = ws.require_login(req)
        if red: return red
        return _capture_page("Ketdim", "check_out")

    def _capture_page(label: str, action: str):
        body = f"""
        <div class='top'><div><h1>🧠 AI Keldi-Ketdi · {_esc(label)}</h1><p class='muted'>Kamera + GPS + yuz moslik tekshiruvi</p></div><a class='btn gray' href='/cabinet'>Kabinetga qaytish</a></div>
        <div class='grid'>
          <div class='card'><h2>1. Selfie</h2><video id='video' autoplay playsinline></video><canvas id='canvas' style='display:none'></canvas><p class='muted'>Yuzingiz aniq ko‘rinsin. Telefonni haddan tashqari uzoq tutmang.</p></div>
          <div class='card'><h2>2. Tekshiruv</h2><p id='gps' class='muted'>GPS kutilmoqda...</p><button class='btn green' onclick='sendCheck()'>✅ {_esc(label)}ni tasdiqlash</button><div id='result' style='margin-top:16px'></div></div>
        </div>
        <script>
        let pos=null;
        async function boot(){{
          try{{ const stream=await navigator.mediaDevices.getUserMedia({{video:{{facingMode:'user'}},audio:false}}); document.getElementById('video').srcObject=stream; }}catch(e){{ document.getElementById('result').innerHTML='<div class="card">Kamera ochilmadi: '+e+'</div>'; }}
          navigator.geolocation.getCurrentPosition(p=>{{pos=p;document.getElementById('gps').innerHTML='GPS tayyor: '+p.coords.latitude.toFixed(5)+', '+p.coords.longitude.toFixed(5)+' · aniqlik '+Math.round(p.coords.accuracy)+'m'}}, e=>{{document.getElementById('gps').innerHTML='GPS xato: '+e.message}}, {{enableHighAccuracy:true,timeout:12000,maximumAge:0}});
        }}
        async function sendCheck(){{
          const v=document.getElementById('video'), c=document.getElementById('canvas'); c.width=v.videoWidth||640; c.height=v.videoHeight||480; c.getContext('2d').drawImage(v,0,0,c.width,c.height);
          const image=c.toDataURL('image/jpeg',0.88);
          const fd=new FormData(); fd.append('action','{action}'); fd.append('image_data',image);
          if(pos){{fd.append('lat',pos.coords.latitude);fd.append('lon',pos.coords.longitude);fd.append('accuracy',pos.coords.accuracy)}}
          document.getElementById('result').innerHTML='<div class="card">⏳ Tekshirilyapti...</div>';
          const r=await fetch('/api/attendance/verify',{{method:'POST',body:fd}}); const j=await r.json();
          document.getElementById('result').innerHTML='<div class="card"><h2>'+j.emoji+' '+j.title+'</h2><p>Yuz: <b>'+j.face_status+'</b> ('+j.face_score+')</p><p>Lokatsiya: <b>'+j.location_status+'</b> '+(j.distance_m?j.distance_m+'m':'')+'</p><p>'+j.message+'</p></div>';
        }}
        boot();
        </script>
        """
        return page(f"AI {label}", body)

    @app.post("/api/attendance/verify")
    async def api_verify(req: Request, action: str = Form(...), image_data: str = Form(...), lat: str = Form(""), lon: str = Form(""), accuracy: str = Form("")):
        red = ws.require_login(req)
        if red: return JSONResponse({"error":"unauthorized"}, status_code=401)
        user = ws.current_user(req)
        tid = str(user.get("telegram_id"))
        if tid == "admin_password":
            return JSONResponse({"error":"Admin password login orqali Keldim/Ketdim qilinmaydi"}, status_code=400)
        selfie_path = save_data_url_image(image_data, tid, "web")
        active = await db.get_active_shift_row(int(tid))
        latitude = float(lat) if lat else None
        longitude = float(lon) if lon else None
        acc = float(accuracy) if accuracy else None
        if action == "check_in" and active:
            return JSONResponse({"emoji":"⚠️","title":"Smena allaqachon ochiq","message":"Avval Ketdim qiling.","face_status":"-","face_score":"-","location_status":"-"})
        if action == "check_out" and not active:
            return JSONResponse({"emoji":"⚠️","title":"Ochiq smena yo‘q","message":"Avval Keldim qiling.","face_status":"-","face_score":"-","location_status":"-"})
        fallback_shop = ""
        result = verify_attendance(tid, action, selfie_path, latitude, longitude, acc, shift_id=active, source="web", fallback_shop=fallback_shop)
        if result["final_status"] == "rejected":
            return JSONResponse({"emoji":"❌","title":"Rad etildi","message":"Admin tekshirishi kerak.",**result})
        staff = await db.get_user_by_telegram_id(int(tid))
        if action == "check_in":
            staff_for_shift = staff.copy() if staff else {"TelegramID": tid, "Имя": user.get("name","Xodim"), "Роль":"staff"}
            staff_for_shift["Магазин"] = result.get("shop") or (staff_for_shift.get("Магазин","").split(",")[0].strip())
            ok = await db.start_shift(staff_for_shift, f"web:{result['check_id']}", f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else "")
            if ok:
                shift_id = await db.get_active_shift_row(int(tid))
                db._execute("UPDATE attendance_checks SET shift_id=? WHERE id=?", (shift_id, int(result["check_id"])))
                return JSONResponse({"emoji":"✅","title":"Smena ochildi","message":"Keldim saqlandi." if result["final_status"]=="approved" else "Keldim saqlandi, lekin admin reviewga tushdi.",**result})
            return JSONResponse({"emoji":"❌","title":"Xato","message":"Smena ochilmadi",**result}, status_code=500)
        worked = await db.end_shift(active, photo_id=f"web:{result['check_id']}", location=f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else "")
        return JSONResponse({"emoji":"✅","title":"Smena yopildi","message":f"Ketdim saqlandi. Ishladi: {worked}",**result})

    @app.get("/verification", response_class=HTMLResponse)
    async def verification(req: Request):
        red = ws.require_admin(req)
        if red: return red
        rows = checks(120)
        body_rows = ""
        for r in rows:
            map_link = f"https://www.google.com/maps?q={r['latitude']},{r['longitude']}" if r.get('latitude') and r.get('longitude') else ""
            check_id = int(r["id"])
            selfie_link = f"<a class='btn gray' href='/attendance-photo/{check_id}' target='_blank'>Selfie</a>"
            map_btn = f"<a class='btn gray' href='{_esc(map_link)}' target='_blank'>Map</a>" if map_link else ""
            status_form = (
                f"<form method='post' action='/verification/{check_id}/status' "
                "style='display:flex;gap:6px;flex-wrap:wrap;margin-top:6px'>"
                "<button class='btn green' name='status' value='approved'>OK</button>"
                "<button class='btn red' name='status' value='rejected'>Reject</button>"
                "<button class='btn gray' name='status' value='needs_review'>Review</button>"
                "</form>"
            )
            body_rows += (
                f"<tr><td>{check_id}</td>"
                f"<td>{_esc(r.get('created_at'))}<br>{_esc(r.get('source'))}</td>"
                f"<td>{_esc(r.get('name') or r.get('telegram_id'))}</td>"
                f"<td>{_esc(r.get('action'))}</td>"
                f"<td>{_esc(r.get('shop'))}<br>{_esc(r.get('distance_m') or '')}m</td>"
                f"<td>{_pill(r.get('face_status'))}<br>{_esc(r.get('face_score'))}</td>"
                f"<td>{_pill(r.get('location_status'))}</td>"
                f"<td>{_pill(r.get('final_status'))}</td>"
                f"<td>{selfie_link}{map_btn}{status_form}</td></tr>"
            )
        body = f"<div class='top'><div><h1>🧠 AI tekshiruvlar</h1><p class='muted'>Yuz moslik, GPS, selfie va admin review</p></div><a class='btn gray' href='/dashboard'>Dashboard</a></div><div class='card' style='overflow:auto'><table class='table'><tr><th>ID</th><th>Vaqt</th><th>Xodim</th><th>Action</th><th>Shop/Masofa</th><th>Yuz</th><th>GPS</th><th>Status</th><th>Amal</th></tr>{body_rows}</table></div>"
        return page("AI tekshiruvlar", body)

    @app.post("/verification/{check_id}/status")
    async def set_status(req: Request, check_id: int, status: str = Form(...)):
        red = ws.require_admin(req)
        if red: return red
        user = ws.current_user(req) or {}
        update_check_status(check_id, status, str(user.get("telegram_id", "admin")))
        return RedirectResponse("/verification", status_code=303)

    @app.get("/attendance-photo/{check_id}")
    async def attendance_photo(req: Request, check_id: int):
        red = ws.require_admin(req)
        if red: return red
        row = db._execute("SELECT selfie_path FROM attendance_checks WHERE company_id=? AND id=?", (db._current_cid(), int(check_id)), "one")
        if not row or not row["selfie_path"] or not os.path.exists(row["selfie_path"]):
            return JSONResponse({"error":"not found"}, status_code=404)
        return FileResponse(row["selfie_path"])

    print("[verification_web_patch] applied")
