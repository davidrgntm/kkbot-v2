import calendar
from datetime import date
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# --- ASOSIY MENYU ---
def main_menu(role: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🟢 Keldim"), KeyboardButton(text="🔴 Ketdim"))
    builder.row(KeyboardButton(text="📅 Grafik"), KeyboardButton(text="👤 Kabinetim"))
    builder.row(KeyboardButton(text="📊 Statistika"))

    if role in ["admin", "manager"]:
        builder.row(KeyboardButton(text="🧾 Hisobotlar"), KeyboardButton(text="🧩 Grafik tuzish"))
        builder.row(KeyboardButton(text="📆 Umumiy grafik"), KeyboardButton(text="✏️ Grafik tahrirlash"))
        builder.row(KeyboardButton(text="👥 Xodimlar"), KeyboardButton(text="⚙️ Admin Panel"))

    return builder.as_markup(resize_keyboard=True)


def request_location() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📍 Lokatsiyani yuborish", request_location=True)],
        [KeyboardButton(text="🔙 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# --- ESKI MENYULAR (MOSLIK UCHUN) ---
def stats_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="7 kunlik"), KeyboardButton(text="Bu oy"))
    builder.row(KeyboardButton(text="⬅ Назад"))
    return builder.as_markup(resize_keyboard=True)


def schedule_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Bugun"), KeyboardButton(text="Ertaga"))
    builder.row(KeyboardButton(text="Bu hafta"), KeyboardButton(text="Kelasi hafta"))
    builder.row(KeyboardButton(text="⬅ Назад"))
    return builder.as_markup(resize_keyboard=True)


# ==========================================
# 🗓 DINAMIK KALENDAR
# ==========================================
def build_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    month_name = calendar.month_name[month]
    builder.row(InlineKeyboardButton(text=f"{month_name} {year}", callback_data="ignore"))

    days = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
    header_row = [InlineKeyboardButton(text=day, callback_data="ignore") for day in days]
    builder.row(*header_row)

    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row_buttons = []
        for day in week:
            if day == 0:
                row_buttons.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                date_str = f"{day:02d}-{month:02d}-{year}"
                row_buttons.append(InlineKeyboardButton(text=str(day), callback_data=f"cal_date_{date_str}"))
        builder.row(*row_buttons)

    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    builder.row(
        InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"cal_nav_{prev_y}_{prev_m}"),
        InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"cal_nav_{next_y}_{next_m}"),
    )
    return builder.as_markup()


