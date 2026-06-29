from __future__ import annotations

import calendar
from datetime import datetime, timedelta, date
from contextlib import suppress

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from database.sqlite_db import db
from keyboards.builders import (
    cabinet_home_kb,
    period_selector_kb,
    month_breakdown_kb,
    smile_picker_kb,
    schedule_menu,
)

router = Router()
router.message.filter(F.chat.type == "private")


class ReportState(StatesGroup):
    viewing = State()


STATUS_LABELS = {
    "day_off": "Dam olish",
    "vacation": "отпуск",
    "sick_leave": "больничный",
}


def _fmt_money(value: float) -> str:
    return f"{round(float(value or 0)):,}".replace(",", " ") + " so'm"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def _pay_period_label(start: date, end: date) -> str:
    if start.day == 1:
        return f"25-sana to'lovi ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    return f"10-sana to'lovi ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"


def _next_pay_period(start: date, end: date) -> tuple[date, date, str]:
    if start.day == 1:
        next_start = date(start.year, start.month, 16)
        next_end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    else:
        ny, nm = _shift_month(start.year, start.month, 1)
        next_start = date(ny, nm, 1)
        next_end = date(ny, nm, 15)
    return next_start, next_end, _pay_period_label(next_start, next_end)


def _previous_pay_period_from_bounds(start: date, end: date) -> tuple[date, date, str]:
    if start.day == 1:
        py, pm = _shift_month(start.year, start.month, -1)
        prev_start = date(py, pm, 16)
        prev_end = date(py, pm, calendar.monthrange(py, pm)[1])
    else:
        prev_start = date(start.year, start.month, 1)
        prev_end = date(start.year, start.month, 15)
    return prev_start, prev_end, _pay_period_label(prev_start, prev_end)


def _pay_period_by_offset(today: date, offset: int) -> tuple[date, date, str]:
    start, end, label = _current_pay_period(today)
    if offset == 0:
        return start, end, label
    if offset > 0:
        for _ in range(offset):
            start, end, label = _next_pay_period(start, end)
        return start, end, label
    for _ in range(abs(offset)):
        start, end, label = _previous_pay_period_from_bounds(start, end)
    return start, end, label


def _pay_offset_from_key(key: str) -> int:
    if key == "pay":
        return 0
    if key == "payprev":
        return -1
    if key.startswith("payo:"):
        try:
            return int(key.split(":", 1)[1])
        except Exception:
            return 0
    return 0


def _period_by_key(key: str) -> tuple[date, date, str]:
    today = datetime.now().date()
    if key == "7d":
        return today - timedelta(days=6), today, "Oxirgi 7 kun"
    if key == "30d":
        return today - timedelta(days=29), today, "Oxirgi 30 kun"
    if key == "m1":
        y, m = _shift_month(today.year, today.month, -1)
        s, e = _month_bounds(y, m)
        return s, e, f"{calendar.month_name[m]} {y}"
    if key in {"pay", "payprev"} or key.startswith("payo:"):
        return _pay_period_by_offset(today, _pay_offset_from_key(key))
    s, e = _month_bounds(today.year, today.month)
    return s, e, f"{calendar.month_name[today.month]} {today.year}"


def _current_pay_period(today: date) -> tuple[date, date, str]:
    if today.day <= 10:
        py, pm = _shift_month(today.year, today.month, -1)
        start = date(py, pm, 16)
        end = date(py, pm, calendar.monthrange(py, pm)[1])
        return start, end, f"10-sana to'lovi ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    if today.day <= 25:
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, 15)
        return start, end, f"25-sana to'lovi ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    start = date(today.year, today.month, 16)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    ny, nm = _shift_month(today.year, today.month, 1)
    return start, end, f"10-sana to'lovi ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"


def _previous_pay_period(today: date) -> tuple[date, date, str]:
    if today.day <= 10:
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, 15)
        return start, end, f"Oldingi 25-sana davri ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    if today.day <= 25:
        py, pm = _shift_month(today.year, today.month, -1)
        start = date(py, pm, 16)
        end = date(py, pm, calendar.monthrange(py, pm)[1])
        return start, end, f"Oldingi 10-sana davri ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    start = date(today.year, today.month, 1)
    end = date(today.year, today.month, 15)
    return start, end, f"Oldingi 25-sana davri ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"


