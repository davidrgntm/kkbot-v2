# KKB final version

Bu versiyada:

- Telegram bot SQLite asosiy bazadan ishlaydi.
- Google Sheets faqat migratsiya/export uchun ishlatiladi.
- Railway volume uchun to'g'ri yo'l: `DB_PATH=/app/data/kkbot.db`.
- Eski botdagi ishlangan soat hisoblash qoidasi qaytarildi:
  - 30 daqiqadan ko'p/yoki teng bo'lsa 1 soatga yaxlitlanadi;
  - yaxlitlangan soat 5 yoki undan ko'p bo'lsa 1 soat tushlik ayriladi;
  - natija doim to'liq soat: masalan `8 ч 00 м`.
- Web panel qo'shildi:
  - telefon orqali Telegram kod bilan login;
  - admin parol bilan emergency login;
  - xodim shaxsiy kabineti;
  - admin/manager panel;
  - xodimlar, shoplar, smenalar, grafik, oylik, arizalar, inventar;
  - DBga yozish/tahrirlash;
  - Google Sheets export.

## Railway variables

```env
BOT_TOKEN=...
ADMIN_IDS=806860624
GROUP_CHAT_ID=-100...
TIMEZONE=Asia/Tashkent

GOOGLE_SHEET_ID=...
GOOGLE_CREDS_JSON={...}

DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
WEB_ADMIN_PASSWORD=strong_password
WEB_SECRET=random_long_secret
```

## Railway settings

- Volume mount path: `/app/data`
- Pre-deploy Command: bo'sh
- Custom Start Command: `python main.py`

## Birinchi migratsiya / qayta migratsiya

Start Command'ni vaqtincha shunga almashtiring:

```bash
python scripts/reset_and_migrate.py
```

Deploy logda quyidagilar chiqishi kerak:

```text
Сотрудники → SQLite
Магазины → SQLite
График → SQLite
Смены → SQLite
```

Keyin Start Command'ni qaytaring:

```bash
python main.py
```

## Login

- Xodim webda telefon raqamini yozadi.
- Kod xodimning Telegram botiga keladi.
- Kod bilan shaxsiy kabinetga kiradi.
- Admin/manager ham telefon + Telegram kod orqali kiradi.
- Emergency admin login uchun `WEB_ADMIN_PASSWORD` ishlaydi.

Muhim: telefon orqali login ishlashi uchun `Сотрудники` jadvalidagi `Phone` ustuni to'ldirilgan bo'lishi kerak.
