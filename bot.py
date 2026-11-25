import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonWebApp, Message, WebAppInfo, ChatJoinRequest
)
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN         = os.getenv("BOT_TOKEN")
PRIVATE_CHANNEL   = int(os.getenv("PRIVATE_CHANNEL_ID", "-1000000000000"))
PRIVATE_LINK      = os.getenv("PRIVATE_LINK", "https://t.me/+fallback")
WEBAPP_URL        = os.getenv("WEBAPP_URL", "https://example.com")
PORT              = int(os.getenv("PORT", 8080))

# Твои каналы
CHANNELS = [
    {"id": "@anonscluba", "name": "Анонсы", "url": "https://t.me/anonscluba"},
    {"id": "@novostycluba", "name": "Новости Клуба", "url": "https://t.me/novostycluba"},
]

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher()


def subs_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['name']}", url=c["url"])] for c in CHANNELS]
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def not_subscribed(user_id: int) -> list[dict]:
    result = []
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch["id"], user_id)
            if m.status in ("left", "kicked"):
                result.append(ch)
        except Exception as e:
            logging.warning("check %s: %s", ch["id"], e)
            result.append(ch)
    return result


@dp.message(Command("start"))
async def cmd_start(msg: Message):
    text = (
        f"👋 Привет, <b>{msg.from_user.first_name}</b>!\n\n"
        "Это бот-заявка в <b>закрытый клуб</b>.\n\n"
        "📌 <b>Как попасть:</b>\n"
        "1. Подпишись на каналы ниже\n"
        "2. Нажми «Проверить подписку»\n"
        "3. Нажми на ссылку и подай заявку\n"
        "4. Бот проверит и одобрит вход\n\n"
        "📱 Личный кабинет — через меню слева (☰)."
    )
    await msg.answer(text, reply_markup=subs_kb())


@dp.callback_query(F.data == "check")
async def cb_check(call: CallbackQuery):
    await call.answer("Проверяю…")
    missing = await not_subscribed(call.from_user.id)

    if missing:
        names = "\n".join(f"• {c['name']}" for c in missing)
        await call.message.edit_text(
            f"❌ Ты подписан не на всё:\n\n{names}\n\n"
            "Подпишись и нажми «Проверить подписку» ещё раз.",
            reply_markup=subs_kb(),
        )
        return

    await call.message.edit_text(
        "🎉 <b>Подписка подтверждена!</b>\n\n"
        f"Твоя ссылка для входа (подай заявку, бот её одобрит):\n{PRIVATE_LINK}\n\n"
        "⚠️ Не пересылай ссылку другим — у каждого должна быть своя проверка."
    )


@dp.chat_join_request()
async def join_request_handler(request: ChatJoinRequest):
    missing = await not_subscribed(request.from_user.id)
    
    if not missing:
        try:
            await bot.approve_chat_join_request(
                chat_id=request.chat.id,
                user_id=request.from_user.id
            )
            await bot.send_message(
                request.from_user.id, 
                "✅ Заявка одобрена! Добро пожаловать в закрытый клуб."
            )
        except Exception as e:
            logging.error(f"Ошибка одобрения: {e}")
    else:
        try:
            await bot.decline_chat_join_request(
                chat_id=request.chat.id,
                user_id=request.from_user.id
            )
            await bot.send_message(
                request.from_user.id, 
                "❌ Не удалось войти. Сначала подпишись на каналы в боте!",
                reply_markup=subs_kb()
            )
        except Exception as e:
            logging.error(f"Ошибка отклонения: {e}")


@dp.chat_member()
async def chat_member_handler(event):
    # Если человек вышел из одного из публичных каналов
    if event.chat.username and f"@{event.chat.username}" in [c["id"] for c in CHANNELS]:
        if event.new_chat_member.status == ChatMemberStatus.LEFT:
            try:
                await bot.ban_chat_member(
                    chat_id=PRIVATE_CHANNEL,
                    user_id=event.new_chat_member.user.id
                )
                await bot.unban_chat_member(
                    chat_id=PRIVATE_CHANNEL,
                    user_id=event.new_chat_member.user.id
                )
                await bot.send_message(
                    event.new_chat_member.user.id,
                    "⚠️ Ты отписался от канала-спонсора, поэтому доступ в закрытый клуб закрыт. Подпишись снова и получи доступ через бота."
                )
            except Exception as e:
                logging.error(f"Ошибка кика: {e}")


@dp.message(Command("menu"))
async def cmd_menu(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await msg.answer("Личный кабинет 👇", reply_markup=kb)


async def health(_request):
    return web.Response(text="ok")

async def start_health():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def on_startup():
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Кабинет",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )

async def main():
    await on_startup()
    if os.getenv("PORT"):
        await start_health()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())