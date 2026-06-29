from __future__ import annotations

import html
import urllib.parse
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import web_server as ws
from database.sqlite_db import db

_PREMIUM_UI_PATCHED = False
LANG_COOKIE = "kkb_lang"

PREMIUM_CSS = r'''
:root{
  --bg:#f4f7fb;--bg2:#eef3fb;--surface:#ffffff;--surface2:#f8fafc;--text:#0f172a;--muted:#64748b;--soft:#94a3b8;--line:#e2e8f0;
  --brand:#2563eb;--brand2:#1d4ed8;--brand3:#60a5fa;--green:#16a34a;--red:#dc2626;--amber:#d97706;--purple:#7c3aed;
  --shadow:0 18px 55px rgba(15,23,42,.08);--shadow2:0 8px 28px rgba(15,23,42,.08);--r:22px;--r2:16px;
}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 0%,rgba(37,99,235,.10),transparent 28%),linear-gradient(180deg,var(--bg),var(--bg2));color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased}a{text-decoration:none;color:inherit}h1,h2,h3,p{margin-top:0}h2{font-size:18px;letter-spacing:-.02em;margin-bottom:14px}.app{display:grid;grid-template-columns:292px minmax(0,1fr);min-height:100vh}.side{position:sticky;top:0;height:100vh;padding:22px 18px;background:linear-gradient(180deg,#07132c 0%,#0b1734 55%,#08111f 100%);color:#fff;z-index:50;box-shadow:14px 0 45px rgba(15,23,42,.14);overflow:auto}.logo{display:flex;align-items:center;gap:12px;margin:2px 4px 22px}.logo-badge{width:46px;height:46px;border-radius:16px;background:linear-gradient(135deg,var(--brand3),var(--brand2));display:grid;place-items:center;font-weight:950;box-shadow:0 14px 35px rgba(37,99,235,.35)}.logo-title{font-size:20px;line-height:1.05;font-weight:950;letter-spacing:-.03em}.logo-sub{font-size:12px;color:#bfdbfe;font-weight:750;margin-top:3px}.user-card{margin:0 4px 18px;padding:14px;border:1px solid rgba(255,255,255,.10);border-radius:20px;background:rgba(255,255,255,.07);backdrop-filter:blur(12px)}.user-card b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.role-pill{display:inline-flex;margin-top:8px;padding:5px 9px;border-radius:999px;background:rgba(96,165,250,.18);color:#bfdbfe;font-size:12px;font-weight:850;text-transform:uppercase;letter-spacing:.04em}.nav{display:flex;flex-direction:column;gap:6px}.nav a{display:flex;align-items:center;gap:9px;min-height:42px;padding:11px 13px;border-radius:14px;color:#cbd5e1;font-weight:780;transition:.15s ease}.nav a:hover{background:rgba(255,255,255,.08);color:#fff;transform:translateX(2px)}.nav a.active{background:linear-gradient(135deg,rgba(96,165,250,.28),rgba(37,99,235,.22));color:#fff;box-shadow:inset 0 0 0 1px rgba(191,219,254,.18)}.main{min-width:0;padding:26px 34px 30px}.mobile-head{display:none;position:sticky;top:0;z-index:80;background:#07132c;color:#fff;padding:12px 14px;align-items:center;justify-content:space-between;box-shadow:0 10px 24px rgba(15,23,42,.20)}.hamb{border:0;background:#172554;color:#fff;border-radius:12px;padding:10px 14px;font-weight:900;cursor:pointer}.top{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:22px}.h1{font-size:31px;line-height:1.08;font-weight:950;letter-spacing:-.045em}.sub{color:var(--muted);margin-top:7px;font-weight:520}.top-actions{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}.btn{border:0;background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;border-radius:13px;min-height:42px;padding:10px 15px;font-weight:850;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px;box-shadow:0 10px 24px rgba(37,99,235,.18);transition:.15s ease;white-space:nowrap}.btn:hover{transform:translateY(-1px);box-shadow:0 16px 32px rgba(37,99,235,.22)}.btn.secondary{background:#eef4ff;color:#1e40af;box-shadow:none;border:1px solid #dbeafe}.btn.gray{background:#f1f5f9;color:#0f172a;box-shadow:none;border:1px solid var(--line)}.btn.danger{background:linear-gradient(135deg,#ef4444,var(--red));box-shadow:0 12px 28px rgba(220,38,38,.18)}.grid{display:grid;gap:18px}.cards{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:18px}.card{background:rgba(255,255,255,.92);border:1px solid rgba(226,232,240,.92);border-radius:var(--r);box-shadow:var(--shadow);padding:20px;backdrop-filter:blur(10px)}.metric{position:relative;overflow:hidden}.metric:after{content:"";position:absolute;right:-34px;top:-42px;width:110px;height:110px;border-radius:999px;background:rgba(37,99,235,.08)}.metric .label{color:var(--muted);font-weight:850;position:relative;z-index:1}.metric .value{font-size:34px;font-weight:950;margin-top:6px;letter-spacing:-.045em;position:relative;z-index:1}.metric .hint{font-size:12px;color:var(--muted);margin-top:6px;font-weight:650;position:relative;z-index:1}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.form{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}.input,.select,textarea{height:42px;border:1px solid var(--line);background:#fff;border-radius:13px;padding:0 13px;font:inherit;min-width:170px;outline:none;transition:.12s ease}.input:focus,.select:focus,textarea:focus{border-color:#93c5fd;box-shadow:0 0 0 4px rgba(37,99,235,.10)}textarea{height:auto;padding:12px}.table-wrap{overflow:auto;margin:0 -2px;padding:0 2px}.table{width:100%;border-collapse:separate;border-spacing:0 9px}.table th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:0 12px;white-space:nowrap;font-weight:950}.table td{background:#fff;padding:13px 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:middle}.table tr:hover td{background:#fbfdff}.table td:first-child{border-left:1px solid var(--line);border-radius:15px 0 0 15px}.table td:last-child{border-right:1px solid var(--line);border-radius:0 15px 15px 0}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:900;background:#f1f5f9;color:#334155;white-space:nowrap}.pill.green{background:#dcfce7;color:#166534}.pill.red{background:#fee2e2;color:#991b1b}.pill.blue{background:#dbeafe;color:#1d4ed8}.pill.amber{background:#fef3c7;color:#92400e}.pill.purple{background:#ede9fe;color:#5b21b6}.split{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(320px,.75fr);gap:18px}.login{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 20% 0%,rgba(96,165,250,.28),transparent 30%),linear-gradient(135deg,#07132c,#1d4ed8)}.login-card{width:min(468px,92vw);background:rgba(255,255,255,.96);border:1px solid rgba(255,255,255,.55);border-radius:30px;padding:30px;box-shadow:0 30px 90px rgba(0,0,0,.26);backdrop-filter:blur(18px)}.login-card h1{margin:0 0 8px;font-size:31px;letter-spacing:-.04em}.login-card p{color:var(--muted);margin:0 0 18px}.login-card input{width:100%;height:50px;border:1px solid var(--line);border-radius:16px;padding:0 15px;font-size:16px;outline:none}.login-card input:focus{border-color:#93c5fd;box-shadow:0 0 0 4px rgba(37,99,235,.12)}.login-card button{width:100%;height:50px;margin-top:12px}.alert{padding:12px 14px;border-radius:14px;margin-bottom:14px;font-weight:750}.alert.ok{background:#dcfce7;color:#166534}.alert.err{background:#fee2e2;color:#991b1b}.footer{margin-top:26px;color:var(--muted);font-size:13px}.bar{height:12px;background:#e2e8f0;border-radius:999px;overflow:hidden}.bar>i{display:block;height:100%;background:linear-gradient(90deg,#60a5fa,#2563eb);border-radius:999px}.chart-row{display:grid;grid-template-columns:120px 1fr 70px;gap:10px;align-items:center;margin:10px 0}.live-list{display:grid;gap:10px}.live-item{border:1px solid var(--line);border-radius:19px;padding:14px;background:#fff;box-shadow:var(--shadow2)}.live-item .name{font-weight:950}.live-seconds{font-size:23px;font-weight:950;letter-spacing:-.03em}.avatar{width:92px;height:92px;border-radius:28px;object-fit:cover;background:#e2e8f0;display:inline-grid;place-items:center;font-size:34px}.mini{font-size:12px;color:var(--muted);font-weight:600}.muted{color:var(--muted)}.lang-switch{height:42px;display:inline-flex;align-items:center;gap:8px;border:1px solid #dbeafe;background:#fff;border-radius:999px;padding:5px 8px;box-shadow:var(--shadow2);user-select:none}.lang-switch span{font-size:12px;font-weight:950;color:#94a3b8;min-width:24px;text-align:center}.lang-switch span.active{color:#1d4ed8}.language-toggle{position:relative;width:54px;height:30px;display:inline-flex;align-items:center;cursor:pointer}.language-toggle input{display:none}.language-toggle i{position:absolute;inset:0;border-radius:999px;background:#dbeafe;border:1px solid #bfdbfe;transition:.18s ease}.language-toggle i:before{content:"";position:absolute;width:24px;height:24px;left:2px;top:2px;border-radius:50%;background:linear-gradient(135deg,#fff,#eef2ff);box-shadow:0 5px 12px rgba(15,23,42,.20);transition:.18s ease}.language-toggle input:checked+i{background:linear-gradient(135deg,#2563eb,#1d4ed8);border-color:#1d4ed8}.language-toggle input:checked+i:before{transform:translateX(24px)}.side .lang-switch{width:100%;justify-content:center;margin-top:18px;background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.12);box-shadow:none}.side .lang-switch span{color:#93c5fd}.side .lang-switch span.active{color:#fff}.side .language-toggle i{background:rgba(255,255,255,.20);border-color:rgba(255,255,255,.20)}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.split{grid-template-columns:1fr}}@media(max-width:980px){.mobile-head{display:flex}.app{display:block}.side{display:none;height:auto;position:sticky;top:52px;border-radius:0 0 24px 24px}.side.open{display:block}.nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.main{padding:18px}.top{align-items:center}.h1{font-size:27px}.top-actions{justify-content:flex-start}}@media(max-width:640px){.cards{grid-template-columns:1fr}.form{display:grid}.input,.select,.btn,textarea{width:100%}.h1{font-size:24px}.nav{grid-template-columns:1fr}.table td,.table th{font-size:13px;padding:10px}.chart-row{grid-template-columns:90px 1fr 55px}.metric .value{font-size:30px}.top{display:block}.top-actions{margin-top:14px}.lang-switch{width:100%;justify-content:center}.main{padding:14px}.card{padding:16px;border-radius:18px}}
'''

