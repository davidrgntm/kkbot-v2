import math
from io import BytesIO
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import config
from database.sqlite_db import db
from keyboards.builders import request_location, main_menu
from services.attendance_verification import verify_attendance, save_bytes_image

router = Router()
router.message.filter(F.chat.type == "private")


class AttendanceState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_location = State()


def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _decision_emoji(status: str) -> str:
    return {"approved": "✅", "needs_review": "⚠️", "rejected": "❌"}.get(status, "⚠️")


def _decision_text(result: dict) -> str:
    return (
        f"{_decision_emoji(result.get('final_status'))} <b>Tekshiruv:</b> {result.get('final_status')}\n"
        f"🧠 Yuz: <b>{result.get('face_status')}</b> ({result.get('face_score')})\n"
        f"📍 Lokatsiya: <b>{result.get('location_status')}</b>"
        + (f" · {result.get('distance_m')}m" if result.get('distance_m') is not None else "")
    )


async def _download_telegram_photo(message: Message, photo_id: str, telegram_id: int | str, prefix: str) -> str:
    file = await message.bot.get_file(photo_id)
    bio = BytesIO()
    await message.bot.download_file(file.file_path, destination=bio)
    return save_bytes_image(bio.getvalue(), str(telegram_id), prefix=prefix)


@router.message(F.text == "🟢 Keldim")
async def cmd_start_shift(message: Message, state: FSMContext, staff: dict):
    active_row = await db.get_active_shift_row(message.from_user.id)
    if active_row:
        await message.answer("Sizda allaqachon ochiq smena bor! Avval '🔴 Ketdim' tugmasini bosing.")
        return
    await state.set_state(AttendanceState.waiting_for_photo)
    await state.update_data(action="start")
    await message.answer("🧠 <b>AI tekshiruv</b>\nIltimos, yuzingiz aniq ko‘rinadigan selfi yuboring:", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == "🔴 Ketdim")
async def cmd_end_shift(message: Message, state: FSMContext, staff: dict):
    active_row = await db.get_active_shift_row(message.from_user.id)
    if not active_row:
        await message.answer("Sizda ochiq smena yo'q. Avval '🟢 Keldim' tugmasini bosing.")
        return
    await state.update_data(shift_row=active_row, action="end")
    await state.set_state(AttendanceState.waiting_for_photo)
    await message.answer("🧠 <b>AI tekshiruv</b>\nIshni yakunlash uchun yuzingiz aniq ko‘rinadigan selfi yuboring:", reply_markup=ReplyKeyboardRemove())


@router.message(AttendanceState.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(AttendanceState.waiting_for_location)
    await message.answer("📍 Endi GPS lokatsiyani yuboring. Bot yuz + lokatsiyani tekshiradi:", reply_markup=request_location())


@router.message(AttendanceState.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext, staff: dict, role: str):
    data = await state.get_data()
    action = data.get("action")
    photo_id = data.get("photo_id")
    name = staff.get("Имя") or "Xodim"
    u_lat = message.location.latitude
    u_lon = message.location.longitude
    accuracy = getattr(message.location, "horizontal_accuracy", None)
    loc_url = f"https://www.google.com/maps?q={u_lat},{u_lon}"

    try:
        selfie_path = await _download_telegram_photo(message, photo_id, message.from_user.id, f"bot_{action}")
    except Exception:
        selfie_path = ""

    if action == "start":
        result = verify_attendance(
            str(message.from_user.id),
            "check_in",
            selfie_path,
            u_lat,
            u_lon,
            accuracy,
            source="bot",
            fallback_shop=str(staff.get("Магазин", "")).split(",")[0].strip(),
        )
        detected_shop = result.get("shop") or str(staff.get("Магазин", "")).split(",")[0].strip()
        staff_for_shift = staff.copy()
        staff_for_shift["Магазин"] = detected_shop

        if result.get("final_status") == "rejected":
            await message.answer(
                f"❌ <b>Smena ochilmadi.</b>\n{_decision_text(result)}\n\nAdmin bilan bog‘laning.",
                reply_markup=main_menu(role),
            )
            await state.clear()
            return

        success = await db.start_shift(staff_for_shift, photo_id, loc_url)
        if success:
            shift_id = await db.get_active_shift_row(message.from_user.id)
            # update last check shift_id
            try:
                db._execute("UPDATE attendance_checks SET shift_id=? WHERE id=?", (shift_id, int(result.get("check_id"))))
            except Exception:
                pass
            await message.answer(
                f"✅ <b>Xush kelibsiz, {name}!</b>\n🏪 {detected_shop}\n{_decision_text(result)}",
                reply_markup=main_menu(role),
            )
            try:
                caption = (
                    f"🟢 <b>KELDI</b>\n"
                    f"👤 {name}\n🏪 {detected_shop}\n"
                    f"{_decision_text(result)}\n"
                    f"📍 <a href='{loc_url}'>Xarita</a>"
                )
                await message.bot.send_photo(chat_id=config.group_chat_id, photo=photo_id, caption=caption)
            except Exception:
                pass
        else:
            await message.answer("❌ Xatolik yuz berdi.", reply_markup=main_menu(role))

    elif action == "end":
        shift_row = data.get("shift_row")
        shift = await db.get_shift_by_id(shift_row)
        saved_shop = shift.get("shop") if shift else str(staff.get("Магазин", "")).split(",")[0].strip()
        result = verify_attendance(
            str(message.from_user.id),
            "check_out",
            selfie_path,
            u_lat,
            u_lon,
            accuracy,
            shift_id=int(shift_row),
            source="bot",
            fallback_shop=saved_shop,
        )
        if result.get("final_status") == "rejected":
            await message.answer(
                f"❌ <b>Smena yopilmadi.</b>\n{_decision_text(result)}\n\nAdmin bilan bog‘laning.",
                reply_markup=main_menu(role),
            )
            await state.clear()
            return
        worked_text = await db.end_shift(shift_row, photo_id=photo_id, location=loc_url)
        await message.answer(
            f"🔴 <b>Ish yakunlandi!</b>\n⏱ Ishladi: {worked_text}\n🏪 {saved_shop}\n{_decision_text(result)}",
            reply_markup=main_menu(role),
        )
        try:
            caption = (
                f"🔴 <b>KETDI</b>\n"
                f"👤 {name}\n🏪 {saved_shop}\n⏱ Ishladi: {worked_text}\n"
                f"{_decision_text(result)}\n"
                f"📍 <a href='{loc_url}'>Xarita</a>"
            )
            await message.bot.send_photo(chat_id=config.group_chat_id, photo=photo_id, caption=caption)
        except Exception:
            pass
    await state.clear()
