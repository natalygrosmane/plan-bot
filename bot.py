import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config
from services.ai_service import (
    process_evening_review,
    process_morning_focus,
    process_weekly_review,
    transcribe_audio,
)
from services.storage import (
    add_to_inbox,
    clear_inbox,
    read_backlog,
    read_inbox,
    read_todo,
    write_backlog,
    write_todo,
)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("PlanBot")

# In-memory storage for evening plan confirmation
PENDING_EVENING_PLANS: dict[int, str] = {}


class EventLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        user_str = f"{user.id} (@{user.username or user.first_name})" if user else "Unknown"
        if hasattr(event, "text") and event.text:
            logger.info(f"📨 [{user_str}] Text: {event.text}")
        elif hasattr(event, "voice") and event.voice:
            logger.info(f"🎙 [{user_str}] Voice note: {event.voice.duration}s")
        elif hasattr(event, "data") and event.data:
            logger.info(f"🔘 [{user_str}] Callback: {event.data}")
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"❌ Error handling event from {user_str}: {e}", exc_info=True)
            raise


async def start_healthcheck_server():
    """Starts a minimal HTTP health check server if PORT is assigned by cloud providers (Railway, Render, etc.)."""
    port_str = os.getenv("PORT")
    if not port_str:
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None

    app = web.Application()

    async def health(request):
        return web.Response(text="OK - PlanBot is running")

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck HTTP server successfully started on port {port}")
    return runner


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="☀️ Доброе утро"), KeyboardButton(text="🌙 Итоги дня")],
            [KeyboardButton(text="🔄 Ревизия недели"), KeyboardButton(text="📋 Показать To-Do")],
        ],
        resize_keyboard=True,
    )


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


