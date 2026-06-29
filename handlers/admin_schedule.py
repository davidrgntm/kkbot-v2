from __future__ import annotations

from datetime import datetime, timedelta
from contextlib import suppress

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from config import config
from database.sqlite_db import db
from services.quick_schedule import parse_quick_schedule, render_quick_schedule_preview, find_conflicts
from keyboards.builders import (
    main_menu,
    build_calendar,
    build_time_picker,
    confirm_schedule_kb,
    send_to_group_kb,
    repeat_weeks_kb,
    publish_confirm_kb,
    schedule_kind_kb,
)

router = Router()

STATUS_LABELS = {
    "day_off": "Dam olish",
    "vacation": "отпуск",
    "sick_leave": "больничный",
}


async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    with suppress(Exception):
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)


@router.callback_query(F.data == "ignore")
async def ignore_callback(cb: CallbackQuery):
    await _safe_answer(cb)


@router.callback_query(F.data.startswith("cal_nav_"))
async def calendar_nav(callback: CallbackQuery):
    await _safe_answer(callback)
    _, _, year, month = callback.data.split("_", 3)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=build_calendar(int(year), int(month)))


def _parse_date_any(s: str):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        with suppress(Exception):
            return datetime.strptime(s, fmt).date()
    return None


def _parse_date_str(s: str):
    return datetime.strptime(s, "%d-%m-%Y").date()


def _status_label(code: str) -> str:
    return STATUS_LABELS.get(code, code)


def _is_status_entry(item: dict) -> bool:
    return item.get("kind") == "status" or str(item.get("start", "")).startswith("STATUS:")


def _decode_row_kind(start_value: str, end_value: str) -> tuple[str, str | None, str | None]:
    start_value = (start_value or "").strip()
    end_value = (end_value or "").strip()
    if start_value.startswith("STATUS:"):
        code = start_value.split(":", 1)[1].strip()
        return "status", code, end_value or _status_label(code)
    return "shift", None, None


async def _get_graphic_rows(date_str: str | None = None):
    target_date = _parse_date_any(date_str) if date_str else None
    rows = await db.get_schedule_rows(start_date=target_date, end_date=target_date)
    out = []
    for r in rows:
        kind, status_code, status_label = _decode_row_kind(r.get("start", ""), r.get("end", ""))
        out.append(
            {
                "row": r["row"],
                "date": r["date"].strftime("%d-%m-%Y"),
                "name": r.get("name", "").strip(),
                "tid": str(r.get("telegram_id", "")).replace(".0", "").strip(),
                "shop": r.get("shop", "").strip(),
                "start": r.get("start", "").strip(),
                "end": r.get("end", "").strip(),
                "kind": kind,
                "status_code": status_code,
                "status_label": status_label,
            }
        )
    return out


def _item_display_range(it: dict) -> str:
    if _is_status_entry(it):
        code = it.get("status_code") or str(it.get("start", "")).split(":", 1)[-1]
        return f"📌 {_status_label(code)}"
    return f"{it.get('start', '')} - {it.get('end', '')}"


def _time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m
    if h < 8:
        total += 24 * 60
    return total


def _shift_hours(start: str, end: str) -> float:
    return max(0, (_time_to_minutes(end) - _time_to_minutes(start)) / 60)


def _row_to_save_values(item: dict) -> list[str]:
    if _is_status_entry(item):
        code = item.get("status_code") or str(item.get("start", "")).split(":", 1)[-1]
        return [
            item["date"],
            item["name"],
            str(item["tid"]),
            item["shop"],
            f"STATUS:{code}",
            _status_label(code),
        ]
    return [item["date"], item["name"], str(item["tid"]), item["shop"], item["start"], item["end"]]


def _items_conflict(a: dict, b: dict) -> bool:
    if str(a.get("date")) != str(b.get("date")):
        return False
    if str(a.get("tid")) != str(b.get("tid")):
        return False
    if _is_status_entry(a) or _is_status_entry(b):
        return True
    try:
        a_start = _time_to_minutes(a["start"])
        a_end = _time_to_minutes(a["end"])
        b_start = _time_to_minutes(b["start"])
        b_end = _time_to_minutes(b["end"])
        return a_start < b_end and a_end > b_start
    except Exception:
        return False


def _conflict_message(new_item: dict, existing_item: dict) -> str:
    return (
        f"{new_item.get('name', 'Xodim')} uchun konflikt: "
        f"{existing_item.get('date')} | {existing_item.get('shop')} | {_item_display_range(existing_item)}"
    )


def _group_graphic_text(date_str: str, items: list[dict]) -> str:
    if not items:
        return f"📆 <b>{date_str}</b>\n\n⚠️ Bu kunda grafik topilmadi."
    shops: dict[str, list[dict]] = {}
    for it in items:
        shops.setdefault(it.get("shop") or "Noma'lum", []).append(it)
    for shop in shops:
        shops[shop].sort(key=lambda x: x.get("start") or "99:99")
    text = f"📆 <b>Umumiy grafik: {date_str}</b>\n\n"
    for shop, lst in shops.items():
        text += f"🏪 <b>{shop}</b>\n"
        for it in lst:
            text += f"• {it.get('name') or it.get('tid') or '—'} — {_item_display_range(it)}\n"
        text += "\n"
    return text.strip()