async def _edit_or_answer(target: Message | CallbackQuery, text: str, reply_markup=None):
    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_text(text, reply_markup=reply_markup)
            return
        await target.message.answer(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


async def _render_cabinet_home(target: Message | CallbackQuery, staff: dict, role: str):
    profile = await db.get_staff_profile(staff.get("TelegramID"))
    current_s, current_e, current_label = _current_pay_period(datetime.now().date())
    pay_summary = await db.get_staff_period_summary(profile["telegram_id"], current_s, current_e, include_future_schedule=True)
    live = await db.get_current_live_earning(profile["telegram_id"])

    lines = [
        f"{profile['emoji']} <b>{profile['name']}</b>",
        f"🧩 Rol: <b>{profile['role']}</b>",
        f"🏪 Magazin: <b>{profile['shop'] or '—'}</b>",
        f"💰 Stavka: <b>{_fmt_money(profile['rate'])}</b> / soat",
        "",
        f"💸 <b>{current_label}</b>",
        f"• Hozirgacha yig'ildi: <b>{_fmt_money(pay_summary['earnings'])}</b>",
        f"• Rejadagi smenalar bilan: <b>{_fmt_money(pay_summary['projected_earnings'])}</b>",
        f"• Ishlangan vaqt: <b>{pay_summary['hours']} soat</b>",
    ]
    if live.get("active"):
        lines += [
            "",
            "🟢 <b>Hozir ishda</b>",
            f"• Boshlanish: <b>{live.get('start') or '—'}</b>",
            f"• Hozirgacha ishladingiz: <b>{_fmt_money(live.get('earned'))}</b>",
            f"• Smena oxirigacha: <b>{_fmt_money(live.get('projected'))}</b>",
        ]

    await _edit_or_answer(target, "\n".join(lines), reply_markup=cabinet_home_kb(is_admin=role in ["admin", "manager"]))


async def _render_stats(target: CallbackQuery | Message, telegram_id: int | str, period_key: str, back_mode: str = "cab"):
    start_d, end_d, label = _period_by_key(period_key)
    summary = await db.get_staff_period_summary(telegram_id, start_d, end_d, include_future_schedule=True)
    profile = summary["profile"]

    text = (
        f"📊 <b>{profile['emoji']} {profile['name']}</b>\n"
        f"🗓 Davr: <b>{label}</b>\n\n"
        f"• Ish kunlari: <b>{summary['days_worked']}</b>\n"
        f"• Smenalar: <b>{summary['shifts']}</b>\n"
        f"• Ishlangan soat: <b>{summary['hours']}</b>\n"
        f"• Ish haqqi: <b>{_fmt_money(summary['earnings'])}</b>\n"
        f"• O'rtacha smena: <b>{summary['avg_shift_hours']} soat</b>\n"
        f"• Eng uzun smena: <b>{summary['longest_shift_hours']} soat</b>\n"
        f"• Eng ko'p ishlagan shop: <b>{summary['busiest_shop']}</b>\n"
        f"• Reja bilan prognoz: <b>{_fmt_money(summary['projected_earnings'])}</b>"
    )
    back = "cab_home" if back_mode == "cab" else f"stf_pick|{telegram_id}"
    prefix = "cab_stats|" if back_mode == "cab" else f"stf_stats|{telegram_id}|"
    kb = period_selector_kb(prefix=prefix, selected=period_key, include_back=back)
    await _edit_or_answer(target, text, reply_markup=kb)


async def _render_salary(target: CallbackQuery | Message, telegram_id: int | str, period_key: str, back_mode: str = "cab"):
    start_d, end_d, label = _period_by_key(period_key)
    summary = await db.get_staff_period_summary(telegram_id, start_d, end_d, include_future_schedule=True)
    live = await db.get_current_live_earning(telegram_id)
    profile = summary["profile"]

    text = (
        f"💸 <b>{profile['emoji']} {profile['name']}</b>\n"
        f"🗓 Davr: <b>{label}</b>\n\n"
        f"• Stavka: <b>{_fmt_money(summary['rate'])}</b> / soat\n"
        f"• Ishlangan soat: <b>{summary['hours']}</b>\n"
        f"• Hozirgacha yig'ildi: <b>{_fmt_money(summary['earnings'])}</b>\n"
        f"• Rejadagi smenalar bilan: <b>{_fmt_money(summary['projected_earnings'])}</b>"
    )
    if live.get("active"):
        text += (
            f"\n\n🟢 <b>Live hisob</b>\n"
            f"• Hozirgacha: <b>{_fmt_money(live.get('earned'))}</b>\n"
            f"• Smena oxirigacha: <b>{_fmt_money(live.get('projected'))}</b>"
        )

    back = "cab_home" if back_mode == "cab" else f"stf_pick|{telegram_id}"
    prefix = "cab_salary|" if back_mode == "cab" else f"stf_salaryp|{telegram_id}|"
    pay_offset = _pay_offset_from_key(period_key) if period_key in {"pay", "payprev"} or period_key.startswith("payo:") else 0
    selected_key = f"payo:{pay_offset}" if period_key in {"pay", "payprev"} or period_key.startswith("payo:") else period_key
    kb = period_selector_kb(prefix=prefix, selected=selected_key, include_back=back, pay_period_offset=pay_offset)
    await _edit_or_answer(target, text, reply_markup=kb)


async def _render_months(target: CallbackQuery | Message, telegram_id: int | str, selected_key: str | None = None, back_mode: str = "cab"):
    months = await db.get_monthly_breakdown(telegram_id, months=6)
    keys = [m["key"] for m in months]
    chosen = next((m for m in months if m["key"] == selected_key), months[0] if months else None)
    profile = await db.get_staff_profile(telegram_id)

    lines = [f"🗓 <b>{profile['emoji']} {profile['name']} — oyma-oy breakdown</b>"]
    for m in months:
        marker = "👉 " if chosen and m["key"] == chosen["key"] else "• "
        lines.append(f"{marker}<b>{m['label']}</b>: {_fmt_money(m['earnings'])} | {m['hours']} soat | {m['shifts']} smena")

    if chosen:
        lines += [
            "",
            f"<b>Tanlangan oy:</b> {chosen['label']}",
            f"• Ish kunlari: <b>{chosen['days_worked']}</b>",
            f"• Smenalar: <b>{chosen['shifts']}</b>",
            f"• Soat: <b>{chosen['hours']}</b>",
            f"• Oylik: <b>{_fmt_money(chosen['earnings'])}</b>",
        ]

    prefix = "cab_month|" if back_mode == "cab" else f"stf_monthpick|{telegram_id}|"
    back = "cab_home" if back_mode == "cab" else f"stf_pick|{telegram_id}"
    kb = month_breakdown_kb(prefix=prefix, months=keys, selected=chosen["key"] if chosen else None, include_back=back)
    await _edit_or_answer(target, "\n".join(lines), reply_markup=kb)


# ==========================================
# 👤 KABINETIM
# ==========================================
@router.message(F.text == "👤 Kabinetim")
async def cabinet_home(message: Message, staff: dict, role: str):
    await _render_cabinet_home(message, staff, role)


@router.callback_query(F.data == "cab_home")
async def cb_cab_home(callback: CallbackQuery, staff: dict, role: str):
    await callback.answer()
    await _render_cabinet_home(callback, staff, role)


@router.callback_query(F.data == "cab_stats_home")
async def cb_cab_stats_home(callback: CallbackQuery, staff: dict):
    await callback.answer()
    await _render_stats(callback, staff.get("TelegramID"), "m0", back_mode="cab")


@router.callback_query(F.data.startswith("cab_stats|"))
async def cb_cab_stats(callback: CallbackQuery, staff: dict):
    await callback.answer()
    key = callback.data.split("|", 1)[1]
    await _render_stats(callback, staff.get("TelegramID"), key, back_mode="cab")


@router.callback_query(F.data == "cab_salary_home")
async def cb_cab_salary_home(callback: CallbackQuery, staff: dict):
    await callback.answer()
    await _render_salary(callback, staff.get("TelegramID"), "pay", back_mode="cab")


@router.callback_query(F.data.startswith("cab_salary|"))
async def cb_cab_salary(callback: CallbackQuery, staff: dict):
    await callback.answer()
    key = callback.data.split("|", 1)[1]
    await _render_salary(callback, staff.get("TelegramID"), key, back_mode="cab")


@router.callback_query(F.data == "cab_months_home")
async def cb_cab_months_home(callback: CallbackQuery, staff: dict):
    await callback.answer()
    await _render_months(callback, staff.get("TelegramID"), back_mode="cab")


@router.callback_query(F.data.startswith("cab_month|"))
async def cb_cab_month_pick(callback: CallbackQuery, staff: dict):
    await callback.answer()
    key = callback.data.split("|", 1)[1]
    await _render_months(callback, staff.get("TelegramID"), selected_key=key, back_mode="cab")


@router.callback_query(F.data == "cab_smile_home")
async def cb_cab_smile(callback: CallbackQuery):
    await callback.answer()
    await _edit_or_answer(callback, "🙂 <b>Smaylik tanlang</b>", reply_markup=smile_picker_kb())


@router.callback_query(F.data.startswith("cab_smile_set|"))
async def cb_cab_smile_set(callback: CallbackQuery, staff: dict):
    await callback.answer("Saqlanyapti...")
    emoji = callback.data.split("|", 1)[1]
    await db.update_staff_field(staff.get("TelegramID"), "Смайлик", emoji)
    await db.append_audit_log(staff.get("TelegramID"), staff.get("Роль", "staff"), "employee_emoji_changed", {"emoji": emoji})
    await _edit_or_answer(callback, f"✅ Smaylik yangilandi: {emoji}", reply_markup=cabinet_home_kb(is_admin=str(staff.get('Роль', 'staff')).lower() in ['admin', 'manager']))


@router.callback_query(F.data == "cab_open_staff")
async def cb_open_staff(callback: CallbackQuery):
    await callback.answer("Xodimlar markazi ochildi")
    await callback.message.answer("👥 Xodimlar tugmasini bosing yoki shu pastdagi reply keyboarddan foydalaning.")


# ==========================================
# 📊 TEZ STATISTIKA (ASOSIY MENYUDAN)
# ==========================================
@router.message(F.text == "📊 Statistika")
async def show_personal_stats(message: Message, staff: dict):
    await _render_stats(message, staff.get("TelegramID"), "m0", back_mode="cab")


# ==========================================
# 📅 GRAFIK (KO'RISH)
# ==========================================
@router.message(F.text == "📅 Grafik")
async def show_schedule_menu(message: Message, state: FSMContext):
    await state.set_state(ReportState.viewing)
    await message.answer("Grafikni tanlang:", reply_markup=schedule_menu())


@router.message(ReportState.viewing, F.text.in_({"Bugun", "Ertaga", "Bu hafta", "Kelasi hafta"}))
async def process_schedule(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    today = datetime.now().date()

    schedule = []
    header = ""

    if text in ["Bugun", "Ertaga"]:
        t_date = today if text == "Bugun" else today + timedelta(days=1)
        d_str = t_date.strftime("%d-%m-%Y")
        header = f"📅 <b>Grafik ({d_str}):</b>"
        schedule = await db.get_user_schedule(user_id, d_str)
    else:
        wd = today.weekday()
        start_week = today - timedelta(days=wd)
        if text == "Bu hafta":
            s, e = start_week, start_week + timedelta(days=6)
            header = "📅 <b>Bu hafta:</b>"
        else:
            s, e = start_week + timedelta(days=7), start_week + timedelta(days=13)
            header = "📅 <b>Kelasi hafta:</b>"
        schedule = await db.get_user_schedule_range(user_id, s, e)

    if not schedule:
        await message.answer(f"{header}\n\nDam olish kuni! 😎")
        return

    lines = [header, ""]
    for item in schedule:
        start = item.get("Время начала", "")
        end = item.get("Время конца", "")
        if str(start).startswith("STATUS:"):
            code = str(start).split(":", 1)[1]
            start = f"📌 {STATUS_LABELS.get(code, code)}"
            end = ""
        lines.append(f"▫️ <b>{item.get('Дата', '')}</b> | {item.get('Магазин', '')}")
        lines.append(f"   ⏰ {start} {('- ' + end) if end else ''}\n")

    await message.answer("\n".join(lines))