RU_REPLACEMENTS = {
    "Kabinetim": "Кабинет", "Shaxsiy kabinet": "Личный кабинет", "O‘z smena, oylik, rasm va arizalaringiz": "Ваши смены, зарплата, фото и заявки",
    "Dashboard": "Дашборд", "Xodimlar": "Сотрудники", "Xodim": "Сотрудник", "Shoplar": "Филиалы", "Shop": "Филиал", "Filiallar": "Филиалы",
    "Smenalarim": "Мои смены", "Smenalar": "Смены", "Smena": "Смена", "Grafikim": "Мой график", "Grafik": "График",
    "Tez grafik": "Быстрый график", "Oylik": "Зарплата", "Arizalar": "Заявки", "Inventar": "Инвентарь", "Hisobotlar": "Отчёты",
    "Chiqish": "Выйти", "Yangilash": "Обновить", "Qidirish": "Поиск", "Tozalash": "Очистить", "Ochish": "Открыть",
    "Qo‘shish": "Добавить", "Saqlash": "Сохранить", "O‘chirish": "Удалить", "Hisoblash": "Рассчитать", "Yuborish": "Отправить",
    "Faol xodimlar": "Активные сотрудники", "bazadagi active xodimlar": "активные в базе", "Hozir ishda": "Сейчас на смене",
    "live ochiq smena": "открытые live-смены", "Bugun yopilgan": "Закрыто сегодня", "closed smenalar": "закрытые смены",
    "Bu oy yozilgan": "За месяц оплачено", "Bu oy real": "За месяц фактически", "pullik soat": "оплачиваемые часы", "fakt ishlagan vaqt": "фактическое время",
    "real ": "факт ", " soat": " ч", "Online smenalar": "Онлайн-смены", "Hozir ochiq smena yo‘q.": "Сейчас нет открытых смен.",
    "Hozir qaysi magazinda nechta odam?": "Сколько людей сейчас по филиалам?", "Bugungi punctuality": "Сегодняшняя пунктуальность",
    "Vaqtida": "Вовремя", "Kechikdi": "Опоздал", "Erta keldi": "Пришёл раньше", "Rejasiz": "Без графика", "Reja xato": "Ошибка графика",
    "Oxirgi smenalar": "Последние смены", "reja / fakt / hisob": "план / факт / расчёт", "Yangilandi": "Обновлено",
    "Ism": "Имя", "Rol": "Роль", "Reja": "План", "Keldi": "Пришёл", "Ketdi": "Ушёл", "Holat": "Статус", "Real ishladi": "Фактически", "Yozildi": "Оплачено", "Pul": "Сумма",
    "Sana": "Дата", "Boshlanish": "Начало", "Tugash": "Конец", "Tur": "Тип", "Stavka": "Ставка", "Jami": "Итого", "Soni": "Количество",
    "Yangi xodim": "Новый сотрудник", "Yangi shop": "Новый филиал", "Nom": "Название", "GPS va radius": "GPS и радиус",
    "Xodim topilmadi": "Сотрудник не найден", "Topilmadi": "Не найдено", "Xodim profili": "Профиль сотрудника", "Tezkor harakat": "Быстрые действия",
    "Smenyini ko‘rish": "Посмотреть смены", "Grafigini ko‘rish": "Посмотреть график", "Deaktivatsiya": "Деактивация",
    "Smenalar": "Смены", "ta qator": "строк", "qator": "строк", "Filter": "Фильтр", "Holati": "Статус",
    "Smena qo‘shish": "Добавить смену", "Smenani tahrirlash": "Редактировать смену", "Smena topilmadi": "Смена не найдена", "Smena edit": "Редактирование смены",
    "Sana oralig‘i, eski yaxlitlash qoidasi va tushlik ayrimi bilan": "Период, округление и обед по правилам старого бота",
    "Bu oy": "Этот месяц", "16–oy oxiri": "16–конец месяца", "Jami oylik": "Итого зарплата", "tushlik": "обед",
    "Ariza yuborish": "Отправить заявку", "Sabab": "Причина", "Dam olish": "Выходной", "Otpusk": "Отпуск", "Bolnichniy": "Больничный", "Boshqa": "Другое",
    "Narsa": "Предмет", "Narsa nomi": "Название предмета", "Berilgan sana": "Дата выдачи", "Inventar berish": "Выдать инвентарь",
    "Google Sheetsga hisobot chiqarish": "Выгрузка отчёта в Google Sheets", "Oy tabeli": "Табель за месяц", "Tabel export": "Экспорт табеля",
    "Barcha shoplar": "Все филиалы", "Ma'lumot yo‘q": "Нет данных", "Ma’lumot yo‘q": "Нет данных", "so‘m": "сум", "so'm": "сум",
    "Ish smenasi": "Рабочая смена", "Ishda": "На смене", "Damda ishda emas": "Сейчас не на смене", "hozircha": "пока", "Rasmni saqlash": "Сохранить фото",
    "Copy-paste grafikni avtomatik jadvalga aylantirish": "Автоматическое превращение copy-paste графика в таблицу", "Preview natijasi": "Результат предпросмотра",
    "Xatolarni tuzatish kerak": "Нужно исправить ошибки", "Konflikt topildi": "Найден конфликт", "Saqlash xatosi": "Ошибка сохранения", "Bazaga yozishda xatolik chiqdi.": "Ошибка записи в базу.",
    "Xatolar bor. Avval matnni tuzating.": "Есть ошибки. Сначала исправьте текст.", "Boshqaruv paneli": "Панель управления",
}