def _analytics_text(schedule_list: list[dict]) -> str:
    if not schedule_list:
        return ""
    shops: dict[str, dict] = {}
    for it in schedule_list:
        shop = it.get("shop") or "Noma'lum"
        bucket = shops.setdefault(shop, {"employees": 0, "hours": 0.0, "statuses": {"day_off": 0, "vacation": 0, "sick_leave": 0}})
        bucket["employees"] += 1
        if _is_status_entry(it):
            code = it.get("status_code") or str(it.get("start", "")).split(":", 1)[-1]
            bucket["statuses"][code] = bucket["statuses"].get(code, 0) + 1
        else:
            with suppress(Exception):
                bucket["hours"] += _shift_hours(it["start"], it["end"])
    text = "📊 <b>Yuklama analitikasi</b>\n"
    for shop, info in shops.items():
        statuses = []
        if info["statuses"].get("day_off"):
            statuses.append(f"dam: {info['statuses']['day_off']}")
        if info["statuses"].get("vacation"):
            statuses.append(f"otpusk: {info['statuses']['vacation']}")
        if info["statuses"].get("sick_leave"):
            statuses.append(f"kasal: {info['statuses']['sick_leave']}")
        suffix = f" | {', '.join(statuses)}" if statuses else ""
        text += f"• {shop}: xodim={info['employees']}, soat={info['hours']:.1f}{suffix}\n"
    return text.strip()


async def build_preview_text(schedule_list: list[dict], repeat_weeks: int = 0) -> str:
    if not schedule_list:
        return "Ro'yxat bo'sh."
    date_str = schedule_list[0]["date"]
    shops: dict[str, list[dict]] = {}
    for it in schedule_list:
        shops.setdefault(it.get("shop") or "Noma'lum", []).append(it)
    for shop in shops:
        shops[shop].sort(key=lambda x: x.get("start") or "99:99")
    text = f"📅 <b>Grafik: {date_str}</b>\n"
    if repeat_weeks:
        text += f"🔁 Repeat: keyingi <b>{repeat_weeks}</b> hafta ham yoziladi\n"
    text += "\n"
    for shop, lst in shops.items():
        text += f"🏪 <b>{shop}</b>\n"
        for it in lst:
            text += f"• {it.get('name', '—')} — {_item_display_range(it)}\n"
        text += "\n"
    text += _analytics_text(schedule_list)
    text += "\n\n✅ Tasdiqlaysizmi?"
    return text


def _entry_mode_kb():
    b = InlineKeyboardBuilder()
    b.button(text="⚡ Tez grafik (matn)", callback_data="sch_mode_quick")
    b.button(text="✍️ Qo'lda tuzish", callback_data="sch_mode_manual")
    b.button(text="📋 Kechagi grafikdan nusxa olish", callback_data="sch_mode_copy_prev")
    b.button(text="⬅ Sanani qayta tanlash", callback_data="sch_mode_back_date")
    b.adjust(1)
    return b.as_markup()


def _make_shop_map(shops: list[str]) -> dict[str, str]:
    return {str(i): shop for i, shop in enumerate(shops, start=1)}


def _make_employee_map(staff_rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    idx = 1
    for s in staff_rows:
        name = str(s.get("Имя", "")).strip()
        tid = str(s.get("TelegramID", "")).replace(".0", "").strip()
        emoji = str(s.get("Смайлик", "🙂") or "🙂")
        if not name or not tid:
            continue
        out[str(idx)] = {"name": name, "tid": tid, "emoji": emoji}
        idx += 1
    return out


async def _build_shop_kb(state: FSMContext):
    data = await state.get_data()
    shop_map = data.get("shop_map", {})
    b = InlineKeyboardBuilder()
    for token, shop in shop_map.items():
        b.button(text=shop, callback_data=f"sch_shop_{token}")
    b.button(text="⬅ Orqaga", callback_data="sch_shop_back")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


async def _render_employee_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    employee_map = data.get("employee_map", {})
    selected = set(data.get("selected_employee_tokens", []))
    b = InlineKeyboardBuilder()
    for token, emp in employee_map.items():
        mark = "✅ " if token in selected else ""
        label = f"{mark}{emp['emoji']} {emp['name']}"
        b.button(text=label[:60], callback_data=f"sch_emp_pick_{token}")
    b.button(text="🧹 Tozalash", callback_data="sch_emp_clear")
    b.button(text="✅ Davom etish", callback_data="sch_emp_done")
    b.button(text="⬅ Magazinlarga qaytish", callback_data="sch_emp_back_shops")
    b.adjust(1)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"🏪 <b>{data.get('selected_shop', '—')}</b>\n"
            f"👥 Xodimlarni tanlang: <b>{len(selected)}</b> ta\n\n"
            f"Keyingi bosqichda har bir xodimga alohida vaqt yoki status qo'yiladi.",
            reply_markup=b.as_markup(),
        )


async def _log_action(actor_tid: int, actor_role: str, action: str, payload: dict):
    await db.append_audit_log(actor_tid, actor_role, action, payload)


async def _render_entry_mode(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(ScheduleState.entry_mode)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"📅 Sana: <b>{data.get('selected_date')}</b>\n\nGrafikni qanday tuzamiz?",
            reply_markup=_entry_mode_kb(),
        )


async def _render_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(ScheduleState.confirm)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            await build_preview_text(data.get("schedule_list", []), int(data.get("repeat_weeks", 0))),
            reply_markup=confirm_schedule_kb(int(data.get("repeat_weeks", 0))),
        )


async def _render_current_employee_assign(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    queue = data.get("queue_tokens", [])
    idx = int(data.get("queue_index", 0))
    employee_map = data.get("employee_map", {})
    if idx >= len(queue):
        await _render_confirm(callback, state)
        return
    token = queue[idx]
    emp = employee_map.get(token)
    if not emp:
        await state.update_data(queue_index=idx + 1)
        await _render_current_employee_assign(callback, state)
        return
    await state.update_data(current_employee_token=token, selected_start_time=None)
    await state.set_state(ScheduleState.start_time)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"👤 <b>{emp['emoji']} {emp['name']}</b>\n"
            f"🏪 Magazin: <b>{data.get('selected_shop')}</b>\n"
            f"📍 {idx + 1}/{len(queue)} xodim\n\n"
            f"⏰ Kelish vaqtini tanlang:",
            reply_markup=_schedule_start_kb(),
        )


