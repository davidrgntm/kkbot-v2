# KKB v2 Final Premium

Bu versiyada:

- Dashboard : live monitoring, online smenalar, real/pullik soat, pul, punctuality.
- Xodimlar : har bir xodim uchun alohida profil sahifa.
- Shaxsiy kabinet : oylik, real/yozilgan soat, grafik va smena tarixi.
- Tez grafik: guruhga chiroyli plain text yuboradi, `<b>` taglari ko'rinmaydi.
- Scroll refreshda joyida qoladi, live smena sekund va pul hisoblaydi.

Railway:

```env
DB_PATH=/app/data/kkbot.db
WEB_ENABLED=1
```

Start command:

```bash
python main.py
```

Deploy logda chiqishi kerak:

```text
Final clean web patch ulandi ✅
Final clean schedule patch ulandi ✅
[final_clean_patch] web applied
[final_clean_patch] schedule messages applied
```