UZ_REPLACEMENTS = {
    "Дашборд": "Dashboard", "Кабинет": "Kabinet", "Личный кабинет": "Shaxsiy kabinet", "Сотрудники": "Xodimlar", "Сотрудник": "Xodim", "Филиалы": "Filiallar", "Филиал": "Filial",
    "Смены": "Smenalar", "Смена": "Smena", "Мои смены": "Smenalarim", "График": "Grafik", "Мой график": "Grafikim", "Быстрый график": "Tez grafik",
    "Зарплата": "Oylik", "Заявки": "Arizalar", "Инвентарь": "Inventar", "Отчёты": "Hisobotlar", "AI-проверка": "AI tekshiruv",
    "Выйти": "Chiqish", "Обновить": "Yangilash", "Поиск": "Qidirish", "Очистить": "Tozalash", "Открыть": "Ochish", "Добавить": "Qo‘shish", "Сохранить": "Saqlash", "Удалить": "O‘chirish",
    "Рассчитать": "Hisoblash", "Отправить": "Yuborish", "Активные сотрудники": "Faol xodimlar", "активные в базе": "bazadagi active xodimlar", "Сейчас на смене": "Hozir ishda",
    "открытые live-смены": "live ochiq smena", "Закрыто сегодня": "Bugun yopilgan", "закрытые смены": "closed smenalar", "За месяц оплачено": "Bu oy yozilgan",
    "За месяц фактически": "Bu oy real", "оплачиваемые часы": "pullik soat", "фактическое время": "fakt ishlagan vaqt", "факт ": "real ",
    "Онлайн-смены": "Online smenalar", "Сейчас нет открытых смен.": "Hozir ochiq smena yo‘q.", "Сколько людей сейчас по филиалам?": "Hozir qaysi filialda nechta odam?",
    "Сегодняшняя пунктуальность": "Bugungi punktuallik", "Вовремя": "Vaqtida", "Опоздал": "Kechikdi", "Пришёл раньше": "Erta keldi", "Без графика": "Rejasiz", "Ошибка графика": "Grafik xatosi",
    "Последние смены": "Oxirgi smenalar", "план / факт / расчёт": "reja / fakt / hisob", "Обновлено": "Yangilandi", "Имя": "Ism", "Роль": "Rol", "План": "Reja",
    "Пришёл": "Keldi", "Ушёл": "Ketdi", "Статус": "Holat", "Фактически": "Real ishladi", "Оплачено": "Yozildi", "Сумма": "Pul", "Дата": "Sana", "Начало": "Boshlanish", "Конец": "Tugash",
    "Тип": "Tur", "Ставка": "Stavka", "Итого": "Jami", "Количество": "Soni", "Новый сотрудник": "Yangi xodim", "Новый филиал": "Yangi filial", "Название": "Nom",
    "GPS и радиус": "GPS va radius", "Сотрудник не найден": "Xodim topilmadi", "Не найдено": "Topilmadi", "Профиль сотрудника": "Xodim profili", "Быстрые действия": "Tezkor harakat",
    "Посмотреть смены": "Smenalarni ko‘rish", "Посмотреть график": "Grafikni ko‘rish", "Деактивация": "Deaktivatsiya", "строк": "qator", "Фильтр": "Filter",
    "Добавить смену": "Smena qo‘shish", "Редактировать смену": "Smenani tahrirlash", "Смена не найдена": "Smena topilmadi", "Редактирование смены": "Smena edit",
    "Период, округление и обед по правилам старого бота": "Sana oralig‘i, eski yaxlitlash qoidasi va tushlik ayrimi bilan", "Этот месяц": "Bu oy", "16–конец месяца": "16–oy oxiri",
    "Итого зарплата": "Jami oylik", "обед": "tushlik", "Отправить заявку": "Ariza yuborish", "Причина": "Sabab", "Выходной": "Dam olish", "Отпуск": "Otpusk",
    "Больничный": "Bolnichniy", "Другое": "Boshqa", "Предмет": "Narsa", "Название предмета": "Narsa nomi", "Дата выдачи": "Berilgan sana", "Выдать инвентарь": "Inventar berish",
    "Выгрузка отчёта в Google Sheets": "Google Sheetsga hisobot chiqarish", "Табель за месяц": "Oy tabeli", "Экспорт табеля": "Tabel export", "Все филиалы": "Barcha filiallar",
    "Нет данных": "Ma'lumot yo‘q", "сум": "so‘m", "Рабочая смена": "Ish smenasi", "На смене": "Ishda", "Сейчас не на смене": "Damda ishda emas", "пока": "hozircha",
    "Сохранить фото": "Rasmni saqlash", "Автоматическое превращение copy-paste графика в таблицу": "Copy-paste grafikni avtomatik jadvalga aylantirish", "Результат предпросмотра": "Preview natijasi",
    "Нужно исправить ошибки": "Xatolarni tuzatish kerak", "Найден конфликт": "Konflikt topildi", "Ошибка сохранения": "Saqlash xatosi", "Ошибка записи в базу.": "Bazaga yozishda xatolik chiqdi.",
    "Есть ошибки. Сначала исправьте текст.": "Xatolar bor. Avval matnni tuzating.", "Панель управления": "Boshqaruv paneli", "Телефон": "Telefon", "Получить код": "Kod olish", "Войти": "Kirish",
    "Вход по паролю администратора": "Admin parol bilan kirish", "Войти как админ": "Admin kirish", "Введите телефон. Код придёт через Telegram-бот.": "Telefon raqamingizni kiriting. Kod Telegram bot orqali keladi.",
    "Код отправлен в Telegram. Введите код.": "Kod Telegramga yuborildi. Kodni kiriting.", "Неверный пароль администратора": "Admin parol noto‘g‘ri",
}


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def current_lang(request: Request | None) -> str:
    raw = ""
    try:
        raw = str(request.query_params.get("lang") or request.cookies.get(LANG_COOKIE) or "") if request else ""
    except Exception:
        raw = ""
    return "uz" if raw.lower().startswith("uz") else "ru"


