import asyncio
import json
import logging
import os
import re
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
PORT = int(os.getenv("PORT", 10000))
OWNER_IDS = set(map(int, (os.getenv("OWNER_IDS", "") or "").split(",") if os.getenv("OWNER_IDS") else []))
JSONBLOB_URL = os.getenv("JSONBLOB_URL", "")
ADMIN_TAGS_ENV = os.getenv("ADMIN_TAGS", "")
ADMIN_ROLES_ENV = os.getenv("ADMIN_ROLES", "")

PRESET_ADMIN_TAGS = {
    7790900154: "#серафим",
    8275375761: "#лютик",
    8814107258: "#ANGEL",
    5934330035: "#линг",
    5305234519: "#призрак",
    2087257865: "#чапа",
    8920606957: "#лирика",
    6354283893: "#киса",
}
PRESET_ADMIN_ROLES = {
    7790900154: "Влд",
    8275375761: "адм.универсал",
    8814107258: "адм.общение",
    5934330035: "адм.универсал",
    5305234519: "адм.универсал",
    2087257865: "Адм.инженер.сов.влд//общение",
    8920606957: "адм.универсал",
    6354283893: "Сов.влд",
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_topics = {}
blocked_users = set()
admins = set()
owners = set(OWNER_IDS)
all_users = set()
admin_to_user_msg = {}
user_to_admin_msg = {}
user_rates = {}
warns = {}
mutes = {}
admin_tags = {}
admin_roles = {}
read_status = {}

class RateStates(StatesGroup):
    waiting_for_rating = State()
    waiting_for_comment = State()

class ReportStates(StatesGroup):
    waiting_for_text = State()

WELCOME_TEXT = (
    "🌙 Врата распахнулись — и в этот секунд время будто замедлило бег, чтобы осмотреть бережно встретить тебя. 🌙\n\n"
    "🕊 «Что случилось, ангелочек мой?» — этот вопрос здесь не для галочки. Мы спрашиваем, потому что правда хотим услышать твой ответ — будь то тяжелый вздох, сбивчивый рассказ или просто тихое «день был странный».\n\n"
    "💭 Может, ты пришёл, потому что плечи уже не держат весь этот груз, и сейчас хочется, чтобы кто-то просто сказал: «я тут, я слушаю». А может, день был таким светлым, что эмоции переливаются через край — и их нужно кому-то отдать, чтобы они не растаяли в тишине. Или вообще не хочется ни про груз, ни про радость — хочется отвлечься и поболтать о чём-нибудь уютном: про сладости, про аниме, про то, как странно сегодня плывут облака… и это тоже можно здесь.\n\n"
    "💖 Мы искренне рады, что ты выбрал именно этот уголок. Даже если сейчас ты можешь написать только «…», мы прочитаем это как «мне нужно чуть-чуть тишины рядом». И этого будет достаточно.\n\n"
    "📬 Хочешь заглянуть в наш мир, где всегда найдётся что-то тёплое и интересное? Добро пожаловать в телеграм-канал: https://t.me/Yasu737\n\n"
    "💬 А если хочется почувствовать, что ты не один, — посмотри отзывы: там люди делятся своими историями, и каждая из них — про то, как становится чуточку легче: https://t.me/ooih865\n\n"
    "📝 Перед началом разговора, пожалуйста, напиши:\n"
    "• тег своего админа;\n"
    "• цель сообщения: «общение» или «поддержка» (это поможет нам быть рядом именно так, как тебе сейчас нужно).\n\n"
    "Пусть здесь тебе будет спокойно — будто кто-то тихо держит тебя за руку и не торопит ни с ответами, ни с чувствами. 🤍"
)

RULES_TEXT = (
    "⚡️⚡️⚡️⚡️⚡️⚡️⚡️\n"
    "знаешь, я попробую объяснить это мягко.\n"
    "здесь мы создаём место, где можно просто быть собой — без осуждения, без давления, с уважением и теплом.\n\n"
    "✦  𝐀 𝐓 𝐌 𝐎 𝐒 𝐅 𝐄 𝐑 𝐀  ✦\n"
    "1. 𖦹 Мы ценим тепло, дружелюбие и уважение.\n"
    "2. 𖦹 Травля, буллинг и психологическое давление запрещены.\n"
    "3. 𖦹 Мы — за спокойное, уютное и поддерживающее общение.\n\n"
    "✦  𝐏 𝐎 𝐕 𝐄 𝐃 𝐄 𝐍 𝐈 𝐄  ✦\n"
    "4. 𖦹 Запрещены спам, реклама, флуд и посторонние ссылки.\n"
    "5. 𖦹 Контент 18+, угрозы и провокации — ведут к моментальному бану.\n\n"
    "✦  𝐎 𝐁 𝐒 𝐇 𝐄 𝐍 𝐈 𝐄  ✦\n"
    "6. 𖦹 Пиши понятно, уважительно и без излишней грубости.\n"
    "7. 𖦹 Маты допустимы в умеренной форме, но без оскорблений.\n"
    "8. 𖦹 Администрация — это голос порядка. В спорных ситуациях их слово решающее.\n"
    "9. Не выпрашивать ЮЗ, номер админа, это запрещено.\n\n"
    "⚠️ Нарушение этих правил может повлечь за собой предупреждение, мут или бан — без лишних объяснений.\n"
    "Мы создаём пространство, где можно быть собой, не боясь осуждения.\n"
    "Давайте беречь эту атмосферу вместе."
)

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Выбрать админа"), KeyboardButton(text="📂 Выбрать категорию")],
            [KeyboardButton(text="📜 Правила общения")]
        ],
        resize_keyboard=True
    )

