from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_settings
from .db import Database
from .handlers import register_handlers
from .sanaei_api import SanaeiAPI


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    db = Database(settings.database_path)
    await db.connect()
    await db.init()

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    panel = SanaeiAPI(settings)
    register_handlers(dispatcher, db, settings, panel)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
