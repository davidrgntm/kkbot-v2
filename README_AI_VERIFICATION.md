# KKB AI Attendance Verification

Qo‘shilgan funksiyalar:

- Web orqali Keldim/Ketdim: `/checkin` va `/checkout`
- Telegram bot orqali selfie + GPS tekshiruv logikasi
- AI-ready yuz moslik tekshiruvi: reference selfie + face score
- GPS geofence: shop radiusi, masofa, location status
- Admin review: `/verification`
- Har bir check uchun selfie, map, status: approved / needs_review / rejected
- 00:00 dan keyingi smenalar `status='open'` bo‘yicha yopiladi, sana bo‘yicha adashmaydi

## Environment variables

```env
DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
FACE_AI_MODE=auto
FACE_MATCH_THRESHOLD=0.72
FACE_WEAK_THRESHOLD=0.58
FACE_ALLOW_FIRST_REFERENCE=1
LOCATION_DEFAULT_RADIUS_M=250
```

## Shop koordinatalari

Admin web panelda shoplar sahifasida har bir do‘kon uchun `lat`, `lon`, `radius_m` to‘ldirilsa GPS tekshiruv aniq ishlaydi.

## Test

- `https://kkb.jelly.uz/checkin`
- `https://kkb.jelly.uz/checkout`
- `https://kkb.jelly.uz/verification`

## Face AI haqida

Bu versiya Railway’da stabil ishlashi uchun yengil face-score rejimida keladi. Birinchi selfi reference sifatida saqlanadi, keyingi selfie shu reference bilan solishtiriladi. Keyinchalik og‘ir face-recognition model ulansa, bot va web logikasi o‘zgarmaydi — faqat `services/attendance_verification.py` ichidagi `compare_face()` provider almashtiriladi.
