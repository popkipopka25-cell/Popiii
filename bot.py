import asyncio
import json
import logging
import os
import aiohttp
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web


BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", "0").split()[0])
PORT = int(os.getenv("PORT", 10000))

_raw_owners = os.getenv("OWNER_IDS", "") or ""
OWNER_IDS = set()
for _x in _raw_owners.split(","):
    _x = _x.strip()
    if _x.isdigit():
        OWNER_IDS.add(int(_x))

JSONBLOB_URL = os.getenv("JSONBLOB_URL", "")
ADMIN_TAGS_ENV = os.getenv("ADMIN_TAGS", "")
ADMIN_ROLES_ENV = os.getenv("ADMIN_ROLES", "")


PRESET_ADMIN_TAGS = {
    7790900154: "#Серафим",
    6354283893: "#Киса",
    2087257865: "#чапа",
    8275375761: "#лютик",
    8790245480: "#падшая",
    6870680424: "#цена",
    5812572110: "#темная",
    6698192304: "#минерва",
    6599739238: "#мадока",
}

PRESET_ADMIN_ROLES = {
    7790900154: "Влд",
    6354283893: "Сов.влд",
    2087257865: "Зам.Сов.Влд//адм.инженер//общение",
    8275375761: "адм.универсал",
    8790245480: "адм.общения",
    6870680424: "адм.общения",
    5812572110: "адм.универсал",
    6698192304: "адм.универсал",
    6599739238: "адм.универсал",
}

ADMIN_GREETINGS = {
    7790900154: "Привет, солнце! Я Серафим, готова помочь. Расскажи, что случилось 🤍",
    6354283893: "Привет! Я Киса, слушаю тебя. Что тревожит?",
    2087257865: "Привет! На связи Чапа. Чем помочь?",
    8275375761: "Приветик! Я Лютик. Давай поболтаем 🌸",
    8790245480: "Привет! Я Падшая, готова выслушать.",
    6870680424: "Привет. Я Цена. Что у тебя случилось?",
    5812572110: "Привет… Я Тёмная. Можешь рассказать всё, что на душе.",
    6698192304: "Привет! Минерва на связи. Расскажи, что тебя беспокоит.",
    6599739238: "Привет! Я Мадока. Готова помочь, пиши.",
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

reminders = {}       # topic_id -> {"admin_id": int|None, "answered": bool, "task": Task}
frozen_topics = {}   # topic_id -> True
topic_history = {}   # topic_id -> [message_id]


class RateStates(StatesGroup):
    waiting_for_comment = State()


class ReportStates(StatesGroup):
    waiting_for_text = State()


class ChangeStates(StatesGroup):
    confirm = State()


WELCOME_TEXT = (
    "🌙 Врата распахнулись — и в этот секунд время будто замедлило бег, чтобы осмотреть бережно встретить тебя. 🌙\n\n"
    "🕊 «Что случилось, ангелочек мой?» — этот вопрос здесь не для галочки. Мы спрашиваем, потому что правда хотим услышать твой ответ — будь то тяжелый вздох, сбивчивый рассказ или просто тихое «день был странный».\n\n"
    "💭 Может, ты пришёл, потому что плечи уже не держат весь этот груз, и сейчас хочется, чтобы кто-то просто сказал: «я тут, я слушаю». А может, день был таким светлым, что эмоции переливаются через край — и их нужно кому-то отдать, чтобы они не растаяли в тишине.\n\n"
    "💖 Мы искренне рады, что ты выбрал именно этот уголок.\n\n"
    "📬 Канал: https://t.me/Yasu737\n"
    "💬 Отзывы: https://t.me/ooih865\n\n"
    "📝 Напиши тег админа и цель: «общение» или «поддержка»."
)

RULES_TEXT = (
    "⚡️⚡️⚡️⚡️⚡️⚡️⚡️\n"
    "Правила общения:\n"
    "1. Будь вежлив.\n"
    "2. Не спамь.\n"
    "3. Уважай других.\n"
    "4. Не выпрашивай юз.\n"
    "5. При конфликте пиши админу."
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Выбрать админа"), KeyboardButton(text="📂 Выбрать категорию")],
            [KeyboardButton(text="📜 Правила общения")],
        ],
        resize_keyboard=True,
    )


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мальчик · Общение", callback_data="cat_male_comm"),
                InlineKeyboardButton(text="Мальчик · Поддержка", callback_data="cat_male_support"),
            ],
            [
                InlineKeyboardButton(text="Девочка · Общение", callback_data="cat_female_comm"),
                InlineKeyboardButton(text="Девочка · Поддержка", callback_data="cat_female_support"),
            ],
            [
                InlineKeyboardButton(text="Любой · Общение", callback_data="cat_any_comm"),
                InlineKeyboardButton(text="Любой · Поддержка", callback_data="cat_any_support"),
            ],
        ]
    )