async def _append_selected_employee_item(callback: CallbackQuery, state: FSMContext, item_data: dict):
    data = await state.get_data()
    token = data.get("current_employee_token")
    employee_map = data.get("employee_map", {})
    emp = employee_map.get(token)
    if not emp:
        await _safe_answer(callback, "Xodim topilmadi.", alert=True)
        return
    item = {
        "date": data["selected_date"],
        "shop": data["selected_shop"],
        "tid": emp["tid"],
        "name": emp["name"],
        **item_data,
    }
    schedule_list = data.get("schedule_list", [])
    existing = await _get_graphic_rows(data["selected_date"])
    for ex in schedule_list + existing:
        if _items_conflict(item, ex):
            await _safe_answer(callback, _conflict_message(item, ex), alert=True)
            return
    schedule_list.append(item)
    await state.update_data(schedule_list=schedule_list, queue_index=int(data.get("queue_index", 0)) + 1)
    await _render_current_employee_assign(callback, state)


def _expand_with_repeat(schedule_list: list[dict], repeat_weeks: int) -> list[dict]:
    expanded = []
    for week in range(repeat_weeks + 1):
        delta = timedelta(days=7 * week)
        for item in schedule_list:
            d = _parse_date_str(item["date"]) + delta
            clone = dict(item)
            clone["date"] = d.strftime("%d-%m-%Y")
            expanded.append(clone)
    return expanded


async def _collect_save_conflicts(items_to_save: list[dict]) -> list[str]:
    conflicts = []
    by_date: dict[str, list[dict]] = {}
    for it in items_to_save:
        by_date.setdefault(it["date"], []).append(it)
    for date_str, items in by_date.items():
        existing = await _get_graphic_rows(date_str)
        for i, item in enumerate(items):
            for ex in existing:
                if _items_conflict(item, ex):
                    conflicts.append(_conflict_message(item, ex))
            for j, other in enumerate(items):
                if i != j and _items_conflict(item, other):
                    conflicts.append(_conflict_message(item, other))
    uniq = []
    seen = set()
    for c in conflicts:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


class ScheduleState(StatesGroup):
    date = State()
    entry_mode = State()
    shop = State()
    employee = State()
    assign_kind = State()
    start_time = State()
    end_time = State()
    confirm = State()
    repeat_select = State()
    quick_text = State()
    quick_confirm = State()