def translate_html(text: Any, lang: str = "ru") -> str:
    out = str(text if text is not None else "")
    # Pull the older replacement list from stable patch if it is already loaded.
    repl: dict[str, str] = {}
    if lang == "ru":
        try:
            import kkb_stable_patch as ksp  # noqa: WPS433
            repl.update(getattr(ksp, "RU_REPLACEMENTS", {}) or {})
        except Exception:
            pass
        repl.update(RU_REPLACEMENTS)
    else:
        repl.update(UZ_REPLACEMENTS)
    for src, dst in sorted(repl.items(), key=lambda item: len(item[0]), reverse=True):
        out = out.replace(src, dst)
    return out


def lang_switch_html(lang: str) -> str:
    checked = "checked" if lang == "uz" else ""
    ru_active = "active" if lang == "ru" else ""
    uz_active = "active" if lang == "uz" else ""
    return f"""
    <div class="lang-switch" title="RU / UZ">
      <span class="{ru_active}">RU</span>
      <label class="language-toggle"><input type="checkbox" {checked} onchange="KKBSetLanguage(this.checked?'uz':'ru')"><i></i></label>
      <span class="{uz_active}">UZ</span>
    </div>
    <script>
    window.KKB_LANG='{lang}';
    function KKBSetLanguage(lang){{
      const next=encodeURIComponent(location.pathname+location.search);
      location.href='/set-language?lang='+lang+'&next='+next;
    }}
    </script>
    """


