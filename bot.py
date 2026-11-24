import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonWebApp, Message, WebAppInfo,
)
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN         = os.getenv("BOT_TOKEN")
PRIVATE_CHANNEL   = int(os.getenv("PRIVATE_CHANNEL_ID", "-1000000000000"))
PRIVATE_LINK      = os.getenv("PRIVATE_LINK", "https://t.me/+fallback")
WEBAPP_URL        = os.getenv("WEBAPP_URL", "https://example.com")
PORT              = int(os.getenv("PORT", 8080))

CHANNELS = [
    {"@-1005749665886": "@channel_one", "name": "Канал 1", "-1005749665886": "https://t.me/channel_one"},
    {"@-1005657673722": "@channel_two", "name": "Канал 2", "-1005657673722": "https://t.me/channel_two"},
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
        "3. Получи личную одноразовую ссылку в закрытый канал\n\n"
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

    invite = PRIVATE_LINK
    try:
        link = await bot.create_chat_invite_link(
            chat_id=PRIVATE_CHANNEL,
            member_limit=1,
            name=f"user_{call.from_user.id}",
        )
        invite = link.invite_link
    except Exception as e:
        logging.exception("invite link: %s", e)

    await call.message.edit_text(
        "🎉 <b>Доступ открыт!</b>\n\n"
        f"Твоя персональная ссылка (одноразовая):\n{invite}\n\n"
        "⚠️ Ссылка работает только для одного входа — не передавай её."
    )

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