def category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мальчик", callback_data="cat_male"),
         InlineKeyboardButton(text="Девочка", callback_data="cat_female")],
        [InlineKeyboardButton(text="Общение", callback_data="cat_comm"),
         InlineKeyboardButton(text="Поддержка", callback_data="cat_support")],
        [InlineKeyboardButton(text="Любой", callback_data="cat_any")]
    ])

def rating_keyboard():
    buttons = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"rate_{i}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Пропустить", callback_data="rate_skip")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_keyboard(user_id: int, read: bool = False):
    if user_id in blocked_users:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock:{user_id}")]])
    if read:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Отменить прочтение", callback_data=f"unread:{user_id}")]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"),
        InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}")
    ]])

def get_confirm_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, разблокировать", callback_data=f"confirm_unblock:{user_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_unblock:{user_id}")
    ]])

def is_owner(user_id: int) -> bool:
    return user_id in owners

def is_admin(user_id: int) -> bool:
    return user_id in admins or is_owner(user_id)

def get_rank(user_id: int) -> str:
    if is_owner(user_id):
        return "👑 Владелец"
    elif is_admin(user_id):
        return "🛡️ Админ"
    else:
        return "👤 Пользователь"

async def load_data():
    global user_topics, blocked_users, admins, owners, all_users, admin_to_user_msg, user_to_admin_msg, user_rates, warns, mutes, admin_tags, admin_roles, read_status
    if JSONBLOB_URL:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(JSONBLOB_URL) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        user_topics = {int(k): v for k, v in data.get("user_topics", {}).items()}
                        blocked_users = set(map(int, data.get("blocked_users", [])))
                        admins = set(map(int, data.get("admins", [])))
                        owners = set(map(int, data.get("owners", [])))
                        all_users = set(map(int, data.get("all_users", [])))
                        admin_to_user_msg = {tuple(map(int, k.split(':'))): v for k, v in data.get("admin_to_user_msg", {}).items()}
                        user_to_admin_msg = {tuple(map(int, k.split(':'))): v for k, v in data.get("user_to_admin_msg", {}).items()}
                        user_rates = data.get("user_rates", {})
                        warns = {int(k): v for k, v in data.get("warns", {}).items()}
                        mutes = {int(k): datetime.fromisoformat(v) for k, v in data.get("mutes", {}).items()}
                        admin_tags = {int(k): v for k, v in data.get("admin_tags", {}).items()}
                        admin_roles = {int(k): v for k, v in data.get("admin_roles", {}).items()}
                        read_status = {int(k): v for k, v in data.get("read_status", {}).items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки из JsonBlob: {e}")

    owners.update(OWNER_IDS)
    if ADMIN_TAGS_ENV:
        for pair in ADMIN_TAGS_ENV.split(","):
            parts = pair.split(":")
            if len(parts) >= 2:
                try:
                    admin_id = int(parts[0])
                    admin_tags[admin_id] = parts[1]
                except ValueError:
                    pass
    if ADMIN_ROLES_ENV:
        for pair in ADMIN_ROLES_ENV.split(","):
            parts = pair.split(":")
            if len(parts) >= 2:
                try:
                    admin_id = int(parts[0])
                    admin_roles[admin_id] = parts[1]
                except ValueError:
                    pass
    admin_tags.update(PRESET_ADMIN_TAGS)
    admin_roles.update(PRESET_ADMIN_ROLES)
    for admin_id in PRESET_ADMIN_TAGS.keys():
        if admin_id not in owners:
            admins.add(admin_id)

async def save_data():
    if not JSONBLOB_URL:
        return
    data = {
        "user_topics": {str(k): v for k, v in user_topics.items()},
        "blocked_users": list(blocked_users),
        "admins": list(admins),
        "owners": list(owners),
        "all_users": list(all_users),
        "admin_to_user_msg": {f"{k[0]}:{k[1]}": v for k, v in admin_to_user_msg.items()},
        "user_to_admin_msg": {f"{k[0]}:{k[1]}": v for k, v in user_to_admin_msg.items()},
        "user_rates": user_rates,
        "warns": {str(k): v for k, v in warns.items()},
        "mutes": {str(k): v.isoformat() for k, v in mutes.items()},
        "admin_tags": {str(k): v for k, v in admin_tags.items()},
        "admin_roles": {str(k): v for k, v in admin_roles.items()},
        "read_status": {str(k): v for k, v in read_status.items()}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(JSONBLOB_URL, json=data) as resp:
                if resp.status not in (200, 204):
                    logging.error(f"Ошибка сохранения: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

def parse_request(text: str):
    text_lower = text.lower()
    type_comm = None
    if 'поддержка' in text_lower or '#поддержка' in text_lower:
        type_comm = 'Поддержка'
    elif 'общение' in text_lower or '#общение' in text_lower:
        type_comm = 'Общение'
    admin_gender = None
    if 'мальчик' in text_lower or '#мальчик' in text_lower:
        admin_gender = 'Мальчик'
    elif 'девочка' in text_lower or '#девочка' in text_lower or 'девушка' in text_lower or '#девушка' in text_lower:
        admin_gender = 'Девочка'
    return type_comm, admin_gender

def is_greeting(text: str) -> bool:
    greetings = ['привет', 'здравствуй', 'здарова', 'дарова', 'ку', 'сап', 'прив', 'хай', 'hello', 'hi', 'пр', 'здорово']
    if text:
        text_lower = text.lower().strip()
        for g in greetings:
            if text_lower == g or text_lower.startswith(g + ' ') or text_lower.startswith(g + '!'):
                return True
    return False

# ---------- КОМАНДЫ ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())

@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help(message: Message):
    help_text = (
        "📋 Команды для админов:\n"
        "/help - эта справка\n"
        "/stats - статистика бота\n"
        "/id - узнать user_id текущей темы\n"
        "/rank - узнать ранг пользователя\n"
        "/close - удалить тему [только владелец]\n"
        "/block - заблокировать пользователя\n"
        "/unblock - разблокировать пользователя\n"
        "/warn - выдать предупреждение\n"
        "/mute <число> <минут|часов|дней> <причина> - замутить\n"
        "/unmute или /размут - размутить\n"
        "/warns - посмотреть предупреждения\n"
        "/myrank - свой ранг\n\n"
        "Команды владельца:\n"
        "/setrank <user_id> <admin|owner> - назначить ранг\n"
        "/settag <user_id> <тег> - установить тег админа\n"
        "/setrole <user_id> <роль> - установить роль админа\n"
        "/removerank <user_id> - снять ранг\n"
        "/liststaff - показать всех владельцев и админов\n"
        "/clear - сбросить все данные (осторожно!)\n"
        "/broadcast <текст> - разослать сообщение всем пользователям\n\n"
        "Сообщения без // пересылаются пользователю.\n"
        "Сообщения с // остаются в теме как заметки."
    )
    await message.answer(help_text)

@dp.message(Command("myrank"))
async def cmd_myrank(message: Message):
    await message.answer(f"Ваш ранг: {get_rank(message.from_user.id)}")

@dp.message(Command("stats"), F.chat.id == GROUP_ID)
async def cmd_stats(message: Message):
    await message.answer(
        f"📊 Статистика бота:\n"
        f"👥 Всего пользователей: {len(all_users)}\n"
        f"💬 Активных диалогов: {len(user_topics)}\n"
        f"🔒 Заблокировано: {len(blocked_users)}"
    )

@dp.message(Command("id"), F.chat.id == GROUP_ID)
async def cmd_id(message: Message):
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    await message.answer(f"ID пользователя: {user_id}" if user_id else "Не удалось определить пользователя.")

@dp.message(Command("close"), F.chat.id == GROUP_ID)
async def cmd_close(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if user_id:
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
            user_topics.pop(user_id, None)
            admin_to_user_msg = {k: v for k, v in admin_to_user_msg.items() if k[0] != topic_id}
            user_to_admin_msg = {k: v for k, v in user_to_admin_msg.items() if k[0] != user_id}
            read_status.pop(user_id, None)
            await save_data()
            await message.answer("Тема удалена.")
            await bot.send_message(user_id, "Пожалуйста, оцените работу администратора от 1 до 10:", reply_markup=rating_keyboard())
        except Exception as e:
            logging.error(f"Ошибка удаления темы: {e}")
            await message.answer("Не удалось удалить тему.")
    else:
        await message.answer("Эта тема не связана с пользователем.")

@dp.message(Command("clear"), F.chat.id == GROUP_ID)
async def cmd_clear(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    user_topics.clear()
    blocked_users.clear()
    all_users.clear()
    admin_to_user_msg.clear()
    user_to_admin_msg.clear()
    user_rates.clear()
    warns.clear()
    mutes.clear()
    admin_tags.clear()
    admin_roles.clear()
    read_status.clear()
    admin_tags.update(PRESET_ADMIN_TAGS)
    admin_roles.update(PRESET_ADMIN_ROLES)
    admins.clear()
    for admin_id in PRESET_ADMIN_TAGS.keys():
        if admin_id not in owners:
            admins.add(admin_id)
    await save_data()
    await message.answer("Все данные сброшены.")

@dp.message(Command("broadcast"), F.chat.id == GROUP_ID)
async def cmd_broadcast(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        await message.answer("Формат: /broadcast <текст>")
        return
    sent, failed = 0, 0
    for user_id in list(all_users):
        try:
            await bot.send_message(user_id, text[1])
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await message.answer(f"✅ Рассылка завершена.\nОтправлено: {sent}\nНе удалось: {failed}")

@dp.message(Command("setrank"), F.chat.id == GROUP_ID)
async def cmd_setrank(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Формат: /setrank <user_id> <admin|owner>")
        return
    try:
        target_id = int(args[1])
        rank = args[2].lower()
    except:
        await message.answer("Неверный user_id.")
        return
    if rank == "admin":
        admins.add(target_id)
        await save_data()
        await message.answer(f"Пользователь {target_id} назначен админом.")
    elif rank == "owner":
        owners.add(target_id)
        await save_data()
        await message.answer(f"Пользователь {target_id} назначен владельцем.")
    else:
        await message.answer("Ранг может быть только admin или owner.")

@dp.message(Command("settag"), F.chat.id == GROUP_ID)
async def cmd_settag(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) != 3:
        await message.answer("Формат: /settag <user_id> <тег>")
        return
    try:
        target_id = int(args[1])
        tag = args[2]
    except:
        await message.answer("Неверный user_id.")
        return
    admin_tags[target_id] = tag
    await save_data()
    await message.answer(f"Тег '{tag}' установлен.")

@dp.message(Command("setrole"), F.chat.id == GROUP_ID)
async def cmd_setrole(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) != 3:
        await message.answer("Формат: /setrole <user_id> <роль>")
        return
    try:
        target_id = int(args[1])
        role = args[2]
    except:
        await message.answer("Неверный user_id.")
        return
    admin_roles[target_id] = role
    await save_data()
    await message.answer(f"Роль '{role}' установлена.")

@dp.message(Command("removerank"), F.chat.id == GROUP_ID)
async def cmd_removerank(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Формат: /removerank <user_id>")
        return
    try:
        target_id = int(args[1])
    except:
        await message.answer("Неверный user_id.")
        return
    admins.discard(target_id)
    owners.discard(target_id)
    await save_data()
    await message.answer(f"Ранг пользователя {target_id} снят.")

@dp.message(Command("liststaff"), F.chat.id == GROUP_ID)
async def cmd_liststaff(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    owners_list = ", ".join(map(str, owners)) if owners else "нет"
    admins_list = ", ".join(map(str, admins)) if admins else "нет"
    await message.answer(f"👑 Владельцы: {owners_list}\n🛡️ Админы: {admins_list}")

@dp.message(Command("warn"), F.chat.id == GROUP_ID)
async def cmd_warn(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if not user_id:
        await message.answer("Не удалось определить пользователя.")
        return
    warns[user_id] = warns.get(user_id, 0) + 1
    await save_data()
    if warns[user_id] >= 3:
        blocked_users.add(user_id)
        await save_data()
        await bot.send_message(user_id, "Вы получили 3 предупреждения и были заблокированы.")
        await message.answer(f"⚠️ Пользователь {user_id} заблокирован (3 варна).")
    else:
        await message.answer(f"⚠️ Предупреждение выдано. Всего: {warns[user_id]}")

@dp.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute_ru(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.answer("Формат: /mute <число> <минут|часов|дней> <причина>\nПример: /mute 5 минут спам")
        return
    try:
        value = int(args[1])
    except ValueError:
        await message.answer("Неверное число.")
        return
    unit = "минут"
    reason = ""
    if len(args) >= 3:
        if args[2].startswith(("час", "часов", "час.", "ч")):
            unit = "часов"
            value *= 60
        elif args[2].startswith(("день", "дней", "д.", "дн")):
            unit = "дней"
            value *= 1440
        else:
            reason = args[2]
    if len(args) >= 4:
        reason = args[3] if not reason else reason + " " + args[3]

    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if not user_id:
        await message.answer("Не удалось определить пользователя.")
        return
    until = datetime.now() + timedelta(minutes=value)
    mutes[user_id] = until
    await save_data()
    reason_text = f"\nПричина: {reason}" if reason else ""
    await message.answer(f"🔇 Пользователь замучен до {until.strftime('%H:%M')}{reason_text}")

@dp.message(F.chat.id == GROUP_ID, F.text.lower().in_(["/unmute", "/размут"]))
async def cmd_unmute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if not user_id:
        await message.answer("Не удалось определить пользователя.")
        return
    if user_id in mutes:
        del mutes[user_id]
        await save_data()
        await message.answer("🔊 Пользователь размучен.")
    else:
        await message.answer("Пользователь не в муте.")

@dp.message(Command("warns"), F.chat.id == GROUP_ID)
async def cmd_warns(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if not user_id:
        await message.answer("Не удалось определить пользователя.")
        return
    await message.answer(f"Предупреждений: {warns.get(user_id, 0)}")

@dp.message(Command("rank"))
async def cmd_rank(message: Message):
    user_id_to_check = None
    if message.chat.type in ["group", "supergroup"] and message.message_thread_id:
        topic_id = message.message_thread_id
        for uid, tid in user_topics.items():
            if tid == topic_id:
                user_id_to_check = uid
                break
    args = message.text.split()
    if len(args) == 2:
        try:
            user_id_to_check = int(args[1])
        except:
            pass
    if user_id_to_check is None and message.chat.type == "private":
        user_id_to_check = message.from_user.id
    if user_id_to_check is None:
        await message.answer("Не удалось определить пользователя. Используй /rank <user_id>")
        return
    rank = get_rank(user_id_to_check)
    await message.answer(f"Ранг пользователя {user_id_to_check}: {rank}")

@dp.message(Command("report"))
async def cmd_report_simple(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, опишите вашу жалобу или проблему. Она будет отправлена владельцам бота.")
    await state.set_state(ReportStates.waiting_for_text)

@dp.message(ReportStates.waiting_for_text)
async def process_report_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    report_text = f"🚨 Репорт от пользователя {user_id}:\n{message.text}"
    for o in owners:
        try:
            await bot.send_message(o, report_text)
        except:
            pass
    await message.answer("Спасибо, жалоба отправлена.")
    await state.clear()

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in user_topics:
        topic_id = user_topics.pop(user_id)
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except:
            pass
        read_status.pop(user_id, None)
        await save_data()
    await message.answer("Диалог завершён. Если захотите снова пообщаться, напишите /start.")

# ---------- Личные сообщения ----------
@dp.message(F.chat.type == "private")
async def handle_user_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text and message.text.startswith('/'):
        return

    all_users.add(user_id)
    await save_data()

    if user_id in mutes and datetime.now() < mutes[user_id]:
        await message.answer(f"🔇 Вы в муте до {mutes[user_id].strftime('%H:%M')}.")
        return
    elif user_id in mutes:
        del mutes[user_id]
        await save_data()

    if user_id in blocked_users:
        await message.answer("Вы заблокированы и не можете отправлять сообщения.")
        return

    if message.text == "👤 Выбрать админа":
        await show_admin_buttons(message)
        return
    elif message.text == "📂 Выбрать категорию":
        await message.answer("Выберите категорию:", reply_markup=category_keyboard())
        return
    elif message.text == "📜 Правила общения":
        await message.answer(RULES_TEXT)
        return

    if user_id not in user_topics:
        text = message.text or ""
        if is_greeting(text):
            await message.answer("Привет! Чтобы начать, выбери один из вариантов:", reply_markup=main_menu_keyboard())
            return

        type_comm, admin_gender = parse_request(text)
        if type_comm and admin_gender:
            username = message.from_user.username or f"id{user_id}"
            try:
                topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=f"{username}")
                topic_id = topic.message_thread_id
                user_topics[user_id] = topic_id
                read_status[user_id] = False
                await save_data()

                info = (
                    f"🆕 Новый запрос!\n"
                    f"👤 Имя: {message.from_user.full_name}\n"
                    f"🔖 Username: @{message.from_user.username or 'нет'}\n"
                    f"📌 Тип: {type_comm}\n"
                    f"🚻 Предпочтительный пол админа: {admin_gender}\n\n"
                    f"Начинайте общение. Сообщения без // будут отправлены пользователю."
                )
                await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
                await message.answer("Готово! Твой запрос принят. Администратор скоро свяжется с тобой.")
            except Exception as e:
                logging.error(f"Не удалось создать тему: {e}")
                await message.answer("Произошла ошибка. Попробуй позже.")
        else:
            await message.answer("Пожалуйста, укажи категорию и пол админа, например: «привет поддержка мальчик».\nИли используй кнопки /start.")
        return

    topic_id = user_topics[user_id]

    async def send_media_to_topic(target_topic_id):
        if message.voice:
            await bot.send_voice(GROUP_ID, message.voice.file_id, message_thread_id=target_topic_id)
        elif message.video_note:
            await bot.send_video_note(GROUP_ID, message.video_note.file_id, message_thread_id=target_topic_id)
        elif message.video:
            await bot.send_video(GROUP_ID, message.video.file_id, message_thread_id=target_topic_id)
        elif message.photo:
            await bot.send_photo(GROUP_ID, message.photo[-1].file_id, message_thread_id=target_topic_id)
        elif message.document:
            await bot.send_document(GROUP_ID, message.document.file_id, message_thread_id=target_topic_id)
        elif message.sticker:
            await bot.send_sticker(GROUP_ID, message.sticker.file_id, message_thread_id=target_topic_id)
        elif message.text:
            sent = await bot.send_message(GROUP_ID, message.text, message_thread_id=target_topic_id)
            return sent
        else:
            await bot.copy_message(GROUP_ID, message.chat.id, message.message_id, message_thread_id=target_topic_id)
        return None

    try:
        sent_msg = await send_media_to_topic(topic_id)
        if sent_msg and message.text:
            user_to_admin_msg[(user_id, message.message_id)] = sent_msg.message_id
            await save_data()
    except Exception as e:
        error_text = str(e).lower()
        if "message thread not found" in error_text or "topic closed" in error_text or "chat not found" in error_text:
            username = message.from_user.username or f"id{user_id}"
            try:
                topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=f"{username}")
                new_topic_id = topic.message_thread_id
                user_topics[user_id] = new_topic_id
                await save_data()
                info = f"🔄 Восстановление темы после удаления.\n👤 Имя: {message.from_user.full_name}\n🔖 Username: @{message.from_user.username or 'нет'}\n"
                await bot.send_message(GROUP_ID, info, message_thread_id=new_topic_id, reply_markup=get_keyboard(user_id, read=False))
                await send_media_to_topic(new_topic_id)
                await message.answer("Тема была пересоздана, администраторы получили твоё сообщение.")
            except Exception as e2:
                logging.error(f"Не удалось создать новую тему: {e2}")
                await message.answer("Произошла ошибка. Попробуй ещё раз.")
        else:
            logging.error(f"Ошибка отправки в тему: {e}")
            await message.answer("Не удалось отправить сообщение. Попробуй позже.")

async def show_admin_buttons(message: Message):
    if not admins and not owners:
        await message.answer("Нет доступных админов.")
        return
    buttons = []
    for a in admins:
        tag = admin_tags.get(a, "")
        role = admin_roles.get(a, "")
        name = f"{tag} — {role}" if tag and role else (tag or role or f"ID {a}")
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"admin_{a}")])
    for o in owners:
        tag = admin_tags.get(o, "")
        role = admin_roles.get(o, "")
        name = f"{tag} — {role}" if tag and role else (tag or role or f"ID {o}")
        buttons.append([InlineKeyboardButton(text=name + " 👑", callback_data=f"admin_{o}")])
    await message.answer("Выберите администратора:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "choose_admin")
async def process_choose_admin_callback(callback: CallbackQuery):
    await callback.message.delete()
    await show_admin_buttons(callback.message)

@dp.callback_query(F.data.startswith("admin_"))
async def process_admin_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"
    topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=f"{username}")
    topic_id = topic.message_thread_id
    user_topics[user_id] = topic_id
    read_status[user_id] = False
    await save_data()

    admin_tag = admin_tags.get(admin_id, "")
    admin_role = admin_roles.get(admin_id, "")
    extra = "\n".join(filter(None, [
        f"🏷 Тег: {admin_tag}" if admin_tag else "",
        f"👔 Роль: {admin_role}" if admin_role else ""
    ]))

    info = (
        f"🆕 Новый запрос!\n"
        f"👤 Имя: {callback.from_user.full_name}\n"
        f"🔖 Username: @{callback.from_user.username or 'нет'}\n"
        f"📌 Тип: выбран админ (ID {admin_id})\n"
        f"{extra}\n\n"
        f"Начинайте общение. Сообщения без // будут отправлены пользователю."
    )
    await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
    await bot.send_message(admin_id, f"Новый пользователь хочет общаться с вами. Тема: {topic_id}")
    await bot.send_message(user_id, "Готово! Администратор уведомлён.")
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data == "choose_category")
async def process_choose_category(callback: CallbackQuery):
    await callback.message.edit_text("Выберите категорию:", reply_markup=category_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_selected(callback: CallbackQuery):
    cat = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"

    type_comm = None
    admin_gender = None
    if cat == "male":
        admin_gender = "Мальчик"
    elif cat == "female":
        admin_gender = "Девочка"
    elif cat == "comm":
        type_comm = "Общение"
    elif cat == "support":
        type_comm = "Поддержка"
    elif cat == "any":
        type_comm = "Общение"
        admin_gender = "Любой"

    topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=f"{username}")
    topic_id = topic.message_thread_id
    user_topics[user_id] = topic_id
    read_status[user_id] = False
    await save_data()

    info = (
        f"🆕 Новый запрос!\n"
        f"👤 Имя: {callback.from_user.full_name}\n"
        f"🔖 Username: @{callback.from_user.username or 'нет'}\n"
        f"📌 Тип: {type_comm or 'Не указан'}\n"
        f"🚻 Предпочтительный пол админа: {admin_gender or 'Не указан'}\n\n"
        f"Начинайте общение. Сообщения без // будут отправлены пользователю."
    )
    await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
    await bot.send_message(user_id, "Готово! Твой запрос принят. Администратор скоро свяжется с тобой.")
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data == "show_rules")
async def process_show_rules(callback: CallbackQuery):
    await callback.message.edit_text(RULES_TEXT)
    await callback.answer()

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery, state: FSMContext):
    if callback.data == "rate_skip":
        await callback.message.edit_text("Спасибо за обратную связь!")
        await callback.answer()
        return
    rating = int(callback.data.split("_")[1])
    await state.update_data(rating=rating)
    await callback.message.edit_text("Пожалуйста, оставьте комментарий (или отправьте /skip):")
    await state.set_state(RateStates.waiting_for_comment)
    await callback.answer()

@dp.message(RateStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
    user_id = message.from_user.id
    rating = (await state.get_data()).get("rating")
    comment = "" if message.text == "/skip" else message.text
    user_rates[user_id] = {"rating": rating, "comment": comment}
    await save_data()
    await message.answer("Спасибо за оценку!")
    await state.clear()

@dp.message(F.chat.id == GROUP_ID, F.message_thread_id.is_not(None))
async def handle_admin_message(message: Message):
    if message.from_user.is_bot or message.is_topic_message is False:
        return
    if message.text and message.text.startswith('/'):
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if user_id is None:
        return

    if message.text and message.text.startswith("//"):
        return

    try:
        if message.text:
            user_msg = await bot.send_message(user_id, message.text)
            admin_to_user_msg[(topic_id, message.message_id)] = user_msg.message_id
            await save_data()
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
        elif message.video_note:
            await bot.send_video_note(user_id, message.video_note.file_id)
        elif message.video:
            await bot.send_video(user_id, message.video.file_id)
        elif message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id)
        elif message.document:
            await bot.send_document(user_id, message.document.file_id)
        elif message.sticker:
            await bot.send_sticker(user_id, message.sticker.file_id)
        else:
            await bot.copy_message(user_id, message.chat.id, message.message_id)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

@dp.edited_message(F.chat.id == GROUP_ID, F.message_thread_id.is_not(None))
async def handle_admin_edited_message(message: Message):
    if message.from_user.is_bot:
        return
    topic_id = message.message_thread_id
    user_id = next((uid for uid, tid in user_topics.items() if tid == topic_id), None)
    if user_id is None:
        return
    key = (topic_id, message.message_id)
    user_message_id = admin_to_user_msg.get(key)
    if not user_message_id:
        return
    new_text = message.text or ""
    if new_text.startswith("//"):
        return
    try:
        await bot.edit_message_text(chat_id=user_id, message_id=user_message_id, text=new_text)
    except Exception as e:
        logging.error(f"Не удалось отредактировать сообщение у пользователя: {e}")

@dp.edited_message(F.chat.type == "private")
async def handle_user_edited_message(message: Message):
    user_id = message.from_user.id
    topic_id = user_topics.get(user_id)
    if not topic_id:
        return
    key = (user_id, message.message_id)
    admin_message_id = user_to_admin_msg.get(key)
    if not admin_message_id:
        return
    new_text = message.text or ""
    try:
        await bot.edit_message_text(chat_id=GROUP_ID, message_id=admin_message_id, text=new_text)
    except Exception as e:
        logging.error(f"Не удалось отредактировать сообщение в теме: {e}")

@dp.callback_query(F.data.startswith("block:"))
async def process_block_button(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    if user_id not in blocked_users:
        blocked_users.add(user_id)
        read_status[user_id] = False
        await save_data()
        try:
            await bot.send_message(user_id, "Вы были заблокированы.")
        except:
            pass
        await callback.message.edit_text(callback.message.text + "\n\n🔒 Заблокирован", reply_markup=get_keyboard(user_id, read=False))
        await callback.answer("Пользователь заблокирован")
    else:
        await callback.answer("Пользователь уже заблокирован")

@dp.callback_query(F.data.startswith("unblock:"))
async def process_unblock_button(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(callback.message.text + "\n\n❓ Вы точно хотите разблокировать?", reply_markup=get_confirm_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_unblock:"))
async def process_confirm_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    if user_id in blocked_users:
        blocked_users.discard(user_id)
        read_status[user_id] = False
        await save_data()
        try:
            await bot.send_message(user_id, "Вы были разблокированы.")
        except:
            pass
        lines = callback.message.text.split('\n')
        while lines and lines[-1].startswith(('🔒', '❓')):
            lines.pop()
        clean_text = '\n'.join(lines)
        await callback.message.edit_text(clean_text, reply_markup=get_keyboard(user_id, read=False))
        await callback.answer("Пользователь разблокирован")
    else:
        await callback.answer("Пользователь не заблокирован")

@dp.callback_query(F.data.startswith("cancel_unblock:"))
async def process_cancel_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    lines = callback.message.text.split('\n')
    if lines and lines[-1].startswith('❓'):
        lines.pop()
    clean_text = '\n'.join(lines)
    await callback.message.edit_text(clean_text, reply_markup=get_keyboard(user_id, read=False))
    await callback.answer()

@dp.callback_query(F.data.startswith("read:"))
async def process_read_button(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    try:
        await bot.send_message(user_id, "Ваш запрос прочитан, скоро с вами свяжутся.")
    except:
        pass
    read_status[user_id] = True
    await save_data()
    await callback.answer("Запрос отмечен как прочитанный")
    try:
        lines = callback.message.text.split('\n')
        while lines and lines[-1].startswith(('✅', '↩️')):
            lines.pop()
        clean_text = '\n'.join(lines) + "\n\n✅ Прочитано"
        await callback.message.edit_text(clean_text, reply_markup=get_keyboard(user_id, read=True))
    except:
        pass

@dp.callback_query(F.data.startswith("unread:"))
async def process_unread_button(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    read_status[user_id] = False
    await save_data()
    await callback.answer("Прочтение отменено")
    try:
        lines = callback.message.text.split('\n')
        while lines and lines[-1].startswith(('✅', '↩️')):
            lines.pop()
        clean_text = '\n'.join(lines)
        await callback.message.edit_text(clean_text, reply_markup=get_keyboard(user_id, read=False))
    except:
        pass

async def main():
    logging.basicConfig(level=logging.INFO)
    await load_data()
    await bot.delete_webhook(drop_pending_updates=True)

    polling_task = asyncio.create_task(dp.start_polling(bot))

    app = web.Application()
    app.router.add_get('/', lambda request: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Web server started on port {PORT}")

    await polling_task

if __name__ == "__main__":
    asyncio.run(main())