# ==========================================
# ⏰ VAQT TANLASH
# ==========================================
def build_time_picker(prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    day_hours = list(range(8, 24))
    night_hours = [0, 1, 2]

    for h in (day_hours + night_hours):
        time_str = f"{h:02d}:00"
        builder.button(text=time_str, callback_data=f"{prefix}_{time_str}")

    builder.adjust(4)
    return builder.as_markup()


# ==========================================
# 🔄 GRAFIK TASDIQLASH
# ==========================================
def confirm_schedule_kb(repeat_weeks: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Yana xodim qo'shish", callback_data="sch_add_more")
    builder.button(text="🏪 Boshqa magazin tanlash", callback_data="sch_change_shop")
    builder.button(text="🗑 Oxirgi batchni olib tashlash", callback_data="sch_remove_last")
    builder.button(text=f"🔁 Repeat: {repeat_weeks} hafta", callback_data="sch_set_repeat")
    builder.button(text="✅ Grafikni saqlash", callback_data="sch_finish_save")
    builder.button(text="❌ Bekor qilish", callback_data="sch_cancel")
    builder.adjust(1)
    return builder.as_markup()


# ==========================================
# ⚡ STATUS + MANUAL TIME
# ==========================================
def shift_templates_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 Dam olish", callback_data="status|day_off")
    builder.button(text="🏖 отпуск", callback_data="status|vacation")
    builder.button(text="🤒 больничный", callback_data="status|sick_leave")
    builder.button(text="⏰ Boshlanish vaqtini tanlash", callback_data="tpl|custom|custom")
    builder.button(text="⬅ Xodimlarga qaytish", callback_data="sch_back_to_employee")
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


# ==========================================
# 🔁 REPEAT TANLASH
# ==========================================
def repeat_weeks_kb(current: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for weeks in [0, 1, 2, 3, 4]:
        marker = "✅ " if weeks == current else ""
        label = "Faqat shu hafta" if weeks == 0 else f"{weeks} hafta repeat"
        builder.button(text=f"{marker}{label}", callback_data=f"sch_repeat_{weeks}")
    builder.button(text="⬅ Orqaga", callback_data="sch_repeat_back")
    builder.adjust(1)
    return builder.as_markup()


# ==========================================
# 📢 PUBLISH CONFIRMATION
# ==========================================
def publish_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Guruhga jo'natish", callback_data="sch_publish_yes")
    builder.button(text="🙈 Faqat saqlash", callback_data="sch_publish_no")
    builder.adjust(1)
    return builder.as_markup()


def send_to_group_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Guruhga jo'natish", callback_data="sch_broadcast_now")
    return builder.as_markup()


# ==========================================
# 👤 KABINET / ANALYTICS
# ==========================================
def cabinet_home_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Statistika", callback_data="cab_stats_home")
    builder.button(text="💸 Oyligim", callback_data="cab_salary_home")
    builder.button(text="🗓 Oyma-oy", callback_data="cab_months_home")
    builder.button(text="🙂 Smaylik", callback_data="cab_smile_home")
    if is_admin:
        builder.button(text="👥 Xodimlar markazi", callback_data="cab_open_staff")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def period_selector_kb(
    prefix: str,
    selected: str | None = None,
    include_back: str | None = None,
    pay_period_offset: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ("7 kun", "7d"),
        ("30 kun", "30d"),
        ("Bu oy", "m0"),
        ("O'tgan oy", "m1"),
    ]
    for label, key in items:
        text = f"✅ {label}" if selected == key else label
        builder.button(text=text, callback_data=f"{prefix}{key}")

    offset = int(pay_period_offset or 0)
    pay_items = [
        ("⬅️ Oldingi davr", f"payo:{offset - 1}"),
        ("Joriy davr", "payo:0"),
        ("Keyingi davr ➡️", f"payo:{offset + 1}"),
    ]
    for label, key in pay_items:
        text = f"✅ {label}" if selected == key else label
        builder.button(text=text, callback_data=f"{prefix}{key}")

    if include_back:
        builder.button(text="⬅ Orqaga", callback_data=include_back)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def month_breakdown_kb(prefix: str, months: list[str], selected: str | None = None, include_back: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in months:
        text = f"✅ {item}" if item == selected else item
        builder.button(text=text, callback_data=f"{prefix}{item}")
    if include_back:
        builder.button(text="⬅ Orqaga", callback_data=include_back)
    builder.adjust(2)
    return builder.as_markup()


def smile_picker_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for emoji in ["🙂", "😎", "🔥", "⭐", "💪", "🧁", "🚀", "💎"]:
        builder.button(text=emoji, callback_data=f"cab_smile_set|{emoji}")
    builder.button(text="⬅ Orqaga", callback_data="cab_home")
    builder.adjust(4, 4, 1)
    return builder.as_markup()


# ==========================================
# 👥 XODIMLAR MARKAZI
# ==========================================
def staff_center_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📡 Online", callback_data="stf_home_online")
    builder.button(text="📚 Katalog", callback_data="stf_home_catalog")
    builder.button(text="📊 Analitika", callback_data="stf_home_analytics")
    builder.button(text="🔍 Qidirish", callback_data="stf_home_search")
    builder.adjust(2, 2)
    return builder.as_markup()


def staff_catalog_kb(items: list[tuple[str, str]], page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Har bir xodim alohida qatorda ko'rinsin.
    # Aks holda Telegram barcha tugmalarni bitta qatorga siqib,
    # matnni faqat emoji + "..." ko'rinishiga tushirib yuboradi.
    for tid, label in items:
        builder.row(
            InlineKeyboardButton(
                text=(label[:64] + "…") if len(label) > 64 else label,
                callback_data=f"stf_pick|{tid}",
            )
        )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"stf_page|{page-1}"))

    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="ignore"))

    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"stf_page|{page+1}"))

    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="🔍 Qidirish", callback_data="stf_home_search"),
        InlineKeyboardButton(text="🏠 Markaz", callback_data="stf_home"),
    )
    return builder.as_markup()


def staff_profile_kb(tid: str, can_edit: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Statistika", callback_data=f"stf_stats|{tid}|m0")
    builder.button(text="💸 Oylik", callback_data=f"stf_salary|{tid}")
    builder.button(text="🗓 Oyma-oy", callback_data=f"stf_months|{tid}")
    if can_edit:
        builder.button(text="💰 Stavka", callback_data=f"stf_rate|{tid}")
        builder.button(text="🙂 Smaylik", callback_data=f"stf_emoji|{tid}")
        builder.button(text="🗑 O'chirish", callback_data=f"stf_delete|{tid}")
    builder.button(text="⬅ Katalog", callback_data="stf_home_catalog")
    builder.button(text="🏠 Markaz", callback_data="stf_home")
    builder.adjust(2, 1, 2, 2)
    return builder.as_markup()


# --- backward compatibility for admin_schedule.py ---
def schedule_kind_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 Dam olish", callback_data="sch_kind_day_off")
    builder.button(text="🏖 отпуск", callback_data="sch_kind_vacation")
    builder.button(text="🤒 больничный", callback_data="sch_kind_sick_leave")
    builder.button(text="⏰ Ish vaqti tanlash", callback_data="sch_kind_shift")
    builder.button(text="⏭ O'tkazib yuborish", callback_data="sch_kind_skip")
    builder.button(text="⬅ Xodimlarga qaytish", callback_data="sch_back_to_employee")
    builder.adjust(2, 1, 1, 1, 1)
    return builder.as_markup()
