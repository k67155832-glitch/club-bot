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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN         = os.getenv("BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
PRIVATE_CHANNEL   = int(os.getenv("PRIVATE_CHANNEL_ID", "-1000000000000"))
PRIVATE_LINK      = os.getenv("PRIVATE_LINK", "https://t.me/+fallback")
WEBAPP_URL        = os.getenv("WEBAPP_URL", "https://example.com")
PORT              = int(os.getenv("PORT", 8080))

CHANNELS = [
    {"id": "@anonscluba", "name": "Анонсы", "url": "https://t.me/anonscluba"},
    {"id": "@novostycluba", "name": "Новости Клуба", "url": "https://t.me/novostycluba"},
]

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher()

# Простая база в памяти (для рассылки)
users_db = set()

# Состояние для рассылки
class AdminStates(StatesGroup):
    waiting_for_broadcast = State()


def subs_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['name']}", url=c["url"])] for c in CHANNELS]
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔗 Проверить каналы", callback_data="admin_check_channels")],
    ])


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
    users_db.add(msg.from_user.id) # Сохраняем юзера
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
    users_db.add(call.from_user.id) # Сохраняем юзера
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
            await bot.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
            await bot.send_message(request.from_user.id, "✅ Заявка одобрена! Добро пожаловать в закрытый клуб.")
        except Exception as e:
            logging.error(f"Ошибка одобрения: {e}")
    else:
        try:
            await bot.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
            await bot.send_message(request.from_user.id, "❌ Не удалось войти. Сначала подпишись на каналы в боте!", reply_markup=subs_kb())
        except Exception as e:
            logging.error(f"Ошибка отклонения: {e}")


@dp.chat_member()
async def chat_member_handler(event):
    if event.chat.username and f"@{event.chat.username}" in [c["id"] for c in CHANNELS]:
        if event.new_chat_member.status == ChatMemberStatus.LEFT:
            try:
                await bot.ban_chat_member(chat_id=PRIVATE_CHANNEL, user_id=event.new_chat_member.user.id)
                await bot.unban_chat_member(chat_id=PRIVATE_CHANNEL, user_id=event.new_chat_member.user.id)
                await bot.send_message(event.new_chat_member.user.id, "⚠️ Ты отписался от канала-спонсора, поэтому доступ в закрытый клуб закрыт.")
            except Exception as e:
                logging.error(f"Ошибка кика: {e}")


@dp.message(Command("menu"))
async def cmd_menu(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await msg.answer("Личный кабинет 👇", reply_markup=kb)


# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("⛔ У вас нет доступа к этой команде.")
        return
    await msg.answer("👑 <b>Админ-панель</b>\n\nВыбери действие:", reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей в боте: <b>{len(users_db)}</b>\n"
        f"📢 Каналов-спонсоров: <b>{len(CHANNELS)}</b>\n"
        f"🔒 Закрытый канал: <b>{PRIVATE_CHANNEL}</b>",
        reply_markup=admin_kb()
    )


@dp.callback_query(F.data == "admin_check_channels")
async def admin_check_channels(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await call.answer("Проверяю…")
    result_text = "🔗 <b>Статус каналов:</b>\n\n"
    for ch in CHANNELS:
        try:
            chat = await bot.get_chat(ch["id"])
            result_text += f"✅ {ch['name']} (@{chat.username}) — ОК\n"
        except Exception:
            result_text += f"❌ {ch['name']} — ОШИБКА (бота нет в админах?)\n"
            
    result_text += f"\nПриватный канал (ID: {PRIVATE_CHANNEL}):\n"
    try:
        await bot.get_chat(PRIVATE_CHANNEL)
        result_text += "✅ Доступ есть\n"
    except Exception:
        result_text += "❌ Ошибка (проверь ID или права бота)\n"
        
    await call.message.edit_text(result_text, reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("📢 Отправь мне текст или фото для рассылки. Для отмены напиши /cancel")
    await state.set_state(AdminStates.waiting_for_broadcast)


@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    await msg.answer("⏳ Начинаю рассылку...")
    
    success = 0
    fail = 0
    for user_id in users_db:
        try:
            await msg.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05) # Задержка, чтобы не забанили за спам
        except Exception:
            fail += 1
            
    await msg.answer(f"✅ Рассылка завершена!\nДоставлено: {success}\nОшибок: {fail}", reply_markup=admin_kb())


@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    await msg.answer("Действие отменено.", reply_markup=admin_kb())


# --- ЗАПУСК ---

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
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Кабинет", web_app=WebAppInfo(url=WEBAPP_URL)))

async def main():
    await on_startup()
    if os.getenv("PORT"):
        await start_health()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())