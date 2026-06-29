# KKB Bot v2

**KKB Bot v2** — xodimlarning ishga kelishi/ketishini nazorat qilish, grafik tuzish, oylik hisoblash, web admin panel, Telegram bot, Google Sheets migratsiya/export va mobil selfie + GPS verification funksiyalarini birlashtirgan ichki HR/attendance tizimi.

Loyiha asosiy bazani **SQLite** orqali yuritadi. Google Sheets endi asosiy operatsion baza emas, faqat eski ma’lumotlarni ko‘chirish, backup va export/hisobot chiqarish uchun ishlatiladi.

---

## Mundarija

- [Asosiy imkoniyatlar](#asosiy-imkoniyatlar)
- [Texnologiyalar](#texnologiyalar)
- [Loyiha strukturasi](#loyiha-strukturasi)
- [Ishlash mantig‘i](#ishlash-mantigi)
- [Rollar](#rollar)
- [Telegram bot menyusi](#telegram-bot-menyusi)
- [Web panel sahifalari](#web-panel-sahifalari)
- [Database modeli](#database-modeli)
- [Environment variables](#environment-variables)
- [Local ishga tushirish](#local-ishga-tushirish)
- [Docker orqali ishga tushirish](#docker-orqali-ishga-tushirish)
- [Railway deploy](#railway-deploy)
- [Google Sheets migratsiya](#google-sheets-migratsiya)
- [Google Sheets export](#google-sheets-export)
- [Mobile Keldim/Ketdim scan](#mobile-keldimketdim-scan)
- [AI/selfie verification](#aiselfie-verification)
- [Hisobotlar](#hisobotlar)
- [API va route’lar](#api-va-routelar)
- [Backup](#backup)
- [Troubleshooting](#troubleshooting)
- [Xavfsizlik](#xavfsizlik)
- [Production checklist](#production-checklist)

---

## Asosiy imkoniyatlar

### Telegram bot

- Xodim bot orqali `Keldim` va `Ketdim` bosadi.
- Bot xodimdan selfie/photo va lokatsiya so‘raydi.
- Ochiq smena `status='open'` bo‘yicha topiladi, shu sababli smena 00:00 dan keyin ham to‘g‘ri yopiladi.
- Xodim o‘z kabinetida statistika, oylik, grafik va tarixni ko‘ra oladi.
- Admin/manager xodim qo‘shadi, o‘chiradi, stavka va emoji o‘zgartiradi.
- Admin/manager grafik tuzadi, tahrirlaydi va guruhga yuboradi.
- Manager oy/filial bo‘yicha hisobot oladi.

### Web panel

- Telefon/Telegram ID orqali login.
- Telegram botga OTP kod yuboriladi.
- Admin uchun emergency password login mavjud.
- Dashboard live monitoring bilan ishlaydi.
- Online smenalar soniya/daqiqa bo‘yicha yangilanadi.
- Xodimlar, filiallar, smenalar, grafik, oylik, arizalar va inventar boshqariladi.
- Xodim shaxsiy kabinetdan avatar va reference photo yuklay oladi.
- Web orqali ham `Keldim/Ketdim` qilish mumkin.
- Admin `/verification` sahifasida tekshiruvlarni tasdiqlaydi yoki rad etadi.

### SQLite + Google Sheets

- SQLite — asosiy tezkor operatsion baza.
- Google Sheets — migratsiya, backup va export uchun.
- Eski botdagi Google Sheets logikasiga mos compatibility adapter bor.
- Railway’da volume bilan ishlashga moslangan.

### Hisob-kitob

- Real ishlangan vaqt alohida hisoblanadi.
- Pullik vaqt eski bot qoidasi bilan hisoblanadi:
  - 30 minut yoki undan ko‘p bo‘lsa 1 soatga yaxlitlanadi;
  - yaxlitlangan soat 5 yoki undan ko‘p bo‘lsa 1 soat tushlik ayriladi;
  - natija to‘liq soat ko‘rinishida chiqadi, masalan: `8 ч 00 м`.

---

## Texnologiyalar

| Qism | Texnologiya |
|---|---|
| Telegram bot | aiogram 3.15 |
| Web backend | FastAPI |
| Web server | Uvicorn |
| Database | SQLite WAL mode |
| Google Sheets | gspread-asyncio + google-auth |
| Hisobot/export | pandas, openpyxl, reportlab |
| Image/reference photo | Pillow |
| Config | pydantic-settings + python-dotenv |
| Deploy | Docker / Railway |

---

## Loyiha strukturasi

```text
.
├── main.py                         # Telegram bot + web server start nuqtasi
├── config.py                       # ENV sozlamalarini o‘qish
├── web_server.py                   # FastAPI web panel asosiy route’lari
├── kkb_stable_patch.py             # Web patch: scan, verification, reports, employee pages
├── final_premium_patch.py          # Dashboard/cabinet premium patch
├── mobile_scan_patch.py            # Mobil scan UI patch
├── verification_web_patch.py       # Verification UI patch
├── database/
│   ├── sqlite_db.py                # SQLite asosiy baza va compatibility adapter
│   ├── google_sheets.py            # Google Sheets bilan ishlash
│   ├── saas.py                     # SaaS/multi-company DB yordamchi qismi
│   └── schema.sql                  # Boshlang‘ich SQL schema
├── handlers/
│   ├── common.py                   # /start va umumiy handlerlar
│   ├── attendance.py               # Keldim/Ketdim bot flow
│   ├── reporting.py                # Xodim kabineti/statistika/oylik/grafik
│   ├── manager.py                  # Manager hisobotlari
│   ├── admin.py                    # Xodimlar markazi/admin panel
│   ├── admin_schedule.py           # Grafik yaratish/tahrirlash
│   └── super_admin.py              # /new_client flow
├── keyboards/
│   └── builders.py                 # Telegram keyboard va inline keyboardlar
├── middlewares/
│   └── auth.py                     # Telegram user auth middleware
├── services/
│   ├── attendance_verification.py  # Selfie/GPS/reference verification
│   ├── google_export.py            # SQLite → Google Sheets export
│   └── quick_schedule.py           # Tez grafik text parser
├── scripts/
│   ├── migrate_from_google_sheets.py
│   ├── reset_and_migrate.py
│   ├── export_to_google_sheets.py
│   ├── audit_migration.py
│   └── debug_sqlite_context.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Ishlash mantig‘i

### 1. Bot start bo‘lganda

`main.py` quyidagi ishlarni qiladi:

1. ENV’dan config o‘qiladi.
2. Telegram bot yaratiladi.
3. `AuthMiddleware` ulanadi.
4. Routerlar ulanadi:
   - `super_admin`
   - `common`
   - `admin_schedule`
   - `manager`
   - `admin`
   - `reporting`
   - `attendance`
5. SQLite bilan aloqa tekshiriladi.
6. `WEB_ENABLED=1` bo‘lsa, web panel Uvicorn orqali parallel ishga tushadi.
7. Bot polling rejimida ishlaydi.

### 2. Xodim botdan foydalanganda

1. Middleware Telegram ID orqali xodimni bazadan qidiradi.
2. Xodim topilmasa, tizimga kiritilmagan deb javob beradi.
3. Admin ID `.env` ichidagi `ADMIN_IDS` ro‘yxatida bo‘lsa, kerak bo‘lsa avtomatik admin sifatida qo‘shiladi.
4. Xodim roli bo‘yicha menyu ko‘rsatiladi.

### 3. Smena ochish/yopish

- `Keldim` bosilganda smena ochiladi.
- `Ketdim` bosilganda ochiq smena topiladi va yopiladi.
- Smena `business_date`, `start_at`, `end_at`, `status`, `worked_minutes`, `break_minutes`, `shop`, `photo_id`, `location` kabi maydonlar bilan saqlanadi.
- 00:00 dan keyingi bug oldini olish uchun ochiq smena sana bilan emas, `status='open'` bilan qidiriladi.

### 4. Grafik

- Admin/manager kalendar orqali kun tanlaydi.
- Filial va xodimlar tanlanadi.
- Ish vaqti yoki status tanlanadi:
  - ish smenasi;
  - dam olish;
  - отпуск;
  - больничный.
- Bir nechta haftaga repeat qilish mumkin.
- Grafik saqlanadi va xohlasa Telegram guruhga yuboriladi.
- Tez grafik funksiyasi matndan grafikni tushunib, preview beradi.

---

## Rollar

| Rol | Imkoniyatlar |
|---|---|
| `staff` | Keldim/Ketdim, shaxsiy kabinet, statistika, grafik, oylik |
| `manager` | Staff imkoniyatlari + hisobotlar, grafik, xodimlar bilan ishlash |
| `admin` | Barcha boshqaruv funksiyalari, web panel, verification, export |
| `super_admin` | `/new_client` orqali yangi client/company yaratish flow |

---

## Telegram bot menyusi

### Hamma xodimlar uchun

```text
🟢 Keldim
🔴 Ketdim
📅 Grafik
👤 Kabinetim
📊 Statistika
```

### Admin/manager uchun qo‘shimcha

```text
🧾 Hisobotlar
🧩 Grafik tuzish
📆 Umumiy grafik
✏️ Grafik tahrirlash
👥 Xodimlar
⚙️ Admin Panel
```

### Xodim kabineti

- Statistika
- Oylik
- Oyma-oy tahlil
- Smaylik tanlash
- Admin bo‘lsa — Xodimlar markazi

### Xodimlar markazi

- Online xodimlar
- Katalog
- Analitika
- Qidirish
- Xodim profili
- Stavka o‘zgartirish
- Emoji o‘zgartirish
- Xodimni o‘chirish/deaktiv qilish

---

## Web panel sahifalari

| Sahifa | Vazifasi |
|---|---|
| `/login` | Web login sahifasi |
| `/cabinet` | Xodim shaxsiy kabineti |
| `/dashboard` | Admin dashboard/live monitoring |
| `/employees` | Xodimlar ro‘yxati |
| `/employees/{telegram_id}` | Xodim profili |
| `/shops` | Filiallar/do‘konlar boshqaruvi |
| `/shifts` | Smenalar tarixi va tahrirlash |
| `/schedule` | Grafik boshqaruvi |
| `/quick-schedule` | Tez grafik kiritish |
| `/salary` | Oylik hisob-kitob |
| `/requests` | Xodim arizalari |
| `/inventory` | Xodimlarga berilgan buyumlar/inventar |
| `/reports` | Bot uslubidagi Excel hisobotlar |
| `/export` | Export sahifasi yoki reports sahifasiga yo‘naltirish |
| `/verification` | Selfie/GPS check review |
| `/checkin` | Web orqali Keldim |
| `/checkout` | Web orqali Ketdim |
| `/health` | Health check |

---

## Database modeli

SQLite WAL mode ishlatiladi:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

### Asosiy jadvallar

| Jadval | Vazifasi |
|---|---|
| `users` | Xodimlar, Telegram ID, rol, telefon, stavka, avatar |
| `shops` | Filiallar, koordinata, radius |
| `user_shops` | Xodim–filial bog‘lanishi |
| `schedules` | Ish grafigi |
| `shifts` | Real smenalar/keldim-ketdim yozuvlari |
| `audit_log` | Admin harakatlari logi |
| `employee_requests` | Xodim arizalari |
| `inventory` | Berilgan inventar/buyumlar |
| `export_jobs` | Export vazifalari tarixi |
| `web_login_codes` | Web OTP login kodlari |
| `face_templates` | Xodim reference photo ma’lumoti |
| `attendance_checks` | Web/mobile verification checklari |

### `users` muhim maydonlari

```text
telegram_id
full_name
phone
role
active
hourly_rate
emoji
department
position
hire_date
avatar_file_id
```

### `shops` muhim maydonlari

```text
name
lat
lon
radius_m
active
```

### `schedules` muhim maydonlari

```text
telegram_id
name
shop
work_date
kind
status_code
start_time
end_time
created_by
```

### `shifts` muhim maydonlari

```text
telegram_id
name
shop
business_date
start_at
end_at
status
start_photo_id
end_photo_id
start_location
end_location
worked_minutes
break_minutes
late_minutes
source
```

---

## Environment variables

`.env.example` asosida `.env` yarating.

```env
BOT_TOKEN=
ADMIN_IDS=
GROUP_CHAT_ID=
TIMEZONE=Asia/Tashkent

# Google Sheets faqat migratsiya/export uchun ishlatiladi
GOOGLE_SHEET_ID=
GOOGLE_CREDS_PATH=google_credentials.json
GOOGLE_CREDS_JSON=

# SQLite asosiy DB
DB_PATH=/app/data/kkbot.db

# Web panel
WEB_ENABLED=1
WEB_ADMIN_PASSWORD=
WEB_SECRET=

# Railway port odatda avtomatik beriladi
PORT=8000
```

### Majburiy sozlamalar

| Variable | Izoh |
|---|---|
| `BOT_TOKEN` | Telegram BotFather tokeni |
| `ADMIN_IDS` | Admin Telegram ID’lari, vergul bilan: `123,456` |
| `GROUP_CHAT_ID` | Grafik va attendance xabarlari ketadigan Telegram group ID |
| `GOOGLE_SHEET_ID` | Eski Google Sheets ID / export sheet ID |
| `DB_PATH` | SQLite fayl yo‘li |

### Web sozlamalari

| Variable | Default | Izoh |
|---|---:|---|
| `WEB_ENABLED` | `1` | `0`, `false`, `no` bo‘lsa web panel o‘chadi |
| `WEB_ADMIN_PASSWORD` | birinchi admin ID | Emergency admin login paroli |
| `WEB_SECRET` | bot token | Session cookie uchun secret |
| `PORT` | `8000` | Railway odatda o‘zi beradi |

### Verification sozlamalari

```env
FACE_AI_MODE=auto
FACE_MATCH_THRESHOLD=0.72
FACE_WEAK_THRESHOLD=0.58
FACE_ALLOW_FIRST_REFERENCE=1
LOCATION_DEFAULT_RADIUS_M=250
```

| Variable | Izoh |
|---|---|
| `FACE_AI_MODE` | `auto`, `phash`, `off`; default `auto` |
| `FACE_MATCH_THRESHOLD` | Selfie/reference moslik chegarasi |
| `FACE_WEAK_THRESHOLD` | Shubhali moslik chegarasi |
| `FACE_ALLOW_FIRST_REFERENCE` | Birinchi selfie’ni reference sifatida olish |
| `LOCATION_DEFAULT_RADIUS_M` | Shop radiusi kiritilmagan bo‘lsa default radius |

### Multi-company/advanced

| Variable | Izoh |
|---|---|
| `FORCE_COMPANY_ID` | SQLite context uchun majburiy company ID |
| `DB_FOLDER` | DB joylashadigan papka |

---

## Local ishga tushirish

### 1. Python virtual environment

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 2. Kutubxonalarni o‘rnatish

```bash
pip install -r requirements.txt
```

### 3. `.env` tayyorlash

```bash
cp .env.example .env
```

So‘ng `.env` ichiga Telegram token, admin ID, group ID va Google ma’lumotlarini kiriting.

### 4. Papka yaratish

```bash
mkdir -p data
```

Local uchun tavsiya:

```env
DB_PATH=data/kkbot.db
```

### 5. Botni ishga tushirish

```bash
python main.py
```

Web panel ham yoqilgan bo‘lsa, lokal URL:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

---

## Docker orqali ishga tushirish

Dockerfile tayyor:

```bash
docker build -t kkb-bot-v2 .
docker run --env-file .env -p 8000:8000 kkb-bot-v2
```

Docker Compose:

```bash
docker compose up -d --build
```

`docker-compose.yml` `.env` faylini avtomatik o‘qiydi.

---

## Railway deploy

### Railway variables

Railway → Variables qismiga quyidagilarni kiriting:

```env
BOT_TOKEN=your_bot_token
ADMIN_IDS=806860624
GROUP_CHAT_ID=-100xxxxxxxxxx
TIMEZONE=Asia/Tashkent

GOOGLE_SHEET_ID=your_google_sheet_id
GOOGLE_CREDS_JSON={"type":"service_account",...}

DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
WEB_ADMIN_PASSWORD=strong_password
WEB_SECRET=random_long_secret

FACE_AI_MODE=auto
FACE_MATCH_THRESHOLD=0.72
FACE_WEAK_THRESHOLD=0.58
FACE_ALLOW_FIRST_REFERENCE=1
LOCATION_DEFAULT_RADIUS_M=250
```

### Railway settings

```text
Custom Start Command: python main.py
Pre-deploy Command: bo‘sh
Volume mount path: /app/data
```

Muhim: SQLite doimiy saqlanishi uchun Railway volume ulanishi shart.

### Deploydan keyin tekshirish

```text
https://your-domain/health
https://your-domain/login
https://your-domain/dashboard
https://your-domain/cabinet
https://your-domain/checkin
https://your-domain/checkout
https://your-domain/verification
```

Loglarda quyidagiga o‘xshash xabarlar chiqishi mumkin:

```text
SQLite baza bilan aloqa o'rnatildi ✅
Bot ishga tushdi 🚀
Web panel ishga tushyapti: 0.0.0.0:PORT
KKB stable web patch ulandi ✅
Final schedule patch ulandi ✅
```

---

## Google Sheets migratsiya

Google Sheets endi asosiy baza emas. Eski ma’lumotlarni SQLite’ga ko‘chirish uchun migratsiya ishlatiladi.

### Oddiy migratsiya

```bash
python scripts/migrate_from_google_sheets.py
```

Boshqa Sheet ID bilan:

```bash
python scripts/migrate_from_google_sheets.py --sheet-id YOUR_SHEET_ID
```

Bu script Google Sheetsdagi ma’lumotlarni o‘chirmaydi. Faqat o‘qib, SQLite’ga yozadi.

### Tozalab qayta migratsiya qilish

Agar Railway’da bot faqat 1 ta auto-admin ko‘rayotgan bo‘lsa, shoplar chiqmasa yoki eski data noto‘g‘ri import bo‘lgan bo‘lsa:

```bash
python scripts/reset_and_migrate.py
```

Boshqa Sheet ID bilan:

```bash
python scripts/reset_and_migrate.py --sheet-id YOUR_SHEET_ID
```

Bu SQLite operatsion jadvallarini tozalaydi va Google Sheets’dan qayta import qiladi. Google Sheets o‘zgarmaydi.

### Railway’da migratsiya qilish

1. Railway’da Start Command’ni vaqtincha o‘zgartiring:

```bash
python scripts/reset_and_migrate.py
```

2. Deploy tugagach logda quyidagilarni tekshiring:

```text
Сотрудники → SQLite
Магазины → SQLite
График → SQLite
Смены → SQLite
```

3. Keyin Start Command’ni qaytaring:

```bash
python main.py
```

---

## Google Sheets export

SQLite’dan Google Sheets’ga export qilish uchun:

### Xodimlar

```bash
python scripts/export_to_google_sheets.py employees
```

### Smenalar

```bash
python scripts/export_to_google_sheets.py shifts
```

### Grafik

```bash
python scripts/export_to_google_sheets.py schedule
```

### Oy bo‘yicha tabel

```bash
python scripts/export_to_google_sheets.py tabel --year 2026 --month 4
```

### Filial bo‘yicha tabel

```bash
python scripts/export_to_google_sheets.py tabel --year 2026 --month 4 --shop "TSM"
```

### Boshqa Sheet ID’ga export

```bash
python scripts/export_to_google_sheets.py employees --sheet-id YOUR_SHEET_ID
```

---

## Mobile Keldim/Ketdim scan

Mobil flow quyidagilarni qo‘llab-quvvatlaydi:

- `/checkin` — web orqali Keldim;
- `/checkout` — web orqali Ketdim;
- `/check-in`, `/check-out`, `/web-checkin`, `/web-checkout` — alias route’lar;
- kamera orqali selfie;
- GPS location;
- liveness/tekshiruv flow;
- hammasi tayyor bo‘lganda tasdiqlash;
- Telegram guruhga selfie bilan xabar yuborish;
- admin verification sahifasi.

Xodim kabinetida katta `Keldim` va `Ketdim` tugmalari bor. Xodim kabinetida admin sidebar/topbar ko‘rinmaydi.

---

## AI/selfie verification

Verification `services/attendance_verification.py` ichida ishlaydi.

Tekshiruvlar:

1. Selfie saqlanadi.
2. GPS koordinata tekshiriladi.
3. Xodim shop radiusida yoki yo‘qligi aniqlanadi.
4. Xodimning reference photo’si bilan moslik score hisoblanadi.
5. Final status belgilanadi:
   - `approved`
   - `needs_review`
   - `rejected`
6. Admin `/verification` sahifasida natijani qo‘lda tasdiqlashi yoki rad etishi mumkin.

### Reference photo

Xodim kabinetida yuqori sifatli reference photo yuklash mumkin.

Route’lar:

```text
POST /cabinet/reference-photo
GET  /face-reference/{telegram_id}
```

Faqat xodimning o‘zi yoki admin reference rasmni ko‘ra oladi.

### Face AI haqida muhim izoh

Hozirgi versiya Railway’da yengil va stabil ishlashi uchun og‘ir face-recognition modeli bilan emas, **AI-ready lightweight score** logikasi bilan keladi. Birinchi selfie reference sifatida saqlanishi mumkin. Keyinchalik haqiqiy face-recognition provider qo‘shilsa, asosiy bot/web oqimini o‘zgartirmasdan `compare_face()` funksiyasi almashtiriladi.

---

## Hisobotlar

### Bot orqali

`🧾 Hisobotlar` menyusi orqali manager/admin:

1. Oy tanlaydi.
2. Filial tanlaydi.
3. Excel formatida hisobot oladi.

### Web orqali

```text
/reports
/reports/download
```

Hisobot bot formatiga o‘xshash:

```text
ФИО
Должность
c / до / итого
oy kunlari
1-15
16-end
JAMI
```

Manba: SQLite `shifts` jadvali.

---

## API va route’lar

### Auth route’lar

| Method | Route | Vazifa |
|---|---|---|
| GET | `/login` | Login form |
| POST | `/login/request` | Telefon/Telegram ID orqali OTP so‘rash |
| POST | `/login/verify` | OTP kodni tasdiqlash |
| POST | `/login/password` | Emergency admin password login |
| POST | `/logout` | Logout |

### Cabinet route’lar

| Method | Route | Vazifa |
|---|---|---|
| GET | `/cabinet` | Xodim kabineti |
| POST | `/cabinet/avatar` | Avatar yuklash |
| POST | `/cabinet/reference-photo` | Reference photo yuklash |
| GET | `/my-shifts` | Xodim smena tarixi |
| GET | `/my-schedule` | Xodim grafigi |
| GET | `/uploads/{filename}` | Yuklangan faylni ko‘rish |
| GET | `/face-reference/{telegram_id}` | Reference photo ko‘rish |

### Admin panel route’lari

| Method | Route | Vazifa |
|---|---|---|
| GET | `/dashboard` | Live dashboard |
| GET | `/api/dashboard/live` | Dashboard live payload |
| GET | `/employees` | Xodimlar ro‘yxati |
| POST | `/employees/add` | Xodim qo‘shish |
| GET | `/employees/{telegram_id}` | Xodim profili |
| POST | `/employees/{telegram_id}/update` | Xodimni tahrirlash |
| POST | `/employees/{telegram_id}/delete` | Xodimni deaktiv qilish |
| GET | `/shops` | Filiallar |
| POST | `/shops/add` | Filial qo‘shish |
| POST | `/shops/{shop_id}/update` | Filialni tahrirlash |
| POST | `/shops/{shop_id}/delete` | Filialni deaktiv qilish |
| GET | `/shifts` | Smenalar |
| POST | `/shifts/add` | Smena qo‘shish |
| GET | `/shifts/{shift_id}` | Smenani ko‘rish/tahrirlash |
| POST | `/shifts/{shift_id}/update` | Smenani yangilash |
| POST | `/shifts/{shift_id}/delete` | Smenani o‘chirish |
| GET | `/schedule` | Grafik sahifasi |
| POST | `/schedule/add` | Grafik qator qo‘shish |
| GET | `/schedule/{sched_id}` | Grafik qatorini ko‘rish/tahrirlash |
| POST | `/schedule/{sched_id}/update` | Grafik qatorini yangilash |
| POST | `/schedule/{sched_id}/delete` | Grafik qatorini o‘chirish |
| GET | `/salary` | Oylik sahifasi |
| GET | `/requests` | Arizalar |
| POST | `/requests/add` | Ariza qo‘shish |
| POST | `/requests/{rid}/status` | Ariza statusini o‘zgartirish |
| GET | `/inventory` | Inventar |
| POST | `/inventory/add` | Inventar qo‘shish |

### Quick schedule route’lari

| Method | Route | Vazifa |
|---|---|---|
| GET | `/quick-schedule` | Tez grafik formasi |
| POST | `/quick-schedule` | Matndan grafik yaratish/preview |

### Reports/export route’lari

| Method | Route | Vazifa |
|---|---|---|
| GET | `/reports` | Hisobot sahifasi |
| POST | `/reports/download` | Excel hisobot yuklab olish |
| GET | `/export` | Export sahifasi yoki `/reports`ga redirect |
| POST | `/export/run` | Google Sheets export |

### Attendance verification route’lari

| Method | Route | Vazifa |
|---|---|---|
| GET | `/checkin` | Web Keldim |
| GET | `/checkout` | Web Ketdim |
| GET | `/check-in` | Alias |
| GET | `/check-out` | Alias |
| GET | `/web-checkin` | Alias |
| GET | `/web-checkout` | Alias |
| POST | `/api/attendance/verify` | Selfie/GPS check yuborish |
| GET | `/verification` | Admin review |
| POST | `/verification/{check_id}/status` | Check statusini o‘zgartirish |
| GET | `/attendance-photo/{check_id}` | Check selfie rasmini ko‘rish |

### System route’lar

| Method | Route | Vazifa |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/stats` | Oddiy statistik API |

---

## Backup

SQLite WAL mode ishlagani uchun backupda faqat `.db` fayl emas, yonidagi WAL/SHM fayllar ham kerak bo‘lishi mumkin.

Asosiy fayllar:

```text
/app/data/kkbot.db
/app/data/kkbot.db-wal
/app/data/kkbot.db-shm
```

Localda:

```text
data/kkbot.db
data/kkbot.db-wal
data/kkbot.db-shm
```

Railway’da volume backup qilishni alohida nazorat qilish kerak.

---

## Troubleshooting

### 1. Bot start bo‘lmayapti

Tekshiring:

- `BOT_TOKEN` to‘g‘ri kiritilganmi?
- `.env` fayl bor-mi?
- `ADMIN_IDS` faqat raqamlardan iboratmi?
- `GROUP_CHAT_ID` to‘g‘ri group ID’mi?
- `GOOGLE_SHEET_ID` bo‘sh emasmi?

### 2. Railway’da data yo‘qolib qolyapti

Sabab: volume ulanmagan yoki `DB_PATH` noto‘g‘ri.

To‘g‘ri sozlama:

```env
DB_PATH=/app/data/kkbot.db
```

Railway volume mount path:

```text
/app/data
```

### 3. Bot faqat 1 ta admin ko‘ryapti, xodimlar chiqmayapti

Ehtimol migratsiya ishlamagan yoki boshqa DB fayl ishlayapti.

Yechim:

```bash
python scripts/reset_and_migrate.py
```

Keyin Start Command’ni qaytaring:

```bash
python main.py
```

### 4. Web login kodi kelmayapti

Tekshiring:

- xodim `users` jadvalida bormi;
- xodimning `phone` maydoni to‘ldirilganmi;
- xodim Telegram botni oldin `/start` qilganmi;
- `BOT_TOKEN` to‘g‘rimi;
- Telegram user botni bloklamaganmi.

### 5. Keldim/Ketdimda lokatsiya noto‘g‘ri chiqyapti

Tekshiring:

- `shops` jadvalida `lat`, `lon`, `radius_m` to‘ldirilganmi;
- xodim telefonda location permission berganmi;
- `LOCATION_DEFAULT_RADIUS_M` juda kichik emasmi.

### 6. `/checkin` yoki `/checkout` ochilmayapti

Tekshiring:

- `WEB_ENABLED=1`;
- Railway public domain ishlayaptimi;
- logda web patch ulanganmi;
- `/health` javob beryaptimi.

### 7. Face verification hammani `needs_review` qilyapti

Tekshiring:

- xodimda reference photo bormi;
- `FACE_ALLOW_FIRST_REFERENCE=1` bo‘lsa, birinchi rasm reference sifatida saqlanishi mumkin;
- `FACE_MATCH_THRESHOLD` juda baland emasmi;
- rasm sifati juda past emasmi.

### 8. Google Sheets export ishlamayapti

Tekshiring:

- `GOOGLE_SHEET_ID` to‘g‘ri;
- `GOOGLE_CREDS_JSON` to‘g‘ri JSON;
- yoki `GOOGLE_CREDS_PATH` fayli mavjud;
- Google service account Sheet’ga editor sifatida qo‘shilgan.

### 9. Python import/module xatosi

Kutubxonalarni qayta o‘rnating:

```bash
pip install -r requirements.txt
```

Syntax/importni tekshirish:

```bash
python -m compileall .
```

---

## Xavfsizlik

`.env` faylni GitHub’ga chiqarish mumkin emas.

GitHub’ga chiqmasligi kerak bo‘lgan ma’lumotlar:

```text
BOT_TOKEN
GOOGLE_CREDS_JSON
google_credentials.json
WEB_ADMIN_PASSWORD
WEB_SECRET
kkbot.db
kkbot.db-wal
kkbot.db-shm
```

Agar token yoki Google credentials avval zip/repo ichiga tushib qolgan bo‘lsa:

1. Telegram BotFather orqali tokenni yangilang.
2. Google service account key’ni revoke qilib, yangisini yarating.
3. Railway variables’ni yangilang.
4. Eski commit history’da secret qolmaganini tekshiring.

Tavsiya qilinadigan `.gitignore`:

```gitignore
.env
*.db
*.db-wal
*.db-shm
google_credentials.json
__pycache__/
*.pyc
.venv/
uploads/
data/
```

---

## Production checklist

Deploydan oldin:

- [ ] `.env` GitHub’ga commit qilinmagan.
- [ ] `BOT_TOKEN` Railway Variables’da bor.
- [ ] `ADMIN_IDS` to‘g‘ri.
- [ ] `GROUP_CHAT_ID` to‘g‘ri.
- [ ] `GOOGLE_SHEET_ID` to‘g‘ri.
- [ ] `GOOGLE_CREDS_JSON` valid JSON.
- [ ] `DB_PATH=/app/data/kkbot.db`.
- [ ] Railway volume `/app/data`ga ulangan.
- [ ] `WEB_ENABLED=1`.
- [ ] `WEB_ADMIN_PASSWORD` kuchli parol.
- [ ] `WEB_SECRET` random uzun secret.
- [ ] Google service account Sheet’ga editor qilingan.
- [ ] Migratsiya bir marta bajarilgan.
- [ ] `/health` ishlayapti.
- [ ] `/login` ochilyapti.
- [ ] `/dashboard` ochilyapti.
- [ ] `/checkin` va `/checkout` ochilyapti.
- [ ] Telegram bot `/start` javob beryapti.
- [ ] Test xodim bilan `Keldim/Ketdim` ishlayapti.
- [ ] Google Sheets export test qilingan.

---

## Qisqa start komandalar

Local:

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Railway start:

```bash
python main.py
```

Migratsiya:

```bash
python scripts/migrate_from_google_sheets.py
```

Reset + migratsiya:

```bash
python scripts/reset_and_migrate.py
```

Export:

```bash
python scripts/export_to_google_sheets.py employees
python scripts/export_to_google_sheets.py shifts
python scripts/export_to_google_sheets.py schedule
python scripts/export_to_google_sheets.py tabel --year 2026 --month 4
```

---

## Status

Ushbu versiya quyidagilarni birlashtiradi:

- SQLite asosiy baza;
- Telegram attendance bot;
- Web admin panel;
- Live dashboard;
- Xodim kabineti;
- Mobile Keldim/Ketdim scan;
- Selfie + GPS verification;
- Reference photo;
- Admin review;
- Grafik tuzish/tahrirlash;
- Bot va web hisobotlar;
- Google Sheets migratsiya/export;
- Railway deploy.

---

## License

License fayli repo ichida ko‘rinmadi. Agar loyiha ichki/private loyiha bo‘lsa, GitHub’da repository’ni private holatda saqlash tavsiya qilinadi.
