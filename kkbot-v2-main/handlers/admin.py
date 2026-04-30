from __future__ import annotations

from datetime import datetime
from collections import defaultdict
from contextlib import suppress

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from database.sqlite_db import db
from keyboards.builders import main_menu, staff_center_kb, staff_catalog_kb, staff_profile_kb
from handlers.reporting import _render_stats, _render_salary, _render_months, _current_pay_period

router = Router()
router.message.filter(F.chat.type == "private")


class AddStaffState(StatesGroup):
    name = State()
    telegram_id = State()
    role = State()
    shop = State()


class DeactivateStaffState(StatesGroup):
    waiting_for_id = State()


class StaffCenterState(StatesGroup):
    waiting_search = State()
    waiting_rate = State()
    waiting_emoji = State()


STATUS_LABELS = {
    "day_off": "Dam olish",
    "vacation": "отпуск",
    "sick_leave": "больничный",
}


def _fmt_money(value: float) -> str:
    return f"{round(float(value or 0)):,}".replace(",", " ") + " so'm"


async def _edit_or_answer(target: Message | CallbackQuery, text: str, reply_markup=None):
    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_text(text, reply_markup=reply_markup)
            return
        await target.message.answer(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


async def _build_online_text() -> str:
    all_staff = await db.get_all_staff(force_refresh=False)
    status_data = await db.get_today_live_status()
    working_map = status_data.get("working", {})
    schedule_map = status_data.get("schedule", {})
    completed_map = status_data.get("completed", {})
    shops_map = defaultdict(list)
    now = datetime.now()
    now_time = now.time()

    for staff in all_staff:
        tid = str(staff.get("TelegramID", "")).replace(".0", "")
        name = staff.get("Имя", "Noma'lum")
        emoji = staff.get("Смайлик") or "🙂"
        raw_shop = str(staff.get("Магазин", "Boshqa"))
        assigned_shop = raw_shop.split(",")[0].strip() or "Boshqa"

        if tid in working_map:
            assigned_shop = working_map[tid]
        elif tid in completed_map:
            assigned_shop = completed_map[tid]["shop"]
        elif tid in schedule_map:
            assigned_shop = schedule_map[tid]["shop"]

        status_icon = "🏖"
        status_text = "Dam olish"
        time_info = ""
        if tid in working_map:
            status_icon = "🟢"
            status_text = "Ishda"
            if tid in schedule_map:
                time_info = f"({schedule_map[tid]['start']} - {schedule_map[tid]['end']})"
        elif tid in completed_map:
            status_icon = "🏁"
            status_text = "Smena tugagan"
            time_info = f"({completed_map[tid]['start']} - {completed_map[tid]['end']})"
        elif tid in schedule_map:
            sch_start = schedule_map[tid]["start"]
            sch_end = schedule_map[tid]["end"]
            if str(sch_start).startswith("STATUS:"):
                code = str(sch_start).split(":", 1)[1]
                status_icon = "📌"
                status_text = STATUS_LABELS.get(code, code)
            else:
                try:
                    start_dt = datetime.strptime(sch_start, "%H:%M").time()
                    end_dt = datetime.strptime(sch_end, "%H:%M").time()
                    if now_time > end_dt and end_dt > start_dt:
                        status_icon = "❌"
                        status_text = "Kelmadi"
                    elif now_time > start_dt:
                        status_icon = "🔴"
                        status_text = "Kechikyapti"
                        time_info = f"({sch_start})"
                    else:
                        status_icon = "🟡"
                        status_text = "Kutilmoqda"
                        time_info = f"({sch_start})"
                except Exception:
                    status_icon = "⚪️"
                    status_text = "Smena"

        shops_map[assigned_shop].append(f"{status_icon} {emoji} {name} — {status_text} {time_info}".strip())

    report = f"📡 <b>ONLINE JADVAL ({now.strftime('%H:%M')})</b>\n\n"
    for shop_name, lines in shops_map.items():
        lines.sort(reverse=True)
        report += f"🏪 <b>{shop_name}</b>\n" + "\n".join(lines) + "\n\n"
    return report if shops_map else report + "Xodimlar topilmadi."


async def _render_staff_center(target: Message | CallbackQuery):
    all_staff = await db.get_all_staff(force_refresh=False)
    live = await db.get_today_live_status()
    roles = defaultdict(int)
    shops = set()
    for item in all_staff:
        roles[str(item.get("Роль", "staff")).lower()] += 1
        for sh in str(item.get("Магазин", "")).split(","):
            if sh.strip():
                shops.add(sh.strip())
    text = (
        "👥 <b>Xodimlar markazi</b>\n\n"
        f"• Faol xodimlar: <b>{len(all_staff)}</b>\n"
        f"• Hozir ishda: <b>{len(live.get('working', {}))}</b>\n"
        f"• Bugun smena tugatgan: <b>{len(live.get('completed', {}))}</b>\n"
        f"• Shoplar: <b>{len(shops)}</b>\n\n"
        f"• Admin: <b>{roles['admin']}</b> | Manager: <b>{roles['manager']}</b> | Staff: <b>{roles['staff']}</b>\n\n"
        "Pastdagi bo'limlardan keraklisini tanlang."
    )
    await _edit_or_answer(target, text, reply_markup=staff_center_kb())


async def _render_staff_catalog(target: Message | CallbackQuery, state: FSMContext, page: int = 1):
    data = await state.get_data()
    query = data.get("staff_query", "")
    results = await db.search_staff(query, limit=300)
    per_page = 8
    total_pages = max(1, (len(results) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    chunk = results[(page - 1) * per_page : page * per_page]
    items = []
    for item in chunk:
        tid = str(item.get("TelegramID", "")).replace(".0", "")
        emoji = str(item.get("Смайлик") or "🙂")
        name = str(item.get("Имя", "Xodim"))
        shop = str(item.get("Магазин", "") or "—")
        label = f"{emoji} {name} — {shop}"
        items.append((tid, label))
    title = "📚 <b>Xodimlar katalogi</b>"
    if query:
        title += f"\n🔍 Qidiruv: <b>{query}</b>"
    title += f"\n\nJami: <b>{len(results)}</b>"
    await _edit_or_answer(target, title, reply_markup=staff_catalog_kb(items, page, total_pages))


async def _render_staff_profile(target: Message | CallbackQuery, telegram_id: str, role: str):
    profile = await db.get_staff_profile(telegram_id)
    if not profile:
        await _edit_or_answer(target, "Xodim topilmadi.", reply_markup=staff_center_kb())
        return
    live = await db.get_current_live_earning(telegram_id)
    period_s, period_e, period_label = _current_pay_period(datetime.now().date())
    salary = await db.get_staff_period_summary(telegram_id, period_s, period_e, include_future_schedule=True)
    status_line = "⚪️ Hozir damda ishda emas"
    if live.get("active"):
        status_line = (
            f"🟢 Ishda | {live.get('shop') or '—'} | {live.get('start') or '—'}"
            f"\n• Hozirgacha: <b>{_fmt_money(live.get('earned'))}</b>"
            f"\n• Smena oxirigacha: <b>{_fmt_money(live.get('projected'))}</b>"
        )
    text = (
        f"👤 <b>{profile['emoji']} {profile['name']}</b>\n"
        f"🆔 <code>{profile['telegram_id']}</code>\n"
        f"🧩 Rol: <b>{profile['role']}</b>\n"
        f"🏪 Magazin: <b>{profile['shop'] or '—'}</b>\n"
        f"💰 Stavka: <b>{_fmt_money(profile['rate'])}</b> / soat\n"
        f"📈 {period_label}: <b>{_fmt_money(salary['earnings'])}</b>\n\n"
        f"{status_line}"
    )
    await _edit_or_answer(target, text, reply_markup=staff_profile_kb(telegram_id, can_edit=(role == 'admin')))


async def _render_staff_analytics(target: Message | CallbackQuery):
    staff = await db.get_all_staff(force_refresh=False)
    top_hours = []
    top_money = []
    shop_hours = defaultdict(float)
    today = datetime.now().date()
    month_start = today.replace(day=1)
    for item in staff:
        tid = str(item.get("TelegramID", "")).replace(".0", "")
        profile = await db.get_staff_profile(tid)
        summary = await db.get_staff_period_summary(tid, month_start, today, include_future_schedule=False)
        top_hours.append((summary["hours"], f"{profile['emoji']} {profile['name']} — {summary['hours']} soat"))
        top_money.append((summary["earnings"], f"{profile['emoji']} {profile['name']} — {_fmt_money(summary['earnings'])}"))
        if summary["busiest_shop"] != "—":
            shop_hours[summary["busiest_shop"]] += summary["hours"]
    top_hours.sort(reverse=True)
    top_money.sort(reverse=True)
    shop_sorted = sorted(shop_hours.items(), key=lambda x: x[1], reverse=True)

    text = "📊 <b>Premium analytics</b>\n\n"
    text += "<b>Top soat:</b>\n" + ("\n".join(f"• {x[1]}" for x in top_hours[:5]) or "—") + "\n\n"
    text += "<b>Top oylik:</b>\n" + ("\n".join(f"• {x[1]}" for x in top_money[:5]) or "—") + "\n\n"
    text += "<b>Shop yuklamasi:</b>\n" + ("\n".join(f"• {shop}: {round(h, 1)} soat" for shop, h in shop_sorted[:5]) or "—")
    await _edit_or_answer(target, text, reply_markup=staff_center_kb())


@router.message(F.text == "⚙️ Admin Panel")
async def admin_panel_menu(message: Message, role: str):
    if role != "admin":
        await message.answer("Bu bo'lim faqat adminlar uchun!")
        return
    builder = ReplyKeyboardBuilder()
    builder.button(text="🆕 Xodim qo'shish")
    builder.button(text="🚫 Xodimni o'chirish")
    builder.button(text="⬅ Назад")
    builder.adjust(2)
    await message.answer("Admin Panelga xush kelibsiz.", reply_markup=builder.as_markup(resize_keyboard=True))


@router.message(F.text == "👥 Xodimlar")
async def view_staff_hub(message: Message, role: str):
    if role not in ["admin", "manager"]:
        return
    await _render_staff_center(message)


@router.callback_query(F.data == "stf_home")
async def cb_staff_home(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    await _render_staff_center(callback)


@router.callback_query(F.data == "stf_home_online")
async def cb_staff_online(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    await _edit_or_answer(callback, await _build_online_text(), reply_markup=staff_center_kb())


@router.callback_query(F.data == "stf_home_catalog")
async def cb_staff_catalog(callback: CallbackQuery, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    await state.update_data(staff_query="")
    await _render_staff_catalog(callback, state, page=1)


@router.callback_query(F.data.startswith("stf_page|"))
async def cb_staff_page(callback: CallbackQuery, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    page = int(callback.data.split("|", 1)[1])
    await _render_staff_catalog(callback, state, page=page)


@router.callback_query(F.data == "stf_home_search")
async def cb_staff_search(callback: CallbackQuery, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    await state.set_state(StaffCenterState.waiting_search)
    await callback.message.answer("🔍 Qidiruv so'zini yuboring:\nmasalan: ism, ID yoki magazin")


@router.message(StaffCenterState.waiting_search)
async def process_staff_search(message: Message, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await state.update_data(staff_query=message.text.strip())
    await state.set_state(None)
    await _render_staff_catalog(message, state, page=1)


@router.callback_query(F.data.startswith("stf_pick|"))
async def cb_staff_pick(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    tid = callback.data.split("|", 1)[1]
    await _render_staff_profile(callback, tid, role)


@router.callback_query(F.data == "stf_home_analytics")
async def cb_staff_analytics(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    await _render_staff_analytics(callback)


@router.callback_query(F.data.startswith("stf_stats|"))
async def cb_staff_stats(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    _, tid, period = callback.data.split("|", 2)
    await _render_stats(callback, tid, period, back_mode="admin")


@router.callback_query(F.data.startswith("stf_salary|"))
async def cb_staff_salary(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    tid = callback.data.split("|", 1)[1]
    await _render_salary(callback, tid, "pay", back_mode="admin")


@router.callback_query(F.data.startswith("stf_salaryp|"))
async def cb_staff_salary_period(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    _, tid, period = callback.data.split("|", 2)
    await _render_salary(callback, tid, period, back_mode="admin")


@router.callback_query(F.data.startswith("stf_months|"))
async def cb_staff_months(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    tid = callback.data.split("|", 1)[1]
    await _render_months(callback, tid, back_mode="admin")


@router.callback_query(F.data.startswith("stf_monthpick|"))
async def cb_staff_monthpick(callback: CallbackQuery, role: str):
    if role not in ["admin", "manager"]:
        return
    await callback.answer()
    _, tid, month_key = callback.data.split("|", 2)
    await _render_months(callback, tid, selected_key=month_key, back_mode="admin")


@router.callback_query(F.data.startswith("stf_rate|"))
async def cb_staff_rate(callback: CallbackQuery, state: FSMContext, role: str):
    if role != "admin":
        return
    await callback.answer()
    tid = callback.data.split("|", 1)[1]
    await state.set_state(StaffCenterState.waiting_rate)
    await state.update_data(edit_tid=tid)
    await callback.message.answer("💰 Yangi stavkani yuboring.\nMasalan: 25000")


@router.message(StaffCenterState.waiting_rate)
async def process_staff_rate(message: Message, state: FSMContext, role: str):
    if role != "admin":
        return
    data = await state.get_data()
    tid = data.get("edit_tid")
    try:
        rate = float(str(message.text).replace(" ", "").replace(",", "."))
    except Exception:
        await message.answer("Noto'g'ri format. Faqat son yuboring.")
        return
    await db.update_staff_field(tid, "Ставка", str(int(rate) if rate.is_integer() else rate))
    await db.append_audit_log(message.from_user.id, role, "staff_rate_changed", {"target_tid": tid, "rate": rate})
    await state.clear()
    await _render_staff_profile(message, tid, role)


@router.callback_query(F.data.startswith("stf_emoji|"))
async def cb_staff_emoji(callback: CallbackQuery, state: FSMContext, role: str):
    if role != "admin":
        return
    await callback.answer()
    tid = callback.data.split("|", 1)[1]
    await state.set_state(StaffCenterState.waiting_emoji)
    await state.update_data(edit_tid=tid)
    await callback.message.answer("🙂 Yangi smaylikni yuboring.\nMasalan: 😎")


@router.message(StaffCenterState.waiting_emoji)
async def process_staff_emoji(message: Message, state: FSMContext, role: str):
    if role != "admin":
        return
    data = await state.get_data()
    tid = data.get("edit_tid")
    emoji = (message.text or "🙂").strip()[:4]
    await db.update_staff_field(tid, "Смайлик", emoji)
    await db.append_audit_log(message.from_user.id, role, "staff_emoji_changed", {"target_tid": tid, "emoji": emoji})
    await state.clear()
    await _render_staff_profile(message, tid, role)


@router.callback_query(F.data.startswith("stf_delete|"))
async def cb_staff_delete(callback: CallbackQuery, role: str):
    if role != "admin":
        return
    await callback.answer("O'chirildi")
    tid = callback.data.split("|", 1)[1]
    await db.deactivate_staff(tid)
    await db.append_audit_log(callback.from_user.id, role, "staff_deactivated", {"target_tid": tid})
    await _render_staff_center(callback)


@router.message(F.text == "🆕 Xodim qo'shish")
async def start_add_staff(message: Message, state: FSMContext, role: str):
    if role != "admin":
        return
    await state.set_state(AddStaffState.name)
    await message.answer("1. Ism Familiya:", reply_markup=ReplyKeyboardRemove())


@router.message(AddStaffState.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddStaffState.telegram_id)
    await message.answer("2. Telegram ID:")


@router.message(AddStaffState.telegram_id)
async def process_id(message: Message, state: FSMContext):
    await state.update_data(telegram_id=int(message.text))
    builder = InlineKeyboardBuilder()
    builder.button(text="Staff", callback_data="role_staff")
    builder.button(text="Manager", callback_data="role_manager")
    builder.button(text="Admin", callback_data="role_admin")
    builder.adjust(1)
    await state.set_state(AddStaffState.role)
    await message.answer("3. Rol:", reply_markup=builder.as_markup())


@router.callback_query(AddStaffState.role, F.data.startswith("role_"))
async def process_role(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    role = callback.data.split("_")[1]
    await state.update_data(role=role)
    shops = await db.get_shops()
    builder = InlineKeyboardBuilder()
    for shop in shops:
        builder.button(text=shop, callback_data=f"shop_{shop}")
    builder.adjust(2)
    await state.set_state(AddStaffState.shop)
    await callback.message.edit_text("4. Magazin:", reply_markup=builder.as_markup())


@router.callback_query(AddStaffState.shop, F.data.startswith("shop_"))
async def process_shop(callback: CallbackQuery, state: FSMContext, role: str):
    await callback.answer()
    shop_name = callback.data.split("_", 1)[1]
    data = await state.get_data()
    await db.add_new_staff(data['telegram_id'], data['name'], data['role'], shop_name)
    await db.append_audit_log(callback.from_user.id, role, "staff_added", {"target_tid": data['telegram_id'], "name": data['name'], "role": data['role'], "shop": shop_name})
    await callback.message.answer("Qo'shildi ✅", reply_markup=main_menu(role))
    await state.clear()
    await callback.message.delete()


@router.message(F.text == "🚫 Xodimni o'chirish")
async def start_deactivate(message: Message, state: FSMContext, role: str):
    if role != "admin":
        return
    await state.set_state(DeactivateStaffState.waiting_for_id)
    await message.answer("ID kiriting:", reply_markup=ReplyKeyboardRemove())


@router.message(DeactivateStaffState.waiting_for_id)
async def process_deactivate(message: Message, state: FSMContext, role: str):
    await db.deactivate_staff(int(message.text))
    await db.append_audit_log(message.from_user.id, role, "staff_deactivated_manual", {"target_tid": int(message.text)})
    await message.answer("O'chirildi ✅", reply_markup=main_menu(role))
    await state.clear()
