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


# ================== КОНФИГ ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
_raw_group = os.getenv("GROUP_ID", "0")
GROUP_ID = int(_raw_group.split()[0])
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


# ================== СПИСОК АДМИНОВ ==================

PRESET_ADMIN_TAGS = {
    7790900154: "#Серафим",
    6354283893: "#Киса",
    2087257865: "#чапа",
    8275375761: "#лютик",
    8790245480: "#падшая",
    6870680424: "#цена",
    5812572110: "#темная",
    6698192304: "#минерва",
    6599739238: "#модок",
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


# ================== ИНИЦИАЛИЗАЦИЯ ==================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_topics = {}       # user_id -> topic_id
blocked_users = set()
admins = set()
owners = set(OWNER_IDS)
all_users = set()
user_rates = {}
warns = {}
mutes = {}             # user_id -> datetime (до какого времени)
admin_tags = {}
admin_roles = {}
read_status = {}       # user_id -> True/False


# ================== СОСТОЯНИЯ ==================

class RateStates(StatesGroup):
    waiting_for_comment = State()


class ReportStates(StatesGroup):
    waiting_for_text = State()


# ================== ТЕКСТЫ ==================

WELCOME_TEXT = "Привет! Выбери действие кнопками ниже."

RULES_TEXT = (
    "Правила общения:\n"
    "1. Будь вежлив.\n"
    "2. Не спамь.\n"
    "3. Уважай других.\n"
    "4. Не выпрашивай юз.\n"
    "5. При конфликте пиши админу."
)


# ================== КЛАВИАТУРЫ ==================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выбрать админа"), KeyboardButton(text="Выбрать категорию")],
            [KeyboardButton(text="Правила общения")],
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


def get_keyboard(user_id: int, read: bool = False) -> InlineKeyboardMarkup:
    if user_id in blocked_users:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Разблокировать", callback_data=f"unblock:{user_id}")]
            ]
        )
    if read:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отменить прочтение", callback_data=f"unread:{user_id}")]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Заблокировать", callback_data=f"block:{user_id}"),
                InlineKeyboardButton(text="Прочитать", callback_data=f"read:{user_id}"),
            ]
        ]
    )


def get_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, разблокировать", callback_data=f"confirm_unblock:{user_id}"),
                InlineKeyboardButton(text="Нет", callback_data=f"cancel_unblock:{user_id}"),
            ]
        ]
    )


# ================== УТИЛИТЫ ==================

def is_owner(user_id: int) -> bool:
    return user_id in owners


def is_admin(user_id: int) -> bool:
    return user_id in admins or is_owner(user_id)


def get_rank(user_id: int) -> str:
    if is_owner(user_id):
        return "Владелец"
    elif is_admin(user_id):
        return "Админ"
    return "Пользователь"


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
    greetings = [
        "привет", "здравствуй", "здарова", "дарова", "ку",
        "сап", "прив", "хай", "hello", "hi", "пр", "здорово",
    ]
    if not text:
        return False
    t = text.lower().strip()
    for g in greetings:
        if t == g or t.startswith(g + " ") or t.startswith(g + "!"):
            return True
    return False


def find_user_by_topic(topic_id: int):
    for uid, tid in user_topics.items():
        if tid == topic_id:
            return uid
    return None


# ================== ЗАГРУЗКА / СОХРАНЕНИЕ ==================

async def load_data():
    global user_topics, blocked_users, admins, owners, all_users
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


# ================== КОМАНДЫ ДЛЯ ГРУППЫ ==================

@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help(message: Message):
    await message.answer(
        "Команды: /help /stats /id /rank /block /unblock /warn /mute /unmute /warns /myrank"
    )


@dp.message(Command("myrank"))
async def cmd_myrank(message: Message):
    await message.answer(f"Ваш ранг: {get_rank(message.from_user.id)}")


@dp.message(Command("stats"), F.chat.id == GROUP_ID)
async def cmd_stats(message: Message):
    await message.answer(
        f"Пользователей: {len(all_users)}\n"
        f"Активных тем: {len(user_topics)}\n"
        f"Заблокировано: {len(blocked_users)}"
    )