def rating_keyboard() -> InlineKeyboardMarkup:
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


def get_keyboard(user_id: int, read: bool = False) -> InlineKeyboardMarkup:
    if user_id in blocked_users:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock:{user_id}")]
            ]
        )
    if read:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Отменить прочтение", callback_data=f"unread:{user_id}")]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"),
                InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}"),
            ]
        ]
    )


def get_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, разблокировать", callback_data=f"confirm_unblock:{user_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_unblock:{user_id}"),
            ]
        ]
    )


def is_owner(user_id: int) -> bool:
    return user_id in owners


def is_admin(user_id: int) -> bool:
    return user_id in admins or is_owner(user_id)


def get_rank(user_id: int) -> str:
    if is_owner(user_id):
        return "👑 Владелец"
    if is_admin(user_id):
        return "🛡️ Админ"
    return "👤 Пользователь"


def find_user_by_topic(topic_id: int):
    for uid, tid in user_topics.items():
        if tid == topic_id:
            return uid
    return None


def parse_request(text: str):
    low = text.lower()
    type_comm = None
    if "поддержка" in low or "#поддержка" in low:
        type_comm = "Поддержка"
    elif "общение" in low or "#общение" in low:
        type_comm = "Общение"

    admin_gender = None
    if "мальчик" in low or "#мальчик" in low:
        admin_gender = "Мальчик"
    elif "девочка" in low or "#девочка" in low or "девушка" in low:
        admin_gender = "Девочка"
    return type_comm, admin_gender


def is_greeting(text: str) -> bool:
    greetings = ["привет", "здравствуй", "здарова", "дарова", "ку", "сап", "прив", "хай", "hello", "hi", "пр", "здорово"]
    if not text:
        return False
    t = text.lower().strip()
    for g in greetings:
        if t == g or t.startswith(g + " ") or t.startswith(g + "!"):
            return True
    return False


# ================== Напоминание ==================

async def reminder_loop(topic_id: int):
    try:
        while True:
            await asyncio.sleep(1800)
            data = reminders.get(topic_id)
            if not data or data.get("answered"):
                return
            admin_id = data.get("admin_id")
            if not admin_id:
                return
            tag = admin_tags.get(admin_id, "")
            mention = tag if tag else f"админ {admin_id}"
            try:
                sent = await bot.send_message(
                    GROUP_ID,
                    f"🔔 {mention}, у тебя новый пользователь в этой теме. Ответь, пожалуйста.",
                    message_thread_id=topic_id,
                )
                topic_history.setdefault(topic_id, []).append(sent.message_id)
            except Exception as e:
                logging.error(f"Напоминание не отправлено: {e}")
                return
    except asyncio.CancelledError:
        return


def start_reminder(topic_id: int, admin_id):
    task = asyncio.create_task(reminder_loop(topic_id))
    reminders[topic_id] = {"admin_id": admin_id, "answered": False, "task": task}


