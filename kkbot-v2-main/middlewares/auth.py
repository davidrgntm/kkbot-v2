from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from database.sqlite_db import db
from utils.ctx import sheet_id_ctx
from config import config


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user = event.from_user
        if not user:
            return await handler(event, data)

        token = sheet_id_ctx.set(config.google_sheet_id)

        try:
            lookup_error = False
            staff = None

            try:
                staff = await db.get_user_by_telegram_id(user.id, strict=True)
            except Exception:
                lookup_error = True

            if not staff:
                try:
                    row = db._execute(
                        "SELECT * FROM users WHERE telegram_id=? AND active=1 ORDER BY id DESC LIMIT 1",
                        (str(user.id),),
                        "one",
                    )
                    if row:
                        staff = db._staff_record(row)
                except Exception:
                    pass

            if not staff:
                try:
                    if int(user.id) in config.get_admin_ids():
                        display_name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or f"Admin {user.id}"
                        await db.add_new_staff(user.id, display_name, "admin", "")
                        staff = await db.get_user_by_telegram_id(user.id, strict=False)
                except Exception:
                    pass

            if staff:
                data["staff"] = staff
                data["role"] = str(staff.get("Роль", "staff")).lower()
                return await handler(event, data)

            if isinstance(event, Message) and (event.text == "/start" or event.text.startswith("/new_client")):
                data["staff_lookup_error"] = lookup_error
                return await handler(event, data)

            if lookup_error:
                if isinstance(event, Message):
                    await event.answer("⏳ Bot hozir yangilanmoqda. Iltimos, bir necha soniyadan keyin qayta urinib ko‘ring.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⏳ Bot yangilanmoqda", show_alert=True)
                return

            if isinstance(event, Message):
                await event.answer(f"⛔️ Siz tizimda ro‘yxatdan o‘tmagansiz.\nID: {user.id}")
            elif isinstance(event, CallbackQuery):
                await event.answer("Ruxsat yo'q", show_alert=True)

        finally:
            sheet_id_ctx.reset(token)
