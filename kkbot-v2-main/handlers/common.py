from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from keyboards.builders import main_menu

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    staff: dict = None,
    role: str = None,
    staff_lookup_error: bool = False,
):
    await state.clear()

    if not staff:
        if staff_lookup_error:
            await message.answer("⏳ Bot yangilanmoqda yoki baza bilan ulanmoqda. 5–10 soniyadan keyin /start ni qayta yuboring.")
        else:
            await message.answer("⛔️ Siz tizimda ro'yxatdan o'tmagansiz.")
        return

    name = staff.get("Имя", "Foydalanuvchi")

    welcome_text = (
        f"👋 Salom, <b>{name}</b>!\n\n"
        f"🚀 <b>Keldi-Ketdi (KKB)</b> — Davomatni nazorat qilish tizimiga xush kelibsiz.\n\n"
        f"📍 <b>Sizning statusingiz:</b> {role.capitalize()}\n"
        f"👇 Ishni boshlash uchun quyidagi tugmalardan foydalaning:"
    )

    await message.answer(welcome_text, reply_markup=main_menu(role))


@router.message(F.text.in_({"🔙 Bekor qilish", "⬅ Назад"}))
async def cmd_cancel(message: Message, state: FSMContext, role: str):
    await state.clear()
    await message.answer("🖥 <b>Bosh menyu</b>", reply_markup=main_menu(role))