def _remove_route(app, path: str, method: str = "GET") -> None:
    app.router.routes = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path and method in getattr(r, "methods", set()))
    ]


def _nav_items(admin: bool, lang: str) -> list[tuple[str, str, str]]:
    if lang == "uz":
        if admin:
            return [
                ("dashboard", "/dashboard", "🏠 Dashboard"),
                ("verification", "/verification", "🧠 AI tekshiruv"),
                ("employees", "/employees", "👥 Xodimlar"),
                ("shops", "/shops", "🏪 Filiallar"),
                ("shifts", "/shifts", "🟢 Smenalar"),
                ("schedule", "/schedule", "📅 Grafik"),
                ("quick_schedule", "/quick-schedule", "⚡ Tez grafik"),
                ("salary", "/salary", "💰 Oylik"),
                ("requests", "/requests", "📝 Arizalar"),
                ("inventory", "/inventory", "📦 Inventar"),
                ("reports", "/reports", "🧾 Hisobotlar"),
                ("export", "/export", "📤 Export"),
            ]
        return [
            ("cabinet", "/cabinet", "👤 Kabinet"),
            ("checkin", "/checkin", "🟢 Keldim"),
            ("checkout", "/checkout", "🔴 Ketdim"),
            ("my_schedule", "/schedule", "📅 Grafikim"),
            ("my_shifts", "/shifts", "🟢 Smenalarim"),
        ]
    if admin:
        return [
            ("dashboard", "/dashboard", "🏠 Дашборд"),
            ("verification", "/verification", "🧠 AI-проверка"),
            ("employees", "/employees", "👥 Сотрудники"),
            ("shops", "/shops", "🏪 Филиалы"),
            ("shifts", "/shifts", "🟢 Смены"),
            ("schedule", "/schedule", "📅 График"),
            ("quick_schedule", "/quick-schedule", "⚡ Быстрый график"),
            ("salary", "/salary", "💰 Зарплата"),
            ("requests", "/requests", "📝 Заявки"),
            ("inventory", "/inventory", "📦 Инвентарь"),
            ("reports", "/reports", "🧾 Отчёты"),
            ("export", "/export", "📤 Экспорт"),
        ]
    return [
        ("cabinet", "/cabinet", "👤 Кабинет"),
        ("checkin", "/checkin", "🟢 Пришёл"),
        ("checkout", "/checkout", "🔴 Ушёл"),
        ("my_schedule", "/schedule", "📅 Мой график"),
        ("my_shifts", "/shifts", "🟢 Мои смены"),
    ]