@dp.message(Command("id"), F.chat.id == GROUP_ID)
async def cmd_id(message: Message):
    user_id = find_user_by_topic(message.message_thread_id)
    await message.answer(f"ID пользователя: {user_id}" if user_id else "Не найден")


@dp.message(Command("rank"))
async def cmd_rank(message: Message):
    user_id_to_check = None
    if message.chat.type in ["group", "supergroup"] and message.message_thread_id:
        user_id_to_check = find_user_by_topic(message.message_thread_id)

    args = message.text.split()
    if len(args) == 2:
        try:
            user_id_to_check = int(args[1])
        except ValueError:
            pass

    if user_id_to_check is None and message.chat.type == "private":
        user_id_to_check = message.from_user.id

    if user_id_to_check is None:
        await message.answer("Не найден. Используй /rank <user_id>")
        return

    await message.answer(f"Ранг {user_id_to_check}: {get_rank(user_id_to_check)}")


@dp.message(Command("block"), F.chat.id == GROUP_ID)
async def cmd_block(message: Message):
    user_id = find_user_by_topic(message.message_thread_id)
    if user_id:
        blocked_users.add(user_id)
        await save_data()
        await message.answer(f"Пользователь {user_id} заблокирован.")
    else:
        await message.answer("Не найден.")


@dp.message(Command("unblock"), F.chat.id == GROUP_ID)
async def cmd_unblock(message: Message):
    user_id = find_user_by_topic(message.message_thread_id)
    if user_id:
        blocked_users.discard(user_id)
        await save_data()
        await message.answer(f"Пользователь {user_id} разблокирован.")
    else:
        await message.answer("Не найден.")


