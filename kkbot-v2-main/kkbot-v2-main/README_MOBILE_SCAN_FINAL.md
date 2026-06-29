# KKB Mobile Scan Final

Bu zip ichida mobil Keldim/Ketdim scan flow tayyorlangan.

## Qo‘shildi

- Xodim kabinetida katta **Keldim** va **Ketdim** tugmalari.
- Xodim kabinetida admin sidebar/topbar chiqmaydi.
- `/checkin` va `/checkout` sahifalari mobil face-scan ko‘rinishida.
- Kamera + GPS + liveness step-by-step tekshiriladi.
- Keldim/Ketdim bazaga yozish tugmasi faqat hammasi tayyor bo‘lgandan keyin chiqadi.
- Web orqali Keldim/Ketdim qilinganda Telegram gruppaga selfie bilan xabar yuboriladi.
- `/verification` admin review sahifasi.
- `/check-in`, `/check-out`, `/web-checkin`, `/web-checkout` aliaslari.
- Login sahifasi tozalandi: telefon/Telegram ID → Telegram OTP. Parol formasi ko‘rinmaydi.
- PWA manifest va minimal service worker qo‘shildi.

## Railway sozlamalari

```env
DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
FACE_AI_MODE=auto
FACE_MATCH_THRESHOLD=0.72
FACE_WEAK_THRESHOLD=0.58
FACE_ALLOW_FIRST_REFERENCE=1
LOCATION_DEFAULT_RADIUS_M=250
```

Start command:

```bash
python main.py
```

Deploy logda chiqishi kerak:

```text
Final dashboard patch ulandi ✅
[mobile_scan_patch] applied: staff cabinet + scan UI + group photo
Mobile scan + AI verification patch ulandi ✅
```

## Tekshirish URLlari

```text
https://kkb.jelly.uz/cabinet
https://kkb.jelly.uz/checkin
https://kkb.jelly.uz/checkout
https://kkb.jelly.uz/verification
```