def premium_nav(active: str, user: dict, lang: str = "ru") -> str:
    admin = ws.is_admin(user)
    items = _nav_items(admin, lang)
    def is_active(key: str) -> bool:
        return key == active or (key == "quick_schedule" and active in {"quick", "quick-schedule"})
    links = "".join(f'<a class="{"active" if is_active(k) else ""}" href="{h}">{lab}</a>' for k, h, lab in items)
    logout = "Chiqish" if lang == "uz" else "Выйти"
    role = esc(user.get("role") or "")
    return f"""
    <aside class="side" id="sideNav">
      <div class="logo"><div class="logo-badge">K</div><div><div class="logo-title">KKB</div><div class="logo-sub">Web Panel</div></div></div>
      <div class="user-card"><b>{esc(user.get('name') or 'User')}</b><span class="role-pill">{role}</span></div>
      <nav class="nav">{links}</nav>
      {lang_switch_html(lang)}
      <form method="post" action="/logout" style="margin-top:18px"><button class="btn gray" style="width:100%">{logout}</button></form>
    </aside>
    """


def premium_layout(request: Request, active: str, title: str, subtitle: str, content: str) -> HTMLResponse:
    lang = current_lang(request)
    user = ws.current_user(request) or {"name": "", "role": ""}
    title_i = translate_html(title, lang)
    subtitle_i = translate_html(subtitle, lang)
    content_i = translate_html(content, lang)
    menu = "Menu" if lang == "uz" else "Меню"
    refresh = "Yangilash" if lang == "uz" else "Обновить"
    panel = "Boshqaruv paneli" if lang == "uz" else "Панель управления"
    mobile = f"<div class='mobile-head'><b>KKB · {esc(title_i)}</b><button class='hamb' onclick=\"document.getElementById('sideNav').classList.toggle('open')\">☰ {menu}</button></div>"
    extra_css = ""
    try:
        import kkb_stable_patch as ksp  # noqa: WPS433
        extra_css = getattr(ksp, "EXTRA_CSS", "") or ""
    except Exception:
        extra_css = ""
    script = """
    <script>
    window.addEventListener('beforeunload',()=>sessionStorage.setItem('scrollY', String(window.scrollY||0)));
    window.addEventListener('load',()=>{const y=sessionStorage.getItem('scrollY'); if(y){setTimeout(()=>window.scrollTo(0, Number(y)),30)}});
    </script>
    """
    return HTMLResponse(f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title_i)} · KKB</title><style>{ws.CSS}{extra_css}</style></head>
    <body>{mobile}<div class="app">{premium_nav(active, user, lang)}<main class="main"><div class="top"><div><div class="h1">{esc(title_i)}</div><div class="sub">{subtitle_i}</div></div><div class="top-actions">{lang_switch_html(lang)}<button class="btn secondary" onclick="if(window.softRefresh)softRefresh();else location.reload()">{refresh}</button></div></div>{content_i}<div class="footer">KKB Web Panel · {panel} · Company: {esc(db._current_cid())}</div></main></div>{script}</body></html>""")


def _premium_login_page(request: Request, error: str = "", sent: str = "", phone: str = "") -> HTMLResponse:
    lang = current_lang(request)
    if lang == "uz":
        title = "KKB Web Panel"
        subtitle = "Telefon raqamingizni kiriting. Kod Telegram bot orqali keladi."
        get_code = "Kod olish"
        phone_ph = "Telefon: +998..."
        code_ph = "6 xonali kod"
        enter = "Kirish"
        admin_summary = "Admin parol bilan kirish"
        admin_enter = "Admin kirish"
        sent_text = "Kod Telegramga yuborildi. Kodni kiriting."
    else:
        title = "KKB Web Panel"
        subtitle = "Введите телефон. Код придёт через Telegram-бот."
        get_code = "Получить код"
        phone_ph = "Телефон: +998..."
        code_ph = "6-значный код"
        enter = "Войти"
        admin_summary = "Вход по паролю администратора"
        admin_enter = "Войти как админ"
        sent_text = "Код отправлен в Telegram. Введите код."
    alert = ""
    if error:
        alert = f"<div class='alert err'>{translate_html(esc(error), lang)}</div>"
    if sent:
        alert = f"<div class='alert ok'>{sent_text}</div>"
    return HTMLResponse(f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Login · KKB</title><style>{ws.CSS}</style></head>
    <body class="login"><div class="login-card"><div class="row" style="justify-content:space-between;margin-bottom:18px"><div><h1>{title}</h1><p>{subtitle}</p></div>{lang_switch_html(lang)}</div>{alert}
    <form method="post" action="/login/request"><input name="phone" value="{esc(phone)}" placeholder="{phone_ph}" required><button class="btn">{get_code}</button></form>
    <form method="post" action="/login/verify"><input name="phone" value="{esc(phone)}" placeholder="{phone_ph}" required style="margin-top:12px"><input name="code" placeholder="{code_ph}" required style="margin-top:12px"><button class="btn">{enter}</button></form>
    <details style="margin-top:18px"><summary>{admin_summary}</summary><form method="post" action="/login/password"><input type="password" name="password" placeholder="WEB_ADMIN_PASSWORD" style="margin-top:12px"><button class="btn gray">{admin_enter}</button></form></details>
    </div></body></html>""")