@dp.message(Command("warn"), F.chat.id == GROUP_ID)
async def cmd_warn(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
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
            await bot.send_message(user_id, "Вы заблокированы (3 варна).")
        except Exception:
            pass
        await message.answer(f"Пользователь {user_id} заблокирован (3 варна).")
    else:
        await message.answer(f"Варн выдан. Всего: {warns[user_id]}")


@dp.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
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
        reason = args[3] if not reason else reason + " " + args[3]

    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    mutes[user_id] = datetime.now() + timedelta(minutes=value)
    await save_data()
    rt = f"\nПричина: {reason}" if reason else ""
    await message.answer(f"Замучен до {mutes[user_id].strftime('%H:%M')}{rt}")


@dp.message(F.chat.id == GROUP_ID, F.text.lower().in_(["/unmute", "/размут"]))
async def cmd_unmute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    if user_id in mutes:
        del mutes[user_id]
        await save_data()
        await message.answer("Размучен.")
    else:
        await message.answer("Не в муте.")


@dp.message(Command("warns"), F.chat.id == GROUP_ID)
async def cmd_warns(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    await message.answer(f"Варнов: {warns.get(user_id, 0)}")


# ================== КОМАНДА СТАРТ ==================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())


# ================== КОМАНДА REPORT ==================

@dp.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("Опишите проблему — она уйдёт владельцам.")
    await state.set_state(ReportStates.waiting_for_text)


@dp.message(ReportStates.waiting_for_text)
async def process_report(message: Message, state: FSMContext):
    text = f"Репорт от {message.from_user.id}:\n{message.text}"
    for o in owners:
        try:
            await bot.send_message(o, text)
        except Exception:
            pass
    await message.answer("Отправлено.")
    await state.clear()


# ================== ЛИЧНЫЕ СООБЩЕНИЯ ==================

@dp.message(F.chat.type == "private")
async def handle_user_message(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Игнорируем команды — они обрабатываются отдельно
    if message.text and message.text.startswith("/"):
        return

    all_users.add(user_id)
    await save_data()

    # Проверка мута
    if user_id in mutes:
        if datetime.now() < mutes[user_id]:
            await message.answer(f"Вы в муте до {mutes[user_id].strftime('%H:%M')}.")
            return
        else:
            del mutes[user_id]
            await save_data()

    # Проверка блокировки
    if user_id in blocked_users:
        await message.answer("Вы заблокированы.")
        return

    # === REPLY-КНОПКИ (работают всегда) ===
    if message.text == "Выбрать админа":
        await show_admin_buttons(message)
        return
    if message.text == "Выбрать категорию":
        await message.answer("Выберите категорию:", reply_markup=category_keyboard())
        return
    if message.text == "Правила общения":
        await message.answer(RULES_TEXT)
        return

    # === ЕСЛИ ТЕМЫ ЕЩЁ НЕТ ===
    if user_id not in user_topics:
        text = message.text or ""
        if is_greeting(text):
            await message.answer(
                "Привет! Выбери кнопку ниже.",
                reply_markup=main_menu_keyboard(),
            )
            return

        type_comm, admin_gender = parse_request(text)
        if type_comm and admin_gender:
            await create_topic_for_user(
                user_id=user_id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                type_comm=type_comm,
                admin_gender=admin_gender,
                reply_to=message,
            )
        else:
            await message.answer(
                "Укажи категорию и пол, например: «привет поддержка мальчик».\n"
                "Или нажми кнопку «Выбрать категорию»."
            )
        return

    # === ТЕМА ЕСТЬ — ПЕРЕСЫЛАЕМ ===
    topic_id = user_topics[user_id]
    try:
        if message.text:
            await bot.send_message(GROUP_ID, message.text, message_thread_id=topic_id)
        elif message.photo:
            await bot.send_photo(
                GROUP_ID,
                message.photo[-1].file_id,
                caption=message.caption,
                message_thread_id=topic_id,
            )
        elif message.video:
            await bot.send_video(
                GROUP_ID,
                message.video.file_id,
                caption=message.caption,
                message_thread_id=topic_id,
            )
        elif message.voice:
            await bot.send_voice(GROUP_ID, message.voice.file_id, message_thread_id=topic_id)
        elif message.video_note:
            await bot.send_video_note(GROUP_ID, message.video_note.file_id, message_thread_id=topic_id)
        elif message.document:
            await bot.send_document(GROUP_ID, message.document.file_id, message_thread_id=topic_id)
        elif message.sticker:
            await bot.send_sticker(GROUP_ID, message.sticker.file_id, message_thread_id=topic_id)
    except Exception as e:
        logging.error(f"Ошибка пересылки от пользователя: {e}")


# ================== СОЗДАНИЕ ТЕМЫ ==================

async def create_topic_for_user(
    user_id: int,
    username: str,
    full_name: str,
    type_comm: str,
    admin_gender: str,
    reply_to: Message,
):
    username_safe = username or f"id{user_id}"
    try:
        topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username_safe)
        topic_id = topic.message_thread_id
        user_topics[user_id] = topic_id
        read_status[user_id] = False
        await save_data()

        info = (
            f"Новый запрос!\n"
            f"Имя: {full_name}\n"
            f"Username: @{username or 'нет'}\n"
            f"Тип: {type_comm}\n"
            f"Пол админа: {admin_gender}\n"
        )
        await bot.send_message(
            GROUP_ID,
            info,
            message_thread_id=topic_id,
            reply_markup=get_keyboard(user_id),
        )
        await reply_to.answer("Готово! Админ скоро свяжется с тобой.")
    except Exception as e:
        logging.error(f"Не удалось создать тему: {e}")
        await reply_to.answer("Ошибка. Попробуй позже.")


# ================== ВЫБОР АДМИНА ==================

async def show_admin_buttons(message: Message):
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

    if not buttons:
        await message.answer("Нет доступных админов.")
        return

    await message.answer(
        "Выберите админа:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


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
        logging.error(f"Не удалось создать тему: {e}")
        await callback.message.answer("Ошибка создания темы.")
        await callback.answer()
        return

    admin_tag = admin_tags.get(admin_id, "")
    admin_role = admin_roles.get(admin_id, "")
    extra_lines = []
    if admin_tag:
        extra_lines.append(f"Тег: {admin_tag}")
    if admin_role:
        extra_lines.append(f"Роль: {admin_role}")
    extra = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

    info = (
        f"Новый запрос!\n"
        f"Имя: {callback.from_user.full_name}\n"
        f"Username: @{callback.from_user.username or 'нет'}\n"
        f"Выбран админ: ID {admin_id}{extra}\n"
    )
    await bot.send_message(
        GROUP_ID,
        info,
        message_thread_id=topic_id,
        reply_markup=get_keyboard(user_id),
    )

    try:
        await bot.send_message(admin_id, f"Новый пользователь: {topic_id}")
    except Exception:
        pass

    await callback.message.answer("Готово! Админ уведомлён.")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ================== ВЫБОР КАТЕГОРИИ ==================

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_selected(callback: CallbackQuery):
    cat = callback.data.split("_", 1)[1]

    type_comm = None
    admin_gender = None

    if cat == "male_comm":
        admin_gender = "Мальчик"
        type_comm = "Общение"
    elif cat == "male_support":
        admin_gender = "Мальчик"
        type_comm = "Поддержка"
    elif cat == "female_comm":
        admin_gender = "Девочка"
        type_comm = "Общение"
    elif cat == "female_support":
        admin_gender = "Девочка"
        type_comm = "Поддержка"
    elif cat == "any_comm":
        admin_gender = "Любой"
        type_comm = "Общение"
    elif cat == "any_support":
        admin_gender = "Любой"
        type_comm = "Поддержка"

    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"

    try:
        topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        topic_id = topic.message_thread_id
        user_topics[user_id] = topic_id
        read_status[user_id] = False
        await save_data()
    except Exception as e:
        logging.error(f"Не удалось создать тему: {e}")
        await callback.message.answer("Ошибка создания темы.")
        await callback.answer()
        return

    info = (
        f"Новый запрос!\n"
        f"Имя: {callback.from_user.full_name}\n"
        f"Username: @{callback.from_user.username or 'нет'}\n"
        f"Тип: {type_comm}\n"
        f"Пол: {admin_gender}\n"
    )
    await bot.send_message(
        GROUP_ID,
        info,
        message_thread_id=topic_id,
        reply_markup=get_keyboard(user_id),
    )
    await callback.message.answer("Готово! Админ скоро свяжется.")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ================== СООБЩЕНИЯ ИЗ ГРУППЫ ==================

@dp.message(F.chat.id == GROUP_ID)
async def handle_admin_message(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    if message.message_thread_id is None:
        return

    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        return

    # внутренняя заметка
    if message.text and message.text.startswith("//"):
        return

    try:
        if message.text:
            await bot.send_message(user_id, message.text)
        elif message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            await bot.send_video(user_id, message.video.file_id, caption=message.caption)
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
        elif message.video_note:
            await bot.send_video_note(user_id, message.video_note.file_id)
        elif message.document:
            await bot.send_document(user_id, message.document.file_id)
        elif message.sticker:
            await bot.send_sticker(user_id, message.sticker.file_id)
    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {user_id}: {e}")


# ================== КНОПКИ КАРТОЧКИ ==================

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
            callback.message.text + "\n\nЗаблокирован",
            reply_markup=get_keyboard(user_id),
        )
    except Exception:
        pass
    await callback.answer("Заблокирован")


@dp.callback_query(F.data.startswith("unblock:"))
async def process_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    try:
        await callback.message.edit_text(
            callback.message.text + "\n\nТочно разблокировать?",
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
    while lines and lines[-1] in ("Заблокирован", "Точно разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=get_keyboard(user_id),
        )
    except Exception:
        pass
    await callback.answer("Разблокирован")


@dp.callback_query(F.data.startswith("cancel_unblock:"))
async def process_cancel_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    lines = callback.message.text.split("\n")
    while lines and lines[-1] in ("Заблокирован", "Точно разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=get_keyboard(user_id),
        )
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
    while lines and lines[-1] in ("Прочитано", "Точно разблокировать?"):
        lines.pop()
    try:
        await callback.message.edit_text(
            "\n".join(lines) + "\n\nПрочитано",
            reply_markup=get_keyboard(user_id, read=True),
        )
    except Exception:
        pass
    await callback.answer("Прочитано")


@dp.callback_query(F.data.startswith("unread:"))
async def process_unread(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    read_status[user_id] = False
    await save_data()

    lines = callback.message.text.split("\n")
    while lines and lines[-1] == "Прочитано":
        lines.pop()
    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=get_keyboard(user_id, read=False),
        )
    except Exception:
        pass
    await callback.answer("Отменено")


# ================== ЗАПУСК ==================

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