def stop_reminder(topic_id: int):
    data = reminders.pop(topic_id, None)
    if data:
        task = data.get("task")
        if task:
            task.cancel()


# ================== Данные ==================

async def load_data():
    global user_topics, blocked_users, admins, owners, all_users
    global admin_to_user_msg, user_to_admin_msg, user_rates
    global warns, mutes, admin_tags, admin_roles, read_status

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
                        admin_to_user_msg = {tuple(map(int, k.split(":"))): v for k, v in data.get("admin_to_user_msg", {}).items()}
                        user_to_admin_msg = {tuple(map(int, k.split(":"))): v for k, v in data.get("user_to_admin_msg", {}).items()}
                        user_rates = data.get("user_rates", {})
                        warns = {int(k): v for k, v in data.get("warns", {}).items()}
                        mutes = {int(k): datetime.fromisoformat(v) for k, v in data.get("mutes", {}).items()}
                        admin_tags = {int(k): v for k, v in data.get("admin_tags", {}).items()}
                        admin_roles = {int(k): v for k, v in data.get("admin_roles", {}).items()}
                        read_status = {int(k): v for k, v in data.get("read_status", {}).items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")

    owners.update(OWNER_IDS)

    if ADMIN_TAGS_ENV:
        for pair in ADMIN_TAGS_ENV.split(","):
            parts = pair.split(":")
            if len(parts) >= 2:
                try:
                    admin_tags[int(parts[0])] = parts[1]
                except ValueError:
                    pass
    if ADMIN_ROLES_ENV:
        for pair in ADMIN_ROLES_ENV.split(","):
            parts = pair.split(":")
            if len(parts) >= 2:
                try:
                    admin_roles[int(parts[0])] = parts[1]
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
        "read_status": {str(k): v for k, v in read_status.items()},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(JSONBLOB_URL, json=data) as resp:
                _ = resp.status
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")


# ================== Команды ==================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())


@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help(message: Message):
    await message.answer(
        "/help /stats /id /rank /close /block /unblock /warn /mute /unmute /warns /myrank /greet"
    )


@dp.message(Command("myrank"))
async def cmd_myrank(message: Message):
    await message.answer(f"Ваш ранг: {get_rank(message.from_user.id)}")


@dp.message(Command("stats"), F.chat.id == GROUP_ID)
async def cmd_stats(message: Message):
    await message.answer(
        f"👥 Всего: {len(all_users)}\n"
        f"💬 Тем: {len(user_topics)}\n"
        f"🔒 Блок: {len(blocked_users)}"
    )


@dp.message(Command("id"), F.chat.id == GROUP_ID)
async def cmd_id(message: Message):
    user_id = find_user_by_topic(message.message_thread_id)
    await message.answer(f"ID: {user_id}" if user_id else "Не найден")


@dp.message(Command("close"), F.chat.id == GROUP_ID)
async def cmd_close(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    topic_id = message.message_thread_id
    user_id = find_user_by_topic(topic_id)
    if user_id:
        stop_reminder(topic_id)
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception as e:
            logging.error(f"Ошибка удаления: {e}")
            await message.answer("Не удалось удалить тему.")
            return
        user_topics.pop(user_id, None)
        admin_to_user_msg = {k: v for k, v in admin_to_user_msg.items() if k[0] != topic_id}
        user_to_admin_msg = {k: v for k, v in user_to_admin_msg.items() if k[0] != user_id}
        read_status.pop(user_id, None)
        topic_history.pop(topic_id, None)
        frozen_topics.pop(topic_id, None)
        await save_data()
        await message.answer("Тема удалена.")
        try:
            await bot.send_message(user_id, "Пожалуйста, оцените работу администратора от 1 до 10:", reply_markup=rating_keyboard())
        except Exception:
            pass
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
    read_status.clear()
    reminders.clear()
    frozen_topics.clear()
    topic_history.clear()
    admin_tags.clear()
    admin_roles.clear()
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
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /broadcast <текст>")
        return
    sent, failed = 0, 0
    for user_id in list(all_users):
        try:
            await bot.send_message(user_id, parts[1])
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await message.answer(f"Отправлено: {sent}\nНе удалось: {failed}")


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
    except ValueError:
        await message.answer("Неверный user_id.")
        return
    rank = args[2].lower()
    if rank == "admin":
        admins.add(target_id)
    elif rank == "owner":
        owners.add(target_id)
    else:
        await message.answer("Ранг только admin или owner.")
        return
    await save_data()
    await message.answer("Готово.")


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
    except ValueError:
        await message.answer("Неверный user_id.")
        return
    admin_tags[target_id] = args[2]
    await save_data()
    await message.answer("Тег установлен.")


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
    except ValueError:
        await message.answer("Неверный user_id.")
        return
    admin_roles[target_id] = args[2]
    await save_data()
    await message.answer("Роль установлена.")


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
    except ValueError:
        await message.answer("Неверный user_id.")
        return
    admins.discard(target_id)
    owners.discard(target_id)
    await save_data()
    await message.answer("Ранг снят.")


@dp.message(Command("liststaff"), F.chat.id == GROUP_ID)
async def cmd_liststaff(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    o = ", ".join(map(str, owners)) or "нет"
    a = ", ".join(map(str, admins)) or "нет"
    await message.answer(f"👑 Владельцы: {o}\n🛡️ Админы: {a}")


@dp.message(Command("warn"), F.chat.id == GROUP_ID)
async def cmd_warn(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    warns[user_id] = warns.get(user_id, 0) + 1
    await save_data()
    if warns[user_id] >= 3:
        blocked_users.add(user_id)
        await save_data()
        try:
            await bot.send_message(user_id, "Вы получили 3 предупреждения и были заблокированы.")
        except Exception:
            pass
        await message.answer(f"⚠️ {user_id} заблокирован (3 варна).")
    else:
        await message.answer(f"⚠️ Варн. Всего: {warns[user_id]}")


@dp.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.answer("Формат: /mute <число> <минут|часов|дней> <причина>")
        return
    try:
        value = int(args[1])
    except ValueError:
        await message.answer("Неверное число.")
        return
    reason = ""
    if len(args) >= 3:
        if args[2].startswith(("час", "ч")):
            value *= 60
        elif args[2].startswith(("день", "дн", "д")):
            value *= 1440
        else:
            reason = args[2]
    if len(args) >= 4:
        reason = (reason + " " + args[3]).strip()

    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    mutes[user_id] = datetime.now() + timedelta(minutes=value)
    await save_data()
    rt = f"\nПричина: {reason}" if reason else ""
    await message.answer(f"🔇 Замучен до {mutes[user_id].strftime('%H:%M')}{rt}")


@dp.message(F.chat.id == GROUP_ID, F.text.lower().in_(["/unmute", "/размут"]))
async def cmd_unmute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    if user_id in mutes:
        del mutes[user_id]
        await save_data()
        await message.answer("🔊 Размучен.")
    else:
        await message.answer("Не в муте.")


@dp.message(Command("warns"), F.chat.id == GROUP_ID)
async def cmd_warns(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Недостаточно прав.")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    await message.answer(f"Варнов: {warns.get(user_id, 0)}")


@dp.message(Command("rank"))
async def cmd_rank(message: Message):
    target = None
    if message.chat.type in ["group", "supergroup"] and message.message_thread_id:
        target = find_user_by_topic(message.message_thread_id)
    args = message.text.split()
    if len(args) == 2:
        try:
            target = int(args[1])
        except ValueError:
            pass
    if target is None and message.chat.type == "private":
        target = message.from_user.id
    if target is None:
        await message.answer("Не найден. Используй /rank <id>")
        return
    await message.answer(f"Ранг {target}: {get_rank(target)}")


@dp.message(Command("greet"), F.chat.id == GROUP_ID)
async def cmd_greet(message: Message):
    admin_id = message.from_user.id
    greeting = ADMIN_GREETINGS.get(admin_id)
    if not greeting:
        await message.answer("У тебя нет приветствия.")
        return
    topic_id = message.message_thread_id
    if topic_id is None:
        await message.answer("Пиши эту команду в теме с пользователем.")
        return
    user_id = find_user_by_topic(topic_id)
    if not user_id:
        await message.answer("Пользователь не найден.")
        return
    try:
        await bot.send_message(user_id, greeting)
        await message.answer("Приветствие отправлено.")
    except Exception as e:
        logging.error(f"Ошибка greet: {e}")
        await message.answer("Ошибка отправки.")


# ================== Report ==================

@dp.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("Опиши проблему — она уйдёт владельцам.")
    await state.set_state(ReportStates.waiting_for_text)


@dp.message(ReportStates.waiting_for_text)
async def process_report(message: Message, state: FSMContext):
    text = f"🚨 Репорт от {message.from_user.id}:\n{message.text}"
    for o in owners:
        try:
            await bot.send_message(o, text)
        except Exception:
            pass
    await message.answer("Отправлено.")
    await state.clear()


# ================== Stop ==================

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in user_topics:
        topic_id = user_topics.pop(user_id)
        stop_reminder(topic_id)
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception:
            pass
        read_status.pop(user_id, None)
        topic_history.pop(topic_id, None)
        frozen_topics.pop(topic_id, None)
        await save_data()
    await message.answer("Диалог завершён. Напиши /start, если снова захочешь.")


# ================== Change ==================

@dp.message(Command("change"))
async def cmd_change(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in user_topics:
        await message.answer("У тебя нет активного диалога.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Да, сменить", callback_data="change_yes"),
            InlineKeyboardButton(text="Нет", callback_data="change_no"),
        ]]
    )
    await message.answer(
        "Сменить админа/категорию? История перенесётся, старая тема замораживается.",
        reply_markup=kb,
    )
    await state.set_state(ChangeStates.confirm)


@dp.callback_query(F.data == "change_no")
async def change_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Ок, оставляем как есть.")
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "change_yes")
async def change_yes(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    old_topic_id = user_topics.get(user_id)
    if not old_topic_id:
        await callback.message.edit_text("Тема не найдена.")
        await state.clear()
        await callback.answer()
        return

    username = callback.from_user.username or f"id{user_id}"

    try:
        new_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        new_topic_id = new_topic.message_thread_id
    except Exception as e:
        logging.error(f"Change: создать тему не удалось: {e}")
        await callback.message.edit_text("Не удалось создать новую тему.")
        await state.clear()
        await callback.answer()
        return

    # Перенос истории
    old_history = topic_history.get(old_topic_id, [])[:]
    for msg_id in old_history:
        try:
            copied = await bot.copy_message(
                chat_id=GROUP_ID,
                from_chat_id=GROUP_ID,
                message_id=msg_id,
                message_thread_id=new_topic_id,
            )
            topic_history.setdefault(new_topic_id, []).append(copied.message_id)
        except Exception as e:
            logging.error(f"Не удалось скопировать {msg_id}: {e}")

    card = (
        f"🔄 Изменено: пользователь {username} сменил админа/категорию.\n"
        f"История сообщений перенесена."
    )
    try:
        sent = await bot.send_message(
            GROUP_ID,
            card,
            message_thread_id=new_topic_id,
            reply_markup=get_keyboard(user_id),
        )
        topic_history.setdefault(new_topic_id, []).append(sent.message_id)
    except Exception as e:
        logging.error(f"Карточка change не отправлена: {e}")

    frozen_topics[old_topic_id] = True
    try:
        await bot.send_message(
            GROUP_ID,
            "❄️ Тема заморожена, диалог перенесён в новую.",
            message_thread_id=old_topic_id,
        )
    except Exception:
        pass

    stop_reminder(old_topic_id)
    user_topics[user_id] = new_topic_id
    read_status[user_id] = False
    topic_history.pop(old_topic_id, None)
    await save_data()

    await callback.message.edit_text(
        "Готово! Выбери админа или категорию заново.",
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()
    await callback.answer()


# ================== Личные сообщения ==================

@dp.message(F.chat.type == "private")
async def handle_user_message(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if message.text and message.text.startswith("/"):
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
        await message.answer("Вы заблокированы.")
        return

    # Reply-кнопки
    if message.text == "👤 Выбрать админа":
        await show_admin_buttons(message)
        return
    if message.text == "📂 Выбрать категорию":
        await message.answer("Выберите категорию:", reply_markup=category_keyboard())
        return
    if message.text == "📜 Правила общения":
        await message.answer(RULES_TEXT)
        return

    if user_id not in user_topics:
        text = message.text or ""
        if is_greeting(text):
            await message.answer("Привет! Выбери кнопку ниже.", reply_markup=main_menu_keyboard())
            return

        type_comm, admin_gender = parse_request(text)
        if type_comm and admin_gender:
            username = message.from_user.username or f"id{user_id}"
            try:
                topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
                topic_id = topic.message_thread_id
                user_topics[user_id] = topic_id
                read_status[user_id] = False
                await save_data()

                info = (
                    f"🆕 Новый запрос!\n"
                    f"👤 Имя: {message.from_user.full_name}\n"
                    f"🔖 Username: @{message.from_user.username or 'нет'}\n"
                    f"📌 Тип: {type_comm}\n"
                    f"🚻 Пол: {admin_gender}\n"
                )
                sent = await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
                topic_history.setdefault(topic_id, []).append(sent.message_id)
                await message.answer("Готово! Админ скоро свяжется.")
            except Exception as e:
                logging.error(f"Ошибка создания темы: {e}")
                await message.answer("Ошибка. Попробуй позже.")
        else:
            await message.answer("Укажи категорию и пол, например: «привет поддержка мальчик».")
        return

    topic_id = user_topics[user_id]

    try:
        if message.text:
            sent = await bot.send_message(GROUP_ID, message.text, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
            user_to_admin_msg[(user_id, message.message_id)] = sent.message_id
        elif message.photo:
            sent = await bot.send_photo(GROUP_ID, message.photo[-1].file_id, caption=message.caption, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
        elif message.video:
            sent = await bot.send_video(GROUP_ID, message.video.file_id, caption=message.caption, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
        elif message.voice:
            sent = await bot.send_voice(GROUP_ID, message.voice.file_id, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
        elif message.video_note:
            sent = await bot.send_video_note(GROUP_ID, message.video_note.file_id, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
        elif message.document:
            sent = await bot.send_document(GROUP_ID, message.document.file_id, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
        elif message.sticker:
            sent = await bot.send_sticker(GROUP_ID, message.sticker.file_id, message_thread_id=topic_id)
            topic_history.setdefault(topic_id, []).append(sent.message_id)
    except Exception as e:
        error_text = str(e).lower()
        if "message thread not found" in error_text or "topic closed" in error_text:
            username = message.from_user.username or f"id{user_id}"
            try:
                topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
                new_topic_id = topic.message_thread_id
                user_topics[user_id] = new_topic_id
                await save_data()
                info = f"🔄 Восстановление темы.\nИмя: {message.from_user.full_name}\n"
                await bot.send_message(GROUP_ID, info, message_thread_id=new_topic_id, reply_markup=get_keyboard(user_id, read=False))
                await message.answer("Тема пересоздана.")
            except Exception as e2:
                logging.error(f"Не удалось пересоздать: {e2}")
                await message.answer("Ошибка отправки.")
        else:
            logging.error(f"Ошибка пересылки: {e}")


# ================== Выбор админа ==================

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
    await message.answer("Выберите админа:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("admin_"))
async def process_admin_selected(callback: CallbackQuery):
    try:
        admin_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("Ошибка.")
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"

    try:
        topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        topic_id = topic.message_thread_id
        user_topics[user_id] = topic_id
        read_status[user_id] = False
        await save_data()
    except Exception as e:
        logging.error(f"Ошибка темы: {e}")
        await callback.message.answer("Не удалось создать тему.")
        await callback.answer()
        return

    admin_tag = admin_tags.get(admin_id, "")
    admin_role = admin_roles.get(admin_id, "")
    extra = ""
    if admin_tag:
        extra += f"\n🏷 Тег: {admin_tag}"
    if admin_role:
        extra += f"\n👔 Роль: {admin_role}"

    info = (
        f"🆕 Новый запрос!\n"
        f"👤 Имя: {callback.from_user.full_name}\n"
        f"🔖 Username: @{callback.from_user.username or 'нет'}\n"
        f"📌 Выбран админ (ID {admin_id}){extra}\n"
    )
    sent = await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
    topic_history.setdefault(topic_id, []).append(sent.message_id)

    start_reminder(topic_id, admin_id)

    try:
        await bot.send_message(admin_id, f"Новый пользователь. Тема: {topic_id}")
    except Exception:
        pass

    await callback.message.answer("Готово! Админ уведомлён.")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ================== Выбор категории ==================

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_selected(callback: CallbackQuery):
    cat = callback.data.split("_", 1)[1]

    type_comm = None
    admin_gender = None
    if cat == "male_comm":
        admin_gender = "Мальчик"; type_comm = "Общение"
    elif cat == "male_support":
        admin_gender = "Мальчик"; type_comm = "Поддержка"
    elif cat == "female_comm":
        admin_gender = "Девочка"; type_comm = "Общение"
    elif cat == "female_support":
        admin_gender = "Девочка"; type_comm = "Поддержка"
    elif cat == "any_comm":
        admin_gender = "Любой"; type_comm = "Общение"
    elif cat == "any_support":
        admin_gender = "Любой"; type_comm = "Поддержка"

    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"

    try:
        topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        topic_id = topic.message_thread_id
        user_topics[user_id] = topic_id
        read_status[user_id] = False
        await save_data()
    except Exception as e:
        logging.error(f"Ошибка темы: {e}")
        await callback.message.answer("Не удалось создать тему.")
        await callback.answer()
        return

    info = (
        f"🆕 Новый запрос!\n"
        f"👤 Имя: {callback.from_user.full_name}\n"
        f"🔖 Username: @{callback.from_user.username or 'нет'}\n"
        f"📌 Тип: {type_comm}\n"
        f"🚻 Пол: {admin_gender}\n"
    )
    sent = await bot.send_message(GROUP_ID, info, message_thread_id=topic_id, reply_markup=get_keyboard(user_id, read=False))
    topic_history.setdefault(topic_id, []).append(sent.message_id)
    await callback.message.answer("Готово! Админ скоро свяжется.")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ================== Рейтинг ==================

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery, state: FSMContext):
    if callback.data == "rate_skip":
        await callback.message.edit_text("Спасибо!")
        await callback.answer()
        return
    rating = int(callback.data.split("_")[1])
    await state.update_data(rating=rating)
    await callback.message.edit_text("Комментарий (или /skip):")
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


# ================== Сообщения из группы ==================

@dp.message(F.chat.id == GROUP_ID)
async def handle_admin_message(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    if not message.message_thread_id:
        return

    topic_id = message.message_thread_id

    if frozen_topics.get(topic_id):
        return

    user_id = find_user_by_topic(topic_id)
    if user_id is None:
        return

    # остановить напоминание
    data = reminders.get(topic_id)
    if data and not data["answered"]:
        data["answered"] = True
        task = data.get("task")
        if task:
            task.cancel()

    if message.text and message.text.startswith("//"):
        return

    try:
        if message.text:
            sent = await bot.send_message(user_id, message.text)
            admin_to_user_msg[(topic_id, message.message_id)] = sent.message_id
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
        logging.error(f"Ошибка отправки {user_id}: {e}")


# ================== Редактирование ==================

@dp.edited_message(F.chat.id == GROUP_ID)
async def handle_admin_edited(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if not message.message_thread_id:
        return
    if not message.text:
        return

    topic_id = message.message_thread_id
    user_id = find_user_by_topic(topic_id)
    if user_id is None:
        return

    key = (topic_id, message.message_id)
    user_msg_id = admin_to_user_msg.get(key)
    if not user_msg_id:
        return

    new_text = message.text
    if new_text.startswith("//"):
        return

    try:
        await bot.edit_message_text(chat_id=user_id, message_id=user_msg_id, text=new_text)
    except Exception as e:
        logging.error(f"Ошибка редактирования у пользователя: {e}")


@dp.edited_message(F.chat.type == "private")
async def handle_user_edited(message: Message):
    user_id = message.from_user.id
    if not message.text:
        return

    topic_id = user_topics.get(user_id)
    if not topic_id:
        return

    key = (user_id, message.message_id)
    admin_msg_id = user_to_admin_msg.get(key)
    if not admin_msg_id:
        return

    try:
        await bot.edit_message_text(chat_id=GROUP_ID, message_id=admin_msg_id, text=message.text)
    except Exception as e:
        logging.error(f"Ошибка редактирования в теме: {e}")


# ================== Кнопки карточки ==================

@dp.callback_query(F.data.startswith("block:"))
async def process_block(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    blocked_users.add(user_id)
    read_status[user_id] = False
    await save_data()
    try:
        await bot.send_message(user_id, "Вы заблокированы.")
    except Exception:
        pass
    try:
        await callback.message.edit_text(
            callback.message.text + "\n\n🔒 Заблокирован",
            reply_markup=get_keyboard(user_id, read=False),
        )
    except Exception:
        pass
    await callback.answer("Заблокирован")


@dp.callback_query(F.data.startswith("unblock:"))
async def process_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    try:
        await callback.message.edit_text(
            callback.message.text + "\n\n❓ Разблокировать?",
            reply_markup=get_confirm_keyboard(user_id),
        )
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_unblock:"))
async def process_confirm_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    blocked_users.discard(user_id)
    read_status[user_id] = False
    await save_data()
    try:
        await bot.send_message(user_id, "Вы разблокированы.")
    except Exception:
        pass
    lines = callback.message.text.split("\n")
    while lines and lines[-1] in ("🔒 Заблокирован", "❓ Разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer("Разблокирован")


@dp.callback_query(F.data.startswith("cancel_unblock:"))
async def process_cancel_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    lines = callback.message.text.split("\n")
    while lines and lines[-1] in ("🔒 Заблокирован", "❓ Разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("read:"))
async def process_read(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    try:
        await bot.send_message(user_id, "Запрос прочитан, скоро свяжутся.")
    except Exception:
        pass
    read_status[user_id] = True
    await save_data()
    lines = callback.message.text.split("\n")
    while lines and lines[-1] in ("✅ Прочитано", "❓ Разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text("\n".join(lines) + "\n\n✅ Прочитано", reply_markup=get_keyboard(user_id, read=True))
    except Exception:
        pass
    await callback.answer("Прочитано")


@dp.callback_query(F.data.startswith("unread:"))
async def process_unread(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    read_status[user_id] = False
    await save_data()
    lines = callback.message.text.split("\n")
    while lines and lines[-1] == "✅ Прочитано":
        lines.pop()
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer("Отменено")


# ================== Запуск ==================

async def main():
    logging.basicConfig(level=logging.INFO)
    await load_data()
    await bot.delete_webhook(drop_pending_updates=True)

    polling_task = asyncio.create_task(dp.start_polling(bot))

    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Web server started on port {PORT}")

    await polling_task


if __name__ == "__main__":
    asyncio.run(main())
