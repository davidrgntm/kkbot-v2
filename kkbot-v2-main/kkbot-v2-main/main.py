import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from database.sqlite_db import db
from middlewares.auth import AuthMiddleware

from handlers import (
    common,
    attendance,
    admin,
    reporting,
    manager,
    admin_schedule,
    super_admin,
)


async def start_web_server():
    import uvicorn
    from web_server import app

    try:
        from final_premium_patch import patch_schedule_messages
        patch_schedule_messages()
        logging.info("Final schedule patch ulandi ✅")
    except Exception as e:
        logging.exception("Final schedule patch ulanmagan: %s", e)

    try:
        from kkb_stable_patch import apply_stable_patch
        apply_stable_patch(app)
        logging.info("KKB stable web patch ulandi ✅")
    except Exception as e:
        logging.exception("KKB stable web patch ulanmagan: %s", e)

    port = int(os.environ.get("PORT", "8000"))
    web_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(web_config)
    logging.info(f"Web panel ishga tushyapti: 0.0.0.0:{port}")
    await server.serve()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    bot = Bot(token=config.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    dp.include_router(super_admin.router)
    dp.include_router(common.router)
    dp.include_router(admin_schedule.router)
    dp.include_router(manager.router)
    dp.include_router(admin.router)
    dp.include_router(reporting.router)
    dp.include_router(attendance.router)

    try:
        from final_premium_patch import patch_schedule_messages
        patch_schedule_messages()
        logging.info("Final schedule patch ulandi ✅")
    except Exception as e:
        logging.exception("Final schedule patch ulanmagan: %s", e)

    try:
        await db.get_all_staff(force_refresh=True)
        logging.info("SQLite baza bilan aloqa o'rnatildi ✅")
    except Exception as e:
        logging.error(f"SQLite baza xatosi: {e}")
        return

    logging.info("Bot ishga tushdi 🚀")

    web_task = None
    if os.environ.get("WEB_ENABLED", "1") not in {"0", "false", "False", "no"}:
        web_task = asyncio.create_task(start_web_server())

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        if web_task:
            web_task.cancel()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