@router.message(F.text.in_(["🧩 Grafik tuzish", "🧩 Grafik yaratish"]))
async def start_schedule(message: Message, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await state.clear()
    now = datetime.now()
    await state.set_state(ScheduleState.date)
    await message.answer("📅 Sana tanlang:", reply_markup=build_calendar(now.year, now.month))


@router.callback_query(ScheduleState.date, F.data.startswith("cal_date_"))
async def schedule_date_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    date_str = callback.data.split("_", 2)[2]
    await state.update_data(selected_date=date_str, schedule_list=[], repeat_weeks=0)
    await _render_entry_mode(callback, state)


@router.callback_query(ScheduleState.entry_mode, F.data == "sch_mode_back_date")
async def schedule_back_date(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    now = datetime.now()
    await state.set_state(ScheduleState.date)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("📅 Sana tanlang:", reply_markup=build_calendar(now.year, now.month))


async def show_shop_selection(callback: CallbackQuery, state: FSMContext, date_str: str):
    shops = await db.get_shops()
    shop_map = _make_shop_map(shops)
    await state.update_data(selected_date=date_str, shop_map=shop_map)
    await state.set_state(ScheduleState.shop)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"📅 Sana: <b>{date_str}</b>\n\n🏪 Magazin tanlang:",
            reply_markup=await _build_shop_kb(state),
        )




def _quick_confirm_kb(can_save: bool = True):
    b = InlineKeyboardBuilder()
    if can_save:
        b.button(text="✅ Saqlash", callback_data="qsch_save")
        b.button(text="📣 Saqlash va guruhga yuborish", callback_data="qsch_save_publish")
    b.button(text="✏️ Matnni qayta yuborish", callback_data="qsch_rewrite")
    b.button(text="❌ Bekor qilish", callback_data="qsch_cancel")
    b.adjust(1)
    return b.as_markup()


async def _existing_items_for_dates(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    dates = sorted({it.get("date") for it in items if it.get("date")})
    for ds in dates:
        d = _parse_date_any(ds)
        if not d:
            continue
        for row in await db.get_schedule_rows(start_date=d, end_date=d):
            result.append({
                "date": row["date"].strftime("%d-%m-%Y"),
                "tid": str(row.get("telegram_id", "")).replace(".0", ""),
                "name": row.get("name", ""),
                "shop": row.get("shop", ""),
                "start": row.get("start", ""),
                "end": row.get("end", ""),
                "kind": "status" if row.get("status") else "shift",
                "status_code": row.get("status"),
            })
    return result


async def _save_quick_schedule(callback: CallbackQuery, state: FSMContext, role: str, publish: bool = False):
    await _safe_answer(callback)
    data = await state.get_data()
    result = data.get("quick_result") or {}
    items = result.get("items") or []
    if not result.get("can_save") or not items:
        await _safe_answer(callback, "Avval xatolarni tuzating.", alert=True)
        return
    existing = await _existing_items_for_dates(items)
    conflicts = find_conflicts(items, existing)
    if conflicts:
        text = "\n".join(conflicts[:6])
        if len(conflicts) > 6:
            text += f"\n... va yana {len(conflicts)-6} ta"
        await _safe_answer(callback, text, alert=True)
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("⏳ Tez grafik bazaga yozilmoqda...")
    ok = await db.append_schedule_rows(items)
    if not ok:
        await callback.message.answer("❌ Grafikni saqlashda xatolik chiqdi.")
        return
    await _log_action(callback.from_user.id, role, "quick_schedule_saved", {"items": len(items), "date": result.get("date"), "publish": publish})
    preview = render_quick_schedule_preview(result).replace("✅ Saqlashga tayyor.", "").strip()
    final_text = f"✅ <b>TEZ GRAFIK SAQLANDI</b>\n\n{preview}\n\n🧾 Jami: <b>{len(items)}</b> qator"
    await state.clear()
    if publish:
        group_text = _group_graphic_text(result.get("date") or items[0]["date"], items)
        try:
            await callback.bot.send_message(config.group_chat_id, group_text)
            await callback.message.answer(final_text + "\n\n📣 Guruhga yuborildi ✅", reply_markup=main_menu(role))
        except Exception as e:
            await callback.message.answer(final_text + f"\n\n⚠️ Guruhga yuborishda xato: {e}", reply_markup=main_menu(role))
    else:
        await callback.message.answer(final_text, reply_markup=main_menu(role))


@router.callback_query(ScheduleState.entry_mode, F.data == "sch_mode_quick")
async def schedule_quick_mode(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await state.set_state(ScheduleState.quick_text)
    example = (
        "SD\n"
        "Dilnavoz 10-16\n"
        "Jaxongir 16-22\n\n"
        "TCM\n"
        "Ixtiyor 9-14\n"
        "Muxabbat 14-22\n"
        "Izzat 14-23\n\n"
        "FP\n"
        "Shuxrat 10-17\n"
        "Shamsiddin 16-22"
    )
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"⚡ <b>Tez grafik</b>\n\n"
            f"Sana: <b>{data.get('selected_date')}</b>\n\n"
            "Grafik matnini bitta xabar qilib yuboring. Lotin/kiril, username, ismdagi kichik xatolarni tushunishga harakat qilaman.\n\n"
            f"<pre>{example}</pre>",
        )


@router.message(ScheduleState.quick_text)
async def quick_schedule_text_received(message: Message, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    data = await state.get_data()
    default_date = data.get("selected_date")
    staff = await db.get_all_staff(force_refresh=True)
    shops = await db.get_shops()
    result = parse_quick_schedule(message.text or "", staff, shops, default_date=default_date)
    await state.update_data(quick_result=result)
    await state.set_state(ScheduleState.quick_confirm)
    await message.answer(render_quick_schedule_preview(result), reply_markup=_quick_confirm_kb(result.get("can_save", False)))


@router.callback_query(ScheduleState.quick_confirm, F.data == "qsch_rewrite")
async def quick_schedule_rewrite(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await state.set_state(ScheduleState.quick_text)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("✏️ Grafik matnini qayta yuboring:")


@router.callback_query(ScheduleState.quick_confirm, F.data == "qsch_cancel")
async def quick_schedule_cancel(callback: CallbackQuery, state: FSMContext, role: str = "unknown"):
    await _safe_answer(callback)
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer("Tez grafik bekor qilindi.", reply_markup=main_menu(role))


@router.callback_query(ScheduleState.quick_confirm, F.data == "qsch_save")
async def quick_schedule_save(callback: CallbackQuery, state: FSMContext, role: str = "unknown"):
    await _save_quick_schedule(callback, state, role, publish=False)


@router.callback_query(ScheduleState.quick_confirm, F.data == "qsch_save_publish")
async def quick_schedule_save_publish(callback: CallbackQuery, state: FSMContext, role: str = "unknown"):
    await _save_quick_schedule(callback, state, role, publish=True)


@router.callback_query(ScheduleState.entry_mode, F.data == "sch_mode_manual")
async def schedule_manual_mode(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await show_shop_selection(callback, state, data["selected_date"])


@router.callback_query(ScheduleState.entry_mode, F.data == "sch_mode_copy_prev")
async def schedule_copy_previous(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    selected_date = _parse_date_str(data["selected_date"])
    prev_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    prev_rows = await _get_graphic_rows(prev_date)
    if not prev_rows:
        await _safe_answer(callback, "Kechagi grafik topilmadi.", alert=True)
        return
    schedule_list = []
    for row in prev_rows:
        clone = dict(row)
        clone.pop("row", None)
        clone["date"] = data["selected_date"]
        schedule_list.append(clone)
    conflicts = await _collect_save_conflicts(schedule_list)
    if conflicts:
        await _safe_answer(callback, "Kopiyada konflikt bor. Avval tekshiring.", alert=True)
        return
    await state.update_data(schedule_list=schedule_list)
    await _render_confirm(callback, state)


@router.callback_query(ScheduleState.shop, F.data == "sch_shop_back")
async def shop_back_entry(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await _render_entry_mode(callback, state)


async def select_employee_step(callback: CallbackQuery, state: FSMContext, shop: str):
    all_staff = await db.get_all_staff(force_refresh=True)
    target_shop = shop.strip().lower()
    shop_staff = []
    for s in all_staff:
        raw_shops = str(s.get("Магазин", ""))
        employee_shops = [x.strip().lower() for x in raw_shops.split(",")]
        if target_shop in employee_shops:
            shop_staff.append(s)
    employee_map = _make_employee_map(shop_staff)
    await state.update_data(employee_map=employee_map, selected_employee_tokens=[])
    await state.set_state(ScheduleState.employee)
    await _render_employee_selection(callback, state)


@router.callback_query(ScheduleState.shop, F.data.startswith("sch_shop_"))
async def shop_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    token = callback.data.split("sch_shop_", 1)[1]
    shop = (await state.get_data()).get("shop_map", {}).get(token)
    if not shop:
        await _safe_answer(callback, "Magazin topilmadi.", alert=True)
        return
    await state.update_data(selected_shop=shop)
    await select_employee_step(callback, state, shop)


@router.callback_query(ScheduleState.employee, F.data == "sch_emp_back_shops")
async def employee_back_shops(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await show_shop_selection(callback, state, data["selected_date"])


@router.callback_query(ScheduleState.employee, F.data == "sch_emp_clear")
async def employee_clear(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await state.update_data(selected_employee_tokens=[])
    await _render_employee_selection(callback, state)


@router.callback_query(ScheduleState.employee, F.data.startswith("sch_emp_pick_"))
async def employee_toggle(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    token = callback.data.split("sch_emp_pick_", 1)[1]
    data = await state.get_data()
    selected = set(data.get("selected_employee_tokens", []))
    if token in selected:
        selected.remove(token)
    else:
        selected.add(token)
    await state.update_data(selected_employee_tokens=list(selected))
    await _render_employee_selection(callback, state)


@router.callback_query(ScheduleState.employee, F.data == "sch_emp_done")
async def employee_done(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    selected = data.get("selected_employee_tokens", [])
    if not selected:
        await _safe_answer(callback, "Kamida bitta xodim tanlang.", alert=True)
        return
    await state.update_data(queue_tokens=selected, queue_index=0)
    await _render_current_employee_assign(callback, state)


@router.callback_query(ScheduleState.assign_kind, F.data == "sch_back_to_employee")
@router.callback_query(ScheduleState.start_time, F.data == "sch_back_to_employee")
async def assign_back_to_employee(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await state.update_data(queue_tokens=[], queue_index=0, selected_start_time=None)
    await state.set_state(ScheduleState.employee)
    await _render_employee_selection(callback, state)


@router.callback_query(ScheduleState.assign_kind, F.data == "sch_kind_skip")
async def assign_skip(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await state.update_data(queue_index=int(data.get("queue_index", 0)) + 1)
    await _render_current_employee_assign(callback, state)


@router.callback_query(ScheduleState.assign_kind, F.data.in_({"sch_kind_day_off", "sch_kind_vacation", "sch_kind_sick_leave"}))
@router.callback_query(ScheduleState.start_time, F.data.in_({"sch_kind_day_off", "sch_kind_vacation", "sch_kind_sick_leave"}))
async def assign_status(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    code = callback.data.replace("sch_kind_", "")
    await _append_selected_employee_item(
        callback,
        state,
        {
            "kind": "status",
            "status_code": code,
            "status_label": _status_label(code),
            "start": f"STATUS:{code}",
            "end": _status_label(code),
        },
    )


@router.callback_query(ScheduleState.assign_kind, F.data == "sch_kind_shift")
async def assign_shift_start(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await state.set_state(ScheduleState.start_time)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("⏰ Kelish vaqtini tanlang:", reply_markup=_schedule_start_kb())


@router.callback_query(ScheduleState.start_time, F.data.startswith("t_start_"))
async def start_time_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    start_time = callback.data.split("_", 2)[2]
    await state.update_data(selected_start_time=start_time)
    await state.set_state(ScheduleState.end_time)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"⏰ Kelish vaqti: <b>{start_time}</b>\n⏳ Ketish vaqtini tanlang:",
            reply_markup=_schedule_end_kb(),
        )


@router.callback_query(ScheduleState.end_time, F.data == "sch_back_to_start")
async def end_back_to_start(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await _render_current_employee_assign(callback, state)


@router.callback_query(ScheduleState.end_time, F.data.startswith("t_end_"))
async def end_time_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    end_time = callback.data.split("_", 2)[2]
    data = await state.get_data()
    start_time = data.get("selected_start_time")
    if not start_time:
        await _safe_answer(callback, "Kelish vaqti topilmadi.", alert=True)
        return
    if _time_to_minutes(end_time) <= _time_to_minutes(start_time):
        await _safe_answer(callback, "Ketish vaqti kelish vaqtidan keyin bo'lishi kerak.", alert=True)
        return
    await _append_selected_employee_item(callback, state, {"kind": "shift", "start": start_time, "end": end_time})


@router.callback_query(ScheduleState.confirm, F.data == "sch_add_more")
async def loop_add_same_shop(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await select_employee_step(callback, state, data["selected_shop"])


@router.callback_query(ScheduleState.confirm, F.data == "sch_change_shop")
async def loop_change_shop(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await show_shop_selection(callback, state, data["selected_date"])


@router.callback_query(ScheduleState.confirm, F.data == "sch_remove_last")
async def remove_last_item(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    schedule_list = data.get("schedule_list", [])
    if not schedule_list:
        await _safe_answer(callback, "Ro'yxat bo'sh.", alert=True)
        return
    schedule_list.pop()
    await state.update_data(schedule_list=schedule_list)
    if not schedule_list:
        await show_shop_selection(callback, state, data["selected_date"])
        return
    await _render_confirm(callback, state)


@router.callback_query(ScheduleState.confirm, F.data == "sch_set_repeat")
async def set_repeat(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    await state.set_state(ScheduleState.repeat_select)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("🔁 Repeat necha hafta davom etsin?", reply_markup=repeat_weeks_kb(int(data.get("repeat_weeks", 0))))


@router.callback_query(ScheduleState.repeat_select, F.data == "sch_repeat_back")
async def repeat_back(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    await _render_confirm(callback, state)


@router.callback_query(ScheduleState.repeat_select, F.data.startswith("sch_repeat_"))
async def repeat_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    weeks = int(callback.data.split("_")[-1])
    await state.update_data(repeat_weeks=weeks)
    await _render_confirm(callback, state)


@router.callback_query(ScheduleState.confirm, F.data == "sch_cancel")
async def cancel_sch(callback: CallbackQuery, state: FSMContext, role: str = "unknown"):
    await _safe_answer(callback)
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer("Grafik tuzish bekor qilindi.", reply_markup=main_menu(role))


@router.callback_query(ScheduleState.confirm, F.data == "sch_finish_save")
async def finish_save_only(callback: CallbackQuery, state: FSMContext, role: str = "unknown"):
    await _safe_answer(callback)
    data = await state.get_data()
    schedule_list = data.get("schedule_list", [])
    repeat_weeks = int(data.get("repeat_weeks", 0))
    if not schedule_list:
        with suppress(TelegramBadRequest):
            await callback.message.edit_text("Ro'yxat bo'sh.")
        await state.clear()
        return

    expanded_items = _expand_with_repeat(schedule_list, repeat_weeks)
    conflicts = await _collect_save_conflicts(expanded_items)
    if conflicts:
        text = "\n".join(conflicts[:5])
        if len(conflicts) > 5:
            text += f"\n... va yana {len(conflicts) - 5} ta"
        await _safe_answer(callback, text, alert=True)
        return

    with suppress(TelegramBadRequest):
        await callback.message.edit_text("⏳ Grafik bazaga yozilmoqda...")
    try:
        ok = await db.append_schedule_rows(expanded_items)
        if not ok:
            raise RuntimeError("Grafikni bulk saqlab bo'lmadi")
        base_preview = (await build_preview_text(schedule_list, repeat_weeks)).replace("✅ Tasdiqlaysizmi?", "").strip()
        final_text = (
            "✅ <b>GRAFIK SAQLANDI</b>\n\n"
            f"{base_preview}\n\n"
            f"🧾 Jami yozilgan satr: <b>{len(expanded_items)}</b>\n"
        )
        await _log_action(
            callback.from_user.id,
            role,
            "schedule_saved",
            {
                "base_date": schedule_list[0]["date"],
                "repeat_weeks": repeat_weeks,
                "base_items": len(schedule_list),
                "saved_items": len(expanded_items),
            },
        )
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        if role == "admin":
            await callback.message.answer(final_text + "\n📤 Guruhga ham jo'natasizmi?", reply_markup=publish_confirm_kb())
        else:
            await callback.message.answer(final_text)
    except Exception as e:
        await callback.message.answer(f"Xatolik: {e}")
    await state.clear()


@router.callback_query(F.data == "sch_publish_yes")
async def publish_yes(callback: CallbackQuery):
    await _safe_answer(callback, "Guruhga yuborildi! ✅", alert=True)
    try:
        await callback.message.copy_to(chat_id=config.group_chat_id)
        await _log_action(callback.from_user.id, "admin", "schedule_published", {"chat_id": config.group_chat_id})
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        await callback.message.answer(f"Guruhga yuborishda xato: {e}")


@router.callback_query(F.data == "sch_publish_no")
async def publish_no(callback: CallbackQuery):
    await _safe_answer(callback, "Faqat saqlandi ✅", alert=True)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "sch_broadcast_now")
async def broadcast_schedule_to_group(callback: CallbackQuery):
    await publish_yes(callback)


class OverallScheduleState(StatesGroup):
    date = State()


@router.message(F.text == "📆 Umumiy grafik")
async def overall_start(message: Message, state: FSMContext, role: str):
    if role not in ["admin", "manager"]:
        return
    await state.clear()
    now = datetime.now()
    await state.set_state(OverallScheduleState.date)
    await message.answer("📆 Qaysi sana uchun umumiy grafik?", reply_markup=build_calendar(now.year, now.month))


@router.callback_query(OverallScheduleState.date, F.data.startswith("cal_date_"))
async def overall_date_selected(callback: CallbackQuery, state: FSMContext, role: str):
    await _safe_answer(callback)
    date_str = callback.data.split("_", 2)[2]
    items = await _get_graphic_rows(date_str)
    text = _group_graphic_text(date_str, items)
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    if role == "admin":
        await callback.message.answer(text, reply_markup=send_to_group_kb())
    else:
        await callback.message.answer(text)


class EditScheduleState(StatesGroup):
    date = State()
    pick_row = State()
    editing_start = State()
    editing_end = State()
    editing_shop = State()
    editing_status = State()


def _rows_list_kb(items: list[dict]):
    builder = InlineKeyboardBuilder()
    for it in items:
        label = f"{it.get('shop', '')} | {it.get('name', '')} | {_item_display_range(it)}"
        builder.button(text=label[:60], callback_data=f"ed_row_{it['row']}")
    builder.button(text="⬅ Sana tanlash", callback_data="ed_back_to_date")
    builder.adjust(1)
    return builder.as_markup()


def _edit_actions_kb(item: dict):
    b = InlineKeyboardBuilder()
    if not _is_status_entry(item):
        b.button(text="⏰ Start", callback_data=f"ed_act_start_{item['row']}")
        b.button(text="⏰ End", callback_data=f"ed_act_end_{item['row']}")
    b.button(text="📌 Status", callback_data=f"ed_act_status_{item['row']}")
    b.button(text="🏪 Shop", callback_data=f"ed_act_shop_{item['row']}")
    b.button(text="🗑 O'chirish", callback_data=f"ed_act_del_{item['row']}")
    b.button(text="⬅ Ro'yxatga qaytish", callback_data="ed_act_back")
    b.adjust(2, 2, 1)
    return b.as_markup()


async def _render_edit_row(callback: CallbackQuery, state: FSMContext, row_num: int):
    items = await _get_graphic_rows()
    it = next((x for x in items if x["row"] == row_num), None)
    if not it:
        await callback.message.answer("Qator topilmadi (o'chirilgan bo'lishi mumkin).")
        await state.clear()
        return
    txt = (
        f"✏️ <b>Tahrirlash</b>\n\n"
        f"📆 Sana: <b>{it['date']}</b>\n"
        f"🏪 Magazin: <b>{it['shop']}</b>\n"
        f"👤 Xodim: <b>{it['name']}</b>\n"
        f"🧩 Holat: <b>{_item_display_range(it)}</b>\n"
        f"🧾 Row: <code>{row_num}</code>"
    )
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(txt, reply_markup=_edit_actions_kb(it))


def _time_picker_with_back(prefix: str, back_cb: str):
    b = InlineKeyboardBuilder()
    day_hours = list(range(8, 24))
    night_hours = [0, 1, 2]
    for h in (day_hours + night_hours):
        time_str = f"{h:02d}:00"
        b.button(text=time_str, callback_data=f"{prefix}_{time_str}")
    b.button(text="⬅ Orqaga", callback_data=back_cb)
    b.adjust(4)
    return b.as_markup()


def _schedule_start_kb():
    b = InlineKeyboardBuilder()
    day_hours = list(range(8, 24))
    night_hours = [0, 1, 2]
    for h in (day_hours + night_hours):
        time_str = f"{h:02d}:00"
        b.button(text=time_str, callback_data=f"t_start_{time_str}")
    b.button(text="🚫 Dam olish", callback_data="sch_kind_day_off")
    b.button(text="🏖 отпуск", callback_data="sch_kind_vacation")
    b.button(text="🤒 больничный", callback_data="sch_kind_sick_leave")
    b.button(text="⬅ Xodimlarga qaytish", callback_data="sch_back_to_employee")
    b.adjust(4, 4, 4, 4, 3, 1)
    return b.as_markup()


def _schedule_end_kb():
    return _time_picker_with_back("t_end", "sch_back_to_start")


def _status_only_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🚫 Dam olish", callback_data="ed_status_day_off")
    b.button(text="🏖 отпуск", callback_data="ed_status_vacation")
    b.button(text="🤒 больничный", callback_data="ed_status_sick_leave")
    b.button(text="⬅ Orqaga", callback_data="ed_cancel_time")
    b.adjust(2, 1, 1)
    return b.as_markup()


@router.message(F.text.in_(["✏️ Grafik tahrirlash", "✏️ Grafikni tahrirlash"]))
async def edit_start(message: Message, state: FSMContext, role: str):
    if role != "admin":
        await message.answer("Bu bo'lim faqat adminlar uchun!")
        return
    await state.clear()
    now = datetime.now()
    await state.set_state(EditScheduleState.date)
    await message.answer("✏️ Qaysi sana grafikini tahrirlaysiz?", reply_markup=build_calendar(now.year, now.month))


@router.callback_query(EditScheduleState.date, F.data.startswith("cal_date_"))
async def edit_date_selected(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    date_str = callback.data.split("_", 2)[2]
    items = await _get_graphic_rows(date_str)
    await state.update_data(edit_date=date_str)
    await state.set_state(EditScheduleState.pick_row)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(_group_graphic_text(date_str, items) + "\n\n✏️ <b>Qaysi qatorni tahrirlaysiz?</b>", reply_markup=_rows_list_kb(items))


@router.callback_query(EditScheduleState.pick_row, F.data == "ed_back_to_date")
async def edit_back_to_date(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    now = datetime.now()
    await state.set_state(EditScheduleState.date)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("✏️ Qaysi sana grafikini tahrirlaysiz?", reply_markup=build_calendar(now.year, now.month))


@router.callback_query(EditScheduleState.pick_row, F.data.startswith("ed_row_"))
async def edit_pick_row(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    row_num = int(callback.data.split("_", 2)[2])
    await state.update_data(edit_row=row_num)
    await _render_edit_row(callback, state, row_num)


@router.callback_query(F.data == "ed_act_back")
async def edit_back_to_rows(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    date_str = data.get("edit_date")
    items = await _get_graphic_rows(date_str)
    await state.set_state(EditScheduleState.pick_row)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(_group_graphic_text(date_str, items) + "\n\n✏️ <b>Qaysi qatorni tahrirlaysiz?</b>", reply_markup=_rows_list_kb(items))


@router.callback_query(F.data.startswith("ed_act_start_"))
async def edit_start_time(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    row_num = int(callback.data.split("_")[-1])
    await state.update_data(edit_row=row_num)
    await state.set_state(EditScheduleState.editing_start)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("⏰ Yangi START vaqtni tanlang:", reply_markup=_time_picker_with_back("ed_start", "ed_cancel_time"))


@router.callback_query(F.data.startswith("ed_act_end_"))
async def edit_end_time(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    row_num = int(callback.data.split("_")[-1])
    await state.update_data(edit_row=row_num)
    await state.set_state(EditScheduleState.editing_end)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("⏰ Yangi END vaqtni tanlang:", reply_markup=_time_picker_with_back("ed_end", "ed_cancel_time"))


@router.callback_query(F.data.startswith("ed_act_shop_"))
async def edit_shop(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    row_num = int(callback.data.split("_")[-1])
    await state.update_data(edit_row=row_num)
    await state.set_state(EditScheduleState.editing_shop)
    shops = await db.get_shops()
    shop_map = _make_shop_map(shops)
    await state.update_data(edit_shop_map=shop_map)
    b = InlineKeyboardBuilder()
    for token, shop in shop_map.items():
        b.button(text=shop, callback_data=f"ed_shop_{token}")
    b.button(text="⬅ Orqaga", callback_data="ed_cancel_time")
    b.adjust(2, 2, 2, 1)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("🏪 Yangi magazinni tanlang:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("ed_act_status_"))
async def edit_status(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    row_num = int(callback.data.split("_")[-1])
    await state.update_data(edit_row=row_num)
    await state.set_state(EditScheduleState.editing_status)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("📌 Yangi statusni tanlang:", reply_markup=_status_only_kb())


@router.callback_query(F.data.startswith("ed_act_del_"))
async def edit_delete_row(callback: CallbackQuery, state: FSMContext, role: str = "admin"):
    await _safe_answer(callback, "Qator o'chirildi ✅", alert=True)
    row_num = int(callback.data.split("_")[-1])
    ws = await db._get_worksheet("График")
    await ws.delete_rows(row_num)
    db.invalidate_sheet_cache("График")
    await _log_action(callback.from_user.id, role, "schedule_row_deleted", {"row": row_num})
    data = await state.get_data()
    date_str = data.get("edit_date")
    items = await _get_graphic_rows(date_str)
    await state.set_state(EditScheduleState.pick_row)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(_group_graphic_text(date_str, items) + "\n\n✏️ <b>Qaysi qatorni tahrirlaysiz?</b>", reply_markup=_rows_list_kb(items))


@router.callback_query(F.data == "ed_cancel_time")
async def edit_cancel_time(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)
    data = await state.get_data()
    row_num = data.get("edit_row")
    if not row_num:
        await state.clear()
        return
    await state.set_state(EditScheduleState.pick_row)
    await _render_edit_row(callback, state, int(row_num))


@router.callback_query(EditScheduleState.editing_start, F.data.startswith("ed_start_"))
async def edit_start_time_save(callback: CallbackQuery, state: FSMContext, role: str = "admin"):
    await _safe_answer(callback)
    new_time = callback.data.split("_", 2)[2]
    data = await state.get_data()
    row_num = int(data["edit_row"])
    items = await _get_graphic_rows()
    it = next((x for x in items if x["row"] == row_num), None)
    if not it:
        await _safe_answer(callback, "Qator topilmadi.", alert=True)
        await state.clear()
        return
    if _time_to_minutes(it["end"]) <= _time_to_minutes(new_time):
        await _safe_answer(callback, "End vaqti startdan keyin bo'lishi kerak.", alert=True)
        return
    probe = dict(it)
    probe["start"] = new_time
    for ex in items:
        if ex["row"] != row_num and _items_conflict(probe, ex):
            await _safe_answer(callback, _conflict_message(probe, ex), alert=True)
            return
    ws = await db._get_worksheet("График")
    await ws.update_cell(row_num, 5, new_time)
    db.invalidate_sheet_cache("График")
    await _log_action(callback.from_user.id, role, "schedule_edit_start", {"row": row_num, "start": new_time})
    await state.set_state(EditScheduleState.pick_row)
    await _render_edit_row(callback, state, row_num)


@router.callback_query(EditScheduleState.editing_end, F.data.startswith("ed_end_"))
async def edit_end_time_save(callback: CallbackQuery, state: FSMContext, role: str = "admin"):
    await _safe_answer(callback)
    new_time = callback.data.split("_", 2)[2]
    data = await state.get_data()
    row_num = int(data["edit_row"])
    items = await _get_graphic_rows()
    it = next((x for x in items if x["row"] == row_num), None)
    if not it:
        await _safe_answer(callback, "Qator topilmadi.", alert=True)
        await state.clear()
        return
    if _time_to_minutes(new_time) <= _time_to_minutes(it["start"]):
        await _safe_answer(callback, "End vaqti startdan keyin bo'lishi kerak.", alert=True)
        return
    probe = dict(it)
    probe["end"] = new_time
    for ex in items:
        if ex["row"] != row_num and _items_conflict(probe, ex):
            await _safe_answer(callback, _conflict_message(probe, ex), alert=True)
            return
    ws = await db._get_worksheet("График")
    await ws.update_cell(row_num, 6, new_time)
    db.invalidate_sheet_cache("График")
    await _log_action(callback.from_user.id, role, "schedule_edit_end", {"row": row_num, "end": new_time})
    await state.set_state(EditScheduleState.pick_row)
    await _render_edit_row(callback, state, row_num)


@router.callback_query(EditScheduleState.editing_shop, F.data.startswith("ed_shop_"))
async def edit_shop_save(callback: CallbackQuery, state: FSMContext, role: str = "admin"):
    await _safe_answer(callback)
    token = callback.data.split("ed_shop_", 1)[1]
    data = await state.get_data()
    row_num = int(data["edit_row"])
    shop = data.get("edit_shop_map", {}).get(token)
    if not shop:
        await _safe_answer(callback, "Magazin topilmadi.", alert=True)
        return
    ws = await db._get_worksheet("График")
    await ws.update_cell(row_num, 4, shop)
    db.invalidate_sheet_cache("График")
    await _log_action(callback.from_user.id, role, "schedule_edit_shop", {"row": row_num, "shop": shop})
    await state.set_state(EditScheduleState.pick_row)
    await _render_edit_row(callback, state, row_num)


@router.callback_query(EditScheduleState.editing_status, F.data.startswith("ed_status_"))
async def edit_status_save(callback: CallbackQuery, state: FSMContext, role: str = "admin"):
    await _safe_answer(callback)
    code = callback.data.split("ed_status_", 1)[1]
    data = await state.get_data()
    row_num = int(data["edit_row"])
    items = await _get_graphic_rows()
    it = next((x for x in items if x["row"] == row_num), None)
    if not it:
        await _safe_answer(callback, "Qator topilmadi.", alert=True)
        await state.clear()
        return
    probe = dict(it)
    probe["kind"] = "status"
    probe["status_code"] = code
    probe["start"] = f"STATUS:{code}"
    probe["end"] = _status_label(code)
    for ex in items:
        if ex["row"] != row_num and _items_conflict(probe, ex):
            await _safe_answer(callback, _conflict_message(probe, ex), alert=True)
            return
    ws = await db._get_worksheet("График")
    await ws.update_cell(row_num, 5, f"STATUS:{code}")
    await ws.update_cell(row_num, 6, _status_label(code))
    db.invalidate_sheet_cache("График")
    await _log_action(callback.from_user.id, role, "schedule_edit_status", {"row": row_num, "status": code})
    await state.set_state(EditScheduleState.pick_row)
    await _render_edit_row(callback, state, row_num)
