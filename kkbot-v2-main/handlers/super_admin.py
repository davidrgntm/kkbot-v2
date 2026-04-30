from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import config
from database.saas import saas_db
from database.sqlite_db import db
from utils.ctx import sheet_id_ctx

router = Router()
router.message.filter(F.from_user.id.in_(config.get_admin_ids()))

class NewCompanyState(StatesGroup):
    name = State()
    sheet_id = State()
    admin_id = State()

@router.message(Command("new_client"))
async def cmd_new_client(message: Message, state: FSMContext):
    await message.answer(
        "💎 <b>KKB (SaaS) — Super Admin Paneli</b>\n\n"
        "Yangi kompaniya (mijoz) qo'shish uchun nomini kiriting:\n"
        "<i>Namuna: Makro, Korzinka, Jelly Next...</i>"
    )
    await state.set_state(NewCompanyState.name)

# ... (Qolgan kodlar o'zgarishsiz qolaversin, ular allaqachon to'g'ri) ...
@router.message(NewCompanyState.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("📄 Mijozning <b>Google Sheet ID</b> sini yuboring:\n(Jadvalga bot pochtasini Editor qilishni unutmang!)")
    await state.set_state(NewCompanyState.sheet_id)

@router.message(NewCompanyState.sheet_id)
async def process_sheet(message: Message, state: FSMContext):
    await state.update_data(sheet_id=message.text)
    await message.answer("👤 Kompaniya <b>Adminining Telegram ID</b> sini yuboring:")
    await state.set_state(NewCompanyState.admin_id)

@router.message(NewCompanyState.admin_id)
async def process_admin(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Faqat raqam!")
        return
    
    data = await state.get_data()
    admin_id = int(message.text)
    sheet_id = data['sheet_id']
    
    company_id = saas_db.add_company(data['name'], sheet_id, admin_id)
    
    if company_id:
        saas_db.register_user(admin_id, company_id, role="admin")
        await message.answer("⏳ Tizim sozlanmoqda...")
        
        token = sheet_id_ctx.set(sheet_id)
        try:
            ws = await db._get_worksheet("Сотрудники")
            headers = await ws.row_values(1)
            if not headers or headers[0] != "TelegramID":
                await ws.insert_row(["TelegramID", "Username", "Phone", "Имя", "Роль", "Магазин", "Активен"], 1)
            
            await db.add_new_staff(admin_id, "Admin", "admin", "Main")
            success_msg = "✅ Tizim to'liq ishga tushdi!"
        except Exception as e:
            success_msg = f"⚠️ Sheet xatosi: {e}"
        finally:
            sheet_id_ctx.reset(token)
        
        await message.answer(
            f"🎉 <b>Yangi mijoz muvaffaqiyatli ulandi!</b>\n\n"
            f"🏢 <b>{data['name']}</b>\n"
            f"🆔 Tizim ID: <code>{company_id}</code>\n"
            f"{success_msg}"
        )
    else:
        await message.answer("❌ Baza xatosi.")
    await state.clear()