dp = Dispatcher(storage=MemoryStorage())
dp.message.middleware(EventLoggingMiddleware())
dp.callback_query.middleware(EventLoggingMiddleware())


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer(
            f"⛔️ Доступ ограничен.\nВаш Telegram ID: <code>{message.from_user.id}</code>\n"
            f"Добавьте его в <code>ALLOWED_USER_IDS</code> в переменных окружения на сервере.",
        )
        return

    welcome_text = (
        "👋 <b>Привет! Я твой персональный ассистент по разгрузке головы и планированию.</b>\n\n"
        "⚡️ <b>Как со мной работать:</b>\n"
        "• <b>Сброс мыслей</b>: отправь текст или аудио — я сохраню в <code>inbox.md</code>.\n"
        "  - Теги: <code>!задача</code>, <code>!рынок</code>, <code>!идея</code>\n"
        "• <b>Утро</b>: напиши «Доброе утро» — выдам Top-3 и фокус дня.\n"
        "• <b>Вечер</b>: напиши «Итоги дня» — разберу инбокс, сгруппирую задачи и подготовлю план на завтра.\n"
        "• <b>Воскресенье</b>: напиши «Ревизия недели» — аудит хвостов и правило 3-х недель.\n"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_authorized(message.from_user.id):
        return
    await cmd_start(message)


@dp.message(F.text == "📋 Показать To-Do")
@dp.message(Command("todo"))
async def cmd_show_todo(message: types.Message):
    if not is_authorized(message.from_user.id):
        return
    todo = await read_todo()
    await message.answer(f"📋 <b>Текущий To-Do:</b>\n\n<pre>{todo}</pre>")


@dp.message(F.voice | F.audio)
async def handle_voice_message(message: types.Message, bot: Bot):
    if not is_authorized(message.from_user.id):
        await message.answer(f"⛔️ Доступ ограничен. ID: <code>{message.from_user.id}</code>")
        return

    audio_obj = message.voice or message.audio
    file_info = await bot.get_file(audio_obj.file_id)
    file_ext = Path(file_info.file_path).suffix or ".ogg"
    local_path = config.TEMP_DIR / f"{audio_obj.file_id}{file_ext}"

    try:
        await bot.download_file(file_info.file_path, destination=local_path)
        transcribed_text = await transcribe_audio(local_path)
    except Exception as e:
        logger.error(f"Error processing voice: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка расшифровки аудио: {e}")
        return
    finally:
        if local_path.exists():
            local_path.unlink()

    if not transcribed_text:
        await message.answer("⚠️ Не удалось распознать речь в сообщении.")
        return

    clean_lower = transcribed_text.strip().lower()
    if clean_lower in ["итоги дня", "давай подведём итоги", "итоги"]:
        await message.answer(f"🗣 <i>«{transcribed_text}»</i>")
        await trigger_evening_review(message)
    elif clean_lower in ["доброе утро", "утренний фокус", "фокус"]:
        await message.answer(f"🗣 <i>«{transcribed_text}»</i>")
        await trigger_morning_focus(message)
    elif clean_lower in ["ревизия недели", "итоги недели"]:
        await message.answer(f"🗣 <i>«{transcribed_text}»</i>")
        await trigger_weekly_review(message)
    else:
        reply_phrase, _ = await add_to_inbox(transcribed_text)
        await message.answer(f"🗣 <i>«{transcribed_text}»</i>\n{reply_phrase}")


async def trigger_evening_review(message: types.Message):
    inbox_content = await read_inbox()
    lines = [
        line.strip()
        for line in inbox_content.splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("_")
    ]
    if not lines:
        await message.answer("📭 <b>Inbox пуст!</b> На сегодня нет накопленных мыслей.")
        return

    status_msg = await message.answer("🌙 Разбираю накопленные мысли и готовлю план...")
    try:
        review_result = await process_evening_review(inbox_content)
        PENDING_EVENING_PLANS[message.from_user.id] = review_result

        display_text = re.sub(r"```json_plan[\s\S]*?```", "", review_result).strip()

        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Утвердить и обновить файлы", callback_data="confirm_evening"
                    )
                ]
            ]
        )
        await status_msg.delete()
        await message.answer(display_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in evening review: {e}", exc_info=True)
        await status_msg.edit_text(f"⚠️ Ошибка при формировании итогов: {e}")


async def trigger_morning_focus(message: types.Message):
    todo_content = await read_todo()
    status_msg = await message.answer("☀️ Формирую фокус дня...")
    try:
        morning_result = await process_morning_focus(todo_content)
        await status_msg.delete()
        await message.answer(morning_result, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in morning focus: {e}", exc_info=True)
        await status_msg.edit_text(f"⚠️ Ошибка при формировании утреннего фокуса: {e}")


async def trigger_weekly_review(message: types.Message):
    todo_content = await read_todo()
    backlog_content = await read_backlog()
    status_msg = await message.answer("🔄 Провожу ревизию недели...")
    try:
        review_result = await process_weekly_review(todo_content, backlog_content)
        await status_msg.delete()
        await message.answer(review_result, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in weekly review: {e}", exc_info=True)
        await status_msg.edit_text(f"⚠️ Ошибка при ревизии недели: {e}")


@dp.callback_query(F.data == "confirm_evening")
async def callback_confirm_evening(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    raw_plan = PENDING_EVENING_PLANS.get(user_id)
    if not raw_plan:
        await callback.answer("План не найден или уже утверждён.", show_alert=True)
        return

    json_match = re.search(r"```json_plan([\s\S]*?)```", raw_plan)
    if json_match:
        try:
            plan_data = json.loads(json_match.group(1).strip())
            top_3 = plan_data.get("top_3", [])
            hard_events = plan_data.get("hard_events", [])
            morning = plan_data.get("morning", [])
            day = plan_data.get("day", [])
            evening = plan_data.get("evening", [])

            top_3_str = "\n".join([f"{i+1}. {task}" for i, task in enumerate(top_3)]) or "1.\n2.\n3."
            hard_str = "\n".join([f"- {h}" for h in hard_events]) or "- "
            m_str = "\n".join([f"- [ ] {m}" for m in morning]) or "- [ ] "
            d_str = "\n".join([f"- [ ] {d}" for d in day]) or "- [ ] "
            e_str = "\n".join([f"- [ ] {e}" for e in evening]) or "- [ ] "

            new_todo = f"""# To-Do — Задачи и расписание

## Фокус дня (Top-3)
{top_3_str}

---

## Жёсткие дела (Hard Events / по времени)
{hard_str}

---

## Гибкие задачи (To-Do по блокам)

### Утро
{m_str}

### День
{d_str}

### Вечер
{e_str}
"""
            await write_todo(new_todo)

            backlog_items = plan_data.get("backlog_items", {})
            current_backlog = await read_backlog()
            appendices = []
            for cat, items in backlog_items.items():
                if items:
                    for it in items:
                        appendices.append(f"- [{cat.upper()}] {it}")
            if appendices:
                current_backlog += (
                    "\n\n### Новые идеи из итогов дня:\n" + "\n".join(appendices) + "\n"
                )
                await write_backlog(current_backlog)

        except Exception as e:
            logger.warning(f"Could not parse json_plan, keeping raw plan: {e}")

    await clear_inbox()
    PENDING_EVENING_PLANS.pop(user_id, None)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✅ <b>План утверждён!</b>\n"
        "— Задачи записаны в <code>todo.md</code>\n"
        "— Идеи перенесены в <code>backlog.md</code>\n"
        "— <code>inbox.md</code> очищен и готов к новому дню.",
    )
    await callback.answer("Утверждено!")


@dp.message(F.text)
async def handle_text_message(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer(
            f"⛔️ Доступ ограничен.\nВаш ID: <code>{message.from_user.id}</code>\n"
            f"Добавьте его в <code>ALLOWED_USER_IDS</code> в переменных окружения на сервере.",
        )
        return

    text = message.text.strip()
    lower = text.lower()

    if lower in ["итоги дня", "давай подведём итоги", "итоги", "/evening"]:
        await trigger_evening_review(message)
        return

    if lower in ["доброе утро", "утренний фокус", "фокус", "/morning"]:
        await trigger_morning_focus(message)
        return

    if lower in ["ревизия недели", "итоги недели", "/review"]:
        await trigger_weekly_review(message)
        return

    reply_phrase, _ = await add_to_inbox(text)
    await message.answer(reply_phrase)


async def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "\n" + "=" * 60 + "\n"
            "⚠️ ОШИБКА: TELEGRAM_BOT_TOKEN не задан в .env файле!\n"
            "=" * 60
        )
        return

    # Start healthcheck server for cloud hosting (Railway/Render)
    await start_healthcheck_server()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    bot_info = await bot.get_me()
    logger.info(f"Plan Bot started successfully as @{bot_info.username} (ID: {bot_info.id})")

    # Drop pending updates to avoid conflict and duplicate processing
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Starting long-polling for updates...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Plan Bot stopped.")