def apply_premium_ui_patch(app) -> None:
    global _PREMIUM_UI_PATCHED
    if _PREMIUM_UI_PATCHED:
        return
    _PREMIUM_UI_PATCHED = True

    ws.CSS = PREMIUM_CSS
    ws.current_lang = current_lang  # type: ignore[attr-defined]
    ws.translate_html = translate_html  # type: ignore[attr-defined]
    ws.lang_switch_html = lang_switch_html  # type: ignore[attr-defined]
    ws.nav = premium_nav  # type: ignore[assignment]
    ws.layout = premium_layout  # type: ignore[assignment]

    try:
        import kkb_stable_patch as ksp  # noqa: WPS433
        ksp.stable_nav = premium_nav  # type: ignore[assignment]
        ksp.stable_layout = premium_layout  # type: ignore[assignment]
        ksp.ru_html = lambda text: translate_html(text, "ru")  # type: ignore[assignment]
    except Exception:
        pass

    if not any(getattr(r, "path", None) == "/set-language" for r in app.router.routes):
        @app.get("/set-language")
        async def set_language(lang: str = "ru", next: str = "/dashboard"):
            selected = "uz" if str(lang).lower().startswith("uz") else "ru"
            target = urllib.parse.unquote(next or "/dashboard")
            if not target.startswith("/") or target.startswith("//"):
                target = "/dashboard"
            res = RedirectResponse(target, status_code=303)
            res.set_cookie(LANG_COOKIE, selected, max_age=60 * 60 * 24 * 365, httponly=False, samesite="lax")
            return res

    _remove_route(app, "/login", "GET")
    app.get("/login", response_class=HTMLResponse)(_premium_login_page)

    _remove_route(app, "/api/dashboard/live", "GET")

    @app.get("/api/dashboard/live")
    async def premium_api_dashboard_live(request: Request):
        if ws.require_admin(request):
            return HTMLResponse("unauthorized", status_code=401)
        html_text = ws._render_dashboard(ws._dashboard_payload())
        return HTMLResponse(translate_html(html_text, current_lang(request)))

    print("[premium_ui_patch] applied: language slider RU/UZ and polished web UI")
