# KKB Bot v2 — SQLite Edition

Bu versiyada botning asosiy bazasi **SQLite** bo‘ldi. Google Sheets endi faqat:

- eski bazadan migratsiya qilish;
- export / backup;
- tashqi hisobot chiqarish uchun ishlatiladi.

## Nima o‘zgardi

- `database/sqlite_db.py` qo‘shildi — asosiy operatsion baza.
- Bot handlerlari SQLite bazaga ulandi.
- `00:00` dan keyingi ochiq smena bugi tuzatildi: smena endi sana bo‘yicha emas, `status='open'` bo‘yicha qidiriladi.
- `scripts/migrate_from_google_sheets.py` qo‘shildi — Google Sheets → SQLite migratsiya.
- `scripts/export_to_google_sheets.py` qo‘shildi — SQLite → Google Sheets export.
- `.env` zip/repo ichidan olib tashlandi. `.env.example` qoldirildi.

## ENV

`.env.example` faylidan `.env` yarating:

```env
BOT_TOKEN=
ADMIN_IDS=
GROUP_CHAT_ID=
TIMEZONE=Asia/Tashkent
GOOGLE_SHEET_ID=
GOOGLE_CREDS_PATH=google_credentials.json
GOOGLE_CREDS_JSON=
DB_PATH=/data/kkbot.db
```

Railway uchun tavsiya:

```env
DB_PATH=/data/kkbot.db
```

Railway volume `/data` ga ulangan bo‘lishi kerak.

## 1. Migratsiya: Google Sheets → SQLite

Productionda botni vaqtincha to‘xtatib, keyin buni ishga tushiring:

```bash
python scripts/migrate_from_google_sheets.py
```

Agar boshqa Google Sheet ID ko‘rsatmoqchi bo‘lsangiz:

```bash
python scripts/migrate_from_google_sheets.py --sheet-id YOUR_SHEET_ID
```

Bu Google Sheetsdagi ma’lumotlarni o‘chirmaydi.

## 2. Botni ishga tushirish

```bash
python main.py
```

Docker/Railwayda odatiy `CMD ["python", "main.py"]` ishlaydi.

## 3. SQLite → Google Sheets export

Xodimlar:

```bash
python scripts/export_to_google_sheets.py employees
```

Smenalar:

```bash
python scripts/export_to_google_sheets.py shifts
```

Grafik:

```bash
python scripts/export_to_google_sheets.py schedule
```

Oy bo‘yicha tabel:

```bash
python scripts/export_to_google_sheets.py tabel --year 2026 --month 4
```

Shop bo‘yicha:

```bash
python scripts/export_to_google_sheets.py tabel --year 2026 --month 4 --shop "TSM"
```

## Asosiy SQLite fayllar

```text
data/kkbot.db
data/kkbot.db-wal
data/kkbot.db-shm
```

Backup qilganda uchalasini ham hisobga oling.

## Muhim xavfsizlik

Agar eski zip ichida `.env` bo‘lgan bo‘lsa, Telegram bot token va Google credentials xavfsizligini tekshiring. Token begonalarga chiqib ketgan bo‘lsa, yangisini oling.

## Web panel

This version can run the Telegram bot and the web admin panel in the same Railway service.

Required Railway variables:

```env
DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
WEB_ADMIN_PASSWORD=your_strong_password
WEB_SECRET=any_random_long_secret
```

Railway settings:

```text
Pre-deploy Command: empty
Custom Start Command: python main.py
Volume mount path: /app/data
```

Open the Railway public domain after deployment. The web panel includes:

- Dashboard
- Employees
- Shops
- Shifts
- Schedule
- Salary calculation
- Google Sheets export buttons

If `WEB_ADMIN_PASSWORD` is empty, the first `ADMIN_IDS` value is used as a temporary password.
