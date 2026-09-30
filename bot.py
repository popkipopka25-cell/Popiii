import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand,
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

PRESET_ADMIN_TAGS = {
    7790900154: "#Серафим",
    6354283893: "#Киса",
    2087257865: "#Чапа",
    8275375761: "#лютик",
    6870680424: "#цена",
    5812572110: "#Темная",
    6698192304: "#минерва",
    6599739238: "#Мадока",
    7894506921: "#добряк",
    7479469048: "#сатана",
    8973469291: "#фитоняшка",
    7803825182: "#мурлыка",
}
PRESET_ADMIN_ROLES = {
    7790900154: "Влд",
    6354283893: "Сов.влд",
    2087257865: "Зам.Сов.Влд//адм.инженер//общение",
    8275375761: "адм.универсал",
    6870680424: "адм.общения",
    5812572110: "адм.универсал",
    6698192304: "адм.универсал",
    6599739238: "адм.универсал",
    7894506921: "Мальчик · Универсал",
    7479469048: "Девочка · Универсал",
    8973469291: "Девочка · Универсал",
    7803825182: "Мальчик · Универсал",
}
FORBIDDEN_TAGS = {"#люстра", "#зефирка2.0", "#падшая", "#тигрица"}

ADMIN_GREETINGS = {
    6599739238: (
        "🌙 Когда нам грустно, бог посылает на землю ангела-человека,\n"
        "который придёт и вытрет наши слёзы.\n\n#мадока\n\n"
        "📬 Отзывы: https://t.me/ooih865\n"
        "📣 ТГК: http://t.me/Yasu737\n"
        "📝 Анкетница: @Anketka65_bot"
    ),
    5812572110: (
        "🖤 Привет! Ты находишься в чате у Тёмной.\n\n"
        "Рада видеть тебя!\n\n✨ Как у тебя дела?\n— Тёмная"
    ),
    7790900154: (
        "#Серафим\n\nТы стоишь у черты.\n— Отзывы: https://t.me/ooih865\n— ТГК: https://t.me/Yasu737"
    ),
    2087257865: (
        "👑 Вы написали Царю-Чапике! 👑\n\nНапишите: «о великий чапа яви себя #Чапа»"
    ),
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_topics = {}       # user_id -> topic_id
topic_to_user = {}     # topic_id -> user_id
chat_mode = {}         # user_id -> "group"|"private"|"admin"
user_admin_map = {}    # user_id -> admin_id
admin_user_map = {}    # admin_id -> user_id
pending_mode_topics = set()   # topic_id, где админ ещё не выбрал режим
pending_user_messages = {}    # user_id -> [сообщения, ждущие выбора]
pending_choice_mode = {}      # user_id, ожидает выбор режима для категории
pending_admin_choice = {}     # user_id -> admin_id, ожидает выбор режима

blocked_users = set()
admins = set()
owners = set(OWNER_IDS)
all_users = set()
admin_to_user_msg = {}
user_to_admin_msg = {}
warns = {}
mutes = {}
admin_tags = {}
admin_roles = {}
read_status = {}

reminders = {}
frozen_topics = {}
topic_history = {}
waiting_admin_replied = {}
user_temp_messages = {}
card_texts = {}


class ReportStates(StatesGroup):
    waiting_for_text = State()


class ChangeStates(StatesGroup):
    confirm = State()


WELCOME_TEXT = (
    "🌙 Врата распахнулись — и этот секунд будто замедлил бег.\n\n"
    "🕊 «Что случилось, ангелочек мой?» — этот вопрос здесь не для галочки.\n\n"
    "💭 Здесь можно выговориться, отвлечься или просто помолчать рядом.\n\n"
    "📬 Канал: https://t.me/Yasu737\n"
    "💬 Отзывы: https://t.me/ooih865\n\n"
    "📝 Напиши тег админа и цель: «общение» или «поддержка»."
)

RULES_TEXT = (
    "⚡️ Правила общения:\n"
    "1. Будь вежлив.\n2. Не спамь.\n3. Уважай других.\n"
    "4. Не выпрашивай юз.\n5. При конфликте пиши админу."
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤍 Позвать хранителя"), KeyboardButton(text="🌸 Поболтать")],
            [KeyboardButton(text="📜 Правила")],
        ],
        resize_keyboard=True,
    )


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мальчик · Общение", callback_data="cat_male_comm"),
         InlineKeyboardButton(text="Мальчик · Поддержка", callback_data="cat_male_support")],
        [InlineKeyboardButton(text="Девочка · Общение", callback_data="cat_female_comm"),
         InlineKeyboardButton(text="Девочка · Поддержка", callback_data="cat_female_support")],
        [InlineKeyboardButton(text="Любой · Общение", callback_data="cat_any_comm"),
         InlineKeyboardButton(text="Любой · Поддержка", callback_data="cat_any_support")],
    ])


def chat_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Переписка в группе (в теме)", callback_data="mode_group")],
        [InlineKeyboardButton(text="🤍 Переписка в личке с ботом", callback_data="mode_private")],
        [InlineKeyboardButton(text="🌙 Пусть админ выберет сам", callback_data="mode_admin")],
    ])


def admin_mode_choice_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 В группе", callback_data=f"adminset_group:{user_id}"),
         InlineKeyboardButton(text="🤍 В личке", callback_data=f"adminset_private:{user_id}")],
        [InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"),
         InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}")],
    ])


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
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock:{user_id}")]])
    if read:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Отменить прочтение", callback_data=f"unread:{user_id}")]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"),
        InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}"),
    ]])


def get_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_unblock:{user_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_unblock:{user_id}"),
    ]])


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
    return topic_to_user.get(topic_id)


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


def mode_label(mode: str) -> str:
    if mode == "group":
        return "💬 в группе (в теме)"
    if mode == "private":
        return "🤍 в личке с ботом"
    if mode == "admin":
        return "🌙 админ выбирает"
    return "—"


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
                await bot.send_message(GROUP_ID, f"🔔 {mention}, у тебя новый пользователь.", message_thread_id=topic_id)
            except Exception as e:
                logging.error(f"Напоминание: {e}")
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


async def load_data():
    global user_topics, topic_to_user, blocked_users, admins, owners, all_users
    global warns, mutes, admin_tags, admin_roles, read_status, chat_mode, user_admin_map, admin_user_map

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
                        chat_mode = {int(k): v for k, v in data.get("chat_mode", {}).items()}
                        user_admin_map = {int(k): v for k, v in data.get("user_admin_map", {}).items()}
                        admin_user_map = {v: k for k, v in user_admin_map.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")

    owners.update(OWNER_IDS)
    admin_tags.update(PRESET_ADMIN_TAGS)
    admin_roles.update(PRESET_ADMIN_ROLES)

    for admin_id, tag in list(admin_tags.items()):
        if tag in FORBIDDEN_TAGS:
            admin_tags.pop(admin_id, None)
            admin_roles.pop(admin_id, None)
            admins.discard(admin_id)

    for admin_id in PRESET_ADMIN_TAGS.keys():
        if admin_id not in owners:
            admins.add(admin_id)

    topic_to_user.clear()
    for uid, tid in user_topics.items():
        topic_to_user[tid] = uid


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
        "chat_mode": {str(k): v for k, v in chat_mode.items()},
        "user_admin_map": {str(k): v for k, v in user_admin_map.items()},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(JSONBLOB_URL, json=data) as resp:
                _ = resp.status
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")


# ================== ВЛАДЕЛЕЦ ==================

@dp.message(Command("addadmin"), F.chat.type == "private")
async def cmd_addadmin(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("Формат: /addadmin <id> <тег> <роль>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("Неверный ID.")
        return
    admins.add(target_id)
    admin_tags[target_id] = args[2]
    admin_roles[target_id] = args[3]
    await save_data()
    await message.answer(f"✅ {args[2]} (ID {target_id}) — {args[3]}")


@dp.message(Command("deladmin"), F.chat.type == "private")
async def cmd_deladmin(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Формат: /deladmin <id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("Неверный ID.")
        return
    if target_id in owners:
        await message.answer("Нельзя удалить владельца.")
        return
    admins.discard(target_id)
    tag = admin_tags.pop(target_id, "")
    admin_roles.pop(target_id, None)
    await save_data()
    await message.answer(f"🗑 {tag or 'Админ'} удалён.")


@dp.message(Command("staff"), F.chat.type == "private")
async def cmd_staff(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец.")
        return
    lines = ["👑 Владельцы:"]
    for o in owners:
        lines.append(f"  {o} — {admin_tags.get(o, '—')} ({admin_roles.get(o, '—')})")
    lines.append("\n🛡️ Админы:")
    if admins:
        for a in admins:
            lines.append(f"  {a} — {admin_tags.get(a, '—')} ({admin_roles.get(a, '—')})")
    else:
        lines.append("  нет")
    await message.answer("\n".join(lines))


# ================== ПОЛЬЗОВАТЕЛЬ ==================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    msg = await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    user_temp_messages.setdefault(message.from_user.id, []).append(msg.message_id)


@dp.message(Command("help"), F.chat.type == "private")
async def cmd_user_help(message: Message):
    await message.answer(
        "🤍 Что я умею:\n\n"
        "/rules — правила\n/status — статус\n/change — сменить хранителя\n"
        "/report — жалоба\n/myrank — мой ранг\n/stop — завершить диалог"
    )


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(RULES_TEXT)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    if user_id in user_topics:
        mode = mode_label(chat_mode.get(user_id, "admin"))
        await message.answer(f"💬 Активный диалог.\nРежим: {mode}")
    else:
        await message.answer("Нет активного диалога. Напиши /start.")


@dp.message(Command("myrank"))
async def cmd_myrank(message: Message):
    await message.answer(f"Ваш ранг: {get_rank(message.from_user.id)}")


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


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in user_topics:
        topic_id = user_topics.pop(user_id)
        topic_to_user.pop(topic_id, None)
        stop_reminder(topic_id)
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception:
            pass
        read_status.pop(user_id, None)
        topic_history.pop(topic_id, None)
        frozen_topics.pop(topic_id, None)
        waiting_admin_replied.pop(user_id, None)
        chat_mode.pop(user_id, None)
        pending_mode_topics.discard(topic_id)
        admin_id = user_admin_map.pop(user_id, None)
        if admin_id:
            admin_user_map.pop(admin_id, None)
        await save_data()
    await message.answer("Диалог завершён. Напиши /start, если снова захочешь.")


@dp.message(Command("change"))
async def cmd_change(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in user_topics:
        await message.answer("У тебя нет активного диалога.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, сменить", callback_data="change_yes"),
        InlineKeyboardButton(text="Нет", callback_data="change_no"),
    ]])
    await message.answer("Сменить админа/категорию? История перенесётся.", reply_markup=kb)
    await state.set_state(ChangeStates.confirm)


@dp.callback_query(F.data == "change_no")
async def change_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Ок.")
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
    old_exists = True
    try:
        await bot.edit_forum_topic(chat_id=GROUP_ID, message_thread_id=old_topic_id, name=f"[ЗАМОРОЖЕНО] {username}")
    except Exception:
        old_exists = False
    try:
        new_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        new_topic_id = new_topic.message_thread_id
    except Exception as e:
        logging.error(f"Change: {e}")
        await callback.message.edit_text("Не удалось создать тему.")
        await state.clear()
        await callback.answer()
        return

    old_history = list(dict.fromkeys(topic_history.get(old_topic_id, [])))
    for msg_id in old_history:
        try:
            await bot.copy_message(chat_id=GROUP_ID, from_chat_id=GROUP_ID, message_id=msg_id, message_thread_id=new_topic_id)
        except Exception:
            continue

    card = f"🔄 Изменено: {username} сменил админа/категорию.\nИстория перенесена."
    try:
        sent = await bot.send_message(GROUP_ID, card, message_thread_id=new_topic_id, reply_markup=get_keyboard(user_id))
        card_texts[sent.message_id] = card
    except Exception:
        pass

    if old_exists:
        frozen_topics[old_topic_id] = True
        try:
            await bot.send_message(GROUP_ID, "❄️ Тема заморожена.", message_thread_id=old_topic_id)
        except Exception:
            pass

    stop_reminder(old_topic_id)
    user_topics[user_id] = new_topic_id
    topic_to_user.pop(old_topic_id, None)
    topic_to_user[new_topic_id] = user_id
    read_status[user_id] = False
    waiting_admin_replied[user_id] = False
    topic_history.pop(old_topic_id, None)
    await save_data()

    await callback.message.edit_text("Готово! Выбери админа/категорию заново.", reply_markup=main_menu_keyboard())
    await state.clear()
    await callback.answer()


# ================== КОМАНДЫ ГРУППЫ ==================

@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help_group(message: Message):
    await message.answer("/stats /id /rank /close /block /unblock /warn /mute /unmute /warns /myrank /greet")


@dp.message(Command("stats"), F.chat.id == GROUP_ID)
async def cmd_stats(message: Message):
    await message.answer(f"👥 {len(all_users)} | 💬 {len(user_topics)} | 🔒 {len(blocked_users)}")


@dp.message(Command("id"), F.chat.id == GROUP_ID)
async def cmd_id(message: Message):
    uid = find_user_by_topic(message.message_thread_id)
    await message.answer(f"ID: {uid}" if uid else "Не найден")


@dp.message(Command("close"), F.chat.id == GROUP_ID)
async def cmd_close(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец.")
        return
    topic_id = message.message_thread_id
    user_id = find_user_by_topic(topic_id)
    if user_id:
        stop_reminder(topic_id)
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception:
            await message.answer("Не удалось.")
            return
        user_topics.pop(user_id, None)
        topic_to_user.pop(topic_id, None)
        read_status.pop(user_id, None)
        topic_history.pop(topic_id, None)
        frozen_topics.pop(topic_id, None)
        waiting_admin_replied.pop(user_id, None)
        chat_mode.pop(user_id, None)
        pending_mode_topics.discard(topic_id)
        admin_id = user_admin_map.pop(user_id, None)
        if admin_id:
            admin_user_map.pop(admin_id, None)
        await save_data()
        await message.answer("Тема удалена.")
        try:
            await bot.send_message(user_id, "Оцените работу админа от 1 до 10:", reply_markup=rating_keyboard())
        except Exception:
            pass


@dp.message(Command("broadcast"), F.chat.id == GROUP_ID)
async def cmd_broadcast(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /broadcast <текст>")
        return
    sent, failed = 0, 0
    for uid in list(all_users):
        try:
            await bot.send_message(uid, parts[1])
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await message.answer(f"Отправлено: {sent} / Не удалось: {failed}")


@dp.message(Command("warn"), F.chat.id == GROUP_ID)
async def cmd_warn(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
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
            await bot.send_message(user_id, "3 предупреждения — вы заблокированы.")
        except Exception:
            pass
        await message.answer(f"⚠️ {user_id} заблокирован.")
    else:
        await message.answer(f"⚠️ Варн. Всего: {warns[user_id]}")


@dp.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
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
        await message.answer("⛔")
        return
    user_id = find_user_by_topic(message.message_thread_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    if user_id in mutes:
        del mutes[user_id]
        await save_data()
        await message.answer("🔊 Размучен.")


@dp.message(Command("warns"), F.chat.id == GROUP_ID)
async def cmd_warns(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
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
        await message.answer("Не найден.")
        return
    await message.answer(f"Ранг {target}: {get_rank(target)}")


@dp.message(Command("greet"), F.chat.id == GROUP_ID)
async def cmd_greet(message: Message):
    greeting = ADMIN_GREETINGS.get(message.from_user.id)
    if not greeting:
        await message.answer("У тебя нет приветствия.")
        return
    topic_id = message.message_thread_id
    if topic_id is None:
        await message.answer("Пиши в теме.")
        return
    user_id = find_user_by_topic(topic_id)
    if not user_id:
        await message.answer("Не найден.")
        return
    try:
        await bot.send_message(GROUP_ID, f"Приветствие:\n\n{greeting}", message_thread_id=topic_id)
    except Exception:
        pass
    try:
        await bot.send_message(user_id, greeting)
        await message.answer("Отправлено.")
    except Exception:
        await message.answer("Не удалось.")


# ================== ЛИЧНЫЕ СООБЩЕНИЯ ==================

@dp.message(F.chat.type == "private")
async def handle_private(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # ========== АДМИН ОТВЕЧАЕТ В ЛИЧКЕ ==========
    if user_id in admin_user_map and user_id not in user_topics:
        target_user = admin_user_map[user_id]
        try:
            if message.text:
                await bot.send_message(target_user, message.text)
            elif message.voice:
                await bot.send_voice(target_user, message.voice.file_id)
            elif message.video_note:
                await bot.send_video_note(target_user, message.video_note.file_id)
            elif message.video:
                await bot.send_video(target_user, message.video.file_id)
            elif message.photo:
                await bot.send_photo(target_user, message.photo[-1].file_id)
            elif message.document:
                await bot.send_document(target_user, message.document.file_id)
            elif message.sticker:
                await bot.send_sticker(target_user, message.sticker.file_id)
        except Exception as e:
            logging.error(f"Ошибка пересылки пользователю: {e}")
        return

    # ========== ПОЛЬЗОВАТЕЛЬ ПИШЕТ ==========
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

    if message.text == "🤍 Позвать хранителя":
        await show_admin_buttons(message)
        return
    if message.text == "🌸 Поболтать":
        msg = await message.answer("Выбери категорию:", reply_markup=category_keyboard())
        user_temp_messages.setdefault(user_id, []).append(msg.message_id)
        return
    if message.text == "📜 Правила":
        await message.answer(RULES_TEXT)
        return

    if user_id not in user_topics:
        text = message.text or ""
        if is_greeting(text):
            msg = await message.answer("Привет! Выбери кнопку ниже.", reply_markup=main_menu_keyboard())
            user_temp_messages.setdefault(user_id, []).append(msg.message_id)
            return
        type_comm, admin_gender = parse_request(text)
        if type_comm and admin_gender:
            pending_choice_mode[user_id] = {"type_comm": type_comm, "admin_gender": admin_gender}
            msg = await message.answer("🌙 Где хочешь общаться?", reply_markup=chat_mode_keyboard())
            user_temp_messages.setdefault(user_id, []).append(msg.message_id)
        else:
            await message.answer("Укажи категорию и пол: «привет поддержка мальчик».")
        return

    # ========== ОБРАБОТКА ПО РЕЖИМУ ==========
    mode = chat_mode.get(user_id, "admin")
    topic_id = user_topics[user_id]

    # Режим «в личке с ботом»
    if mode == "private":
        admin_id = user_admin_map.get(user_id)
        if not admin_id:
            await message.answer("⏳ Ещё не назначен админ. Подожди немного.")
            return
        try:
            if message.text:
                await bot.send_message(admin_id, f"💬 от пользователя:\n{message.text}")
            elif message.voice:
                await bot.send_message(admin_id, "🎤 Голосовое от пользователя:")
                await bot.send_voice(admin_id, message.voice.file_id)
            elif message.video_note:
                await bot.send_message(admin_id, "📹 Кружок от пользователя:")
                await bot.send_video_note(admin_id, message.video_note.file_id)
            elif message.video:
                await bot.send_message(admin_id, "🎥 Видео от пользователя:")
                await bot.send_video(admin_id, message.video.file_id)
            elif message.photo:
                await bot.send_message(admin_id, "🖼 Фото от пользователя:")
                await bot.send_photo(admin_id, message.photo[-1].file_id)
            elif message.document:
                await bot.send_message(admin_id, "📎 Документ от пользователя:")
                await bot.send_document(admin_id, message.document.file_id)
            elif message.sticker:
                await bot.send_sticker(admin_id, message.sticker.file_id)
        except Exception as e:
            logging.error(f"Ошибка пересылки админу: {e}")
        return

    # Режим «админ выбирает» (пока не выбрал)
    if mode == "admin" and topic_id in pending_mode_topics:
        pending_user_messages.setdefault(user_id, []).append({
            "type": "text" if message.text else
                    "voice" if message.voice else
                    "video_note" if message.video_note else
                    "video" if message.video else
                    "photo" if message.photo else
                    "document" if message.document else "sticker",
            "content": message.text or (
                message.voice.file_id if message.voice else
                message.video_note.file_id if message.video_note else
                message.video.file_id if message.video else
                message.photo[-1].file_id if message.photo else
                message.document.file_id if message.document else
                message.sticker.file_id if message.sticker else None
            ),
        })
        await message.answer("⏳ Сообщение сохранено. Ждём, пока админ выберет режим.")
        return

    # Режим «в группе»
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
        logging.error(f"Ошибка пересылки в тему: {e}")


# ================== ВЫБОР РЕЖИМА ==================

@dp.callback_query(F.data.startswith("mode_"))
async def process_mode(callback: CallbackQuery):
    mode = callback.data.split("_", 1)[1]
    if mode not in ("group", "private", "admin"):
        await callback.answer("Ошибка.")
        return
    user_id = callback.from_user.id
    chat_mode[user_id] = mode
    await save_data()
    await callback.message.edit_text(f"✅ Режим: {mode_label(mode)}", reply_markup=None)

    if user_id in pending_admin_choice:
        admin_id = pending_admin_choice.pop(user_id)
        await create_topic(callback, admin_id=admin_id, mode=mode)
        await callback.answer()
        return
    if user_id in pending_choice_mode:
        data = pending_choice_mode.pop(user_id)
        await create_topic(callback, type_comm=data["type_comm"], admin_gender=data["admin_gender"], mode=mode)
        await callback.answer()
        return

    msg = await callback.message.answer("Выбери действие:", reply_markup=main_menu_keyboard())
    user_temp_messages.setdefault(user_id, []).append(msg.message_id)
    await callback.answer()


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
        await message.answer("Сейчас нет админов. Напиши категорию текстом.")
        return
    msg = await message.answer("Выбери админа:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    user_temp_messages.setdefault(message.chat.id, []).append(msg.message_id)


@dp.callback_query(F.data.startswith("admin_"))
async def process_admin_selected(callback: CallbackQuery):
    try:
        admin_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("Ошибка.")
        return
    user_id = callback.from_user.id
    if user_id not in chat_mode:
        pending_admin_choice[user_id] = admin_id
        await callback.message.edit_text("🌙 Сначала выбери режим переписки:", reply_markup=chat_mode_keyboard())
        await callback.answer()
        return
    await create_topic(callback, admin_id=admin_id, mode=chat_mode[user_id])
    await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def process_category_selected(callback: CallbackQuery):
    cat = callback.data.split("_", 1)[1]
    type_comm, admin_gender = None, None
    if cat == "male_comm":
        admin_gender, type_comm = "Мальчик", "Общение"
    elif cat == "male_support":
        admin_gender, type_comm = "Мальчик", "Поддержка"
    elif cat == "female_comm":
        admin_gender, type_comm = "Девочка", "Общение"
    elif cat == "female_support":
        admin_gender, type_comm = "Девочка", "Поддержка"
    elif cat == "any_comm":
        admin_gender, type_comm = "Любой", "Общение"
    elif cat == "any_support":
        admin_gender, type_comm = "Любой", "Поддержка"

    user_id = callback.from_user.id
    if user_id not in chat_mode:
        pending_choice_mode[user_id] = {"type_comm": type_comm, "admin_gender": admin_gender}
        await callback.message.edit_text("🌙 Сначала выбери режим переписки:", reply_markup=chat_mode_keyboard())
        await callback.answer()
        return
    await create_topic(callback, type_comm=type_comm, admin_gender=admin_gender, mode=chat_mode[user_id])
    await callback.answer()


async def create_topic(callback: CallbackQuery, admin_id=None, type_comm=None, admin_gender=None, mode="admin"):
    user_id = callback.from_user.id
    username = callback.from_user.username or f"id{user_id}"

    try:
        topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=username)
        topic_id = topic.message_thread_id
    except Exception as e:
        logging.error(f"Ошибка темы: {e}")
        await callback.message.answer("Не удалось создать тему.")
        return

    user_topics[user_id] = topic_id
    topic_to_user[topic_id] = user_id
    read_status[user_id] = False
    waiting_admin_replied[user_id] = False

    if mode == "admin":
        pending_mode_topics.add(topic_id)

    if admin_id:
        user_admin_map[user_id] = admin_id
        admin_user_map[admin_id] = user_id

    await save_data()

    # Карточка
    if admin_id:
        tag = admin_tags.get(admin_id, "")
        role = admin_roles.get(admin_id, "")
        extra = ""
        if tag: extra += f"\n🏷 Тег: {tag}"
        if role: extra += f"\n👔 Роль: {role}"
        info = (
            f"🆕 Новый запрос!\n"
            f"👤 {callback.from_user.full_name}\n"
            f"🔖 @{callback.from_user.username or 'нет'}\n"
            f"📌 Выбран админ (ID {admin_id}){extra}\n"
            f"📍 Режим: {mode_label(mode)}"
        )
    else:
        info = (
            f"🆕 Новый запрос!\n"
            f"👤 {callback.from_user.full_name}\n"
            f"🔖 @{callback.from_user.username or 'нет'}\n"
            f"📌 Тип: {type_comm}\n"
            f"🚻 Пол: {admin_gender}\n"
            f"📍 Режим: {mode_label(mode)}"
        )

    if mode == "admin":
        info += "\n\n👇 Админ, выбери, где тебе удобнее общаться:"
        sent = await bot.send_message(
            GROUP_ID,
            info,
            message_thread_id=topic_id,
            reply_markup=admin_mode_choice_keyboard(user_id),
        )
    else:
        sent = await bot.send_message(
            GROUP_ID,
            info,
            message_thread_id=topic_id,
            reply_markup=get_keyboard(user_id),
        )
    card_texts[sent.message_id] = info

    if admin_id:
        start_reminder(topic_id, admin_id)
        try:
            await bot.send_message(admin_id, f"Новый пользователь. Тема: {topic_id}")
        except Exception:
            pass

    await callback.message.answer("🌙 Я создал(а) уютное местечко. Админ скоро ответит 🤍")
    await delete_user_temp_messages(user_id)


# ================== АДМИН ВЫБИРАЕТ РЕЖИМ ==================

@dp.callback_query(F.data.startswith("adminset_"))
async def process_admin_setmode(callback: CallbackQuery):
    action, uid_str = callback.data.split(":", 1)
    try:
        user_id = int(uid_str)
    except ValueError:
        await callback.answer("Ошибка.")
        return
    new_mode = "group" if action == "adminset_group" else "private"
    chat_mode[user_id] = new_mode
    topic_id = user_topics.get(user_id)
    if topic_id:
        pending_mode_topics.discard(topic_id)
    await save_data()

    original = card_texts.get(callback.message.message_id, callback.message.text)
    try:
        await callback.message.edit_text(
            original + f"\n\n✅ Админ выбрал: {mode_label(new_mode)}",
            reply_markup=get_keyboard(user_id),
        )
    except Exception:
        pass

    # Отправляем накопленные сообщения
    messages = pending_user_messages.pop(user_id, [])
    admin_id = user_admin_map.get(user_id)
    for item in messages:
        try:
            if new_mode == "group" and topic_id:
                if item["type"] == "text":
                    await bot.send_message(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "voice":
                    await bot.send_voice(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "video_note":
                    await bot.send_video_note(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "video":
                    await bot.send_video(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "photo":
                    await bot.send_photo(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "document":
                    await bot.send_document(GROUP_ID, item["content"], message_thread_id=topic_id)
                elif item["type"] == "sticker":
                    await bot.send_sticker(GROUP_ID, item["content"], message_thread_id=topic_id)
            elif new_mode == "private" and admin_id:
                if item["type"] == "text":
                    await bot.send_message(admin_id, f"💬 {item['content']}")
                elif item["type"] == "voice":
                    await bot.send_voice(admin_id, item["content"])
                elif item["type"] == "video_note":
                    await bot.send_video_note(admin_id, item["content"])
                elif item["type"] == "video":
                    await bot.send_video(admin_id, item["content"])
                elif item["type"] == "photo":
                    await bot.send_photo(admin_id, item["content"])
                elif item["type"] == "document":
                    await bot.send_document(admin_id, item["content"])
                elif item["type"] == "sticker":
                    await bot.send_sticker(admin_id, item["content"])
        except Exception as e:
            logging.error(f"Ошибка отправки накопленного: {e}")

    try:
        await bot.send_message(user_id, f"✅ Админ выбрал режим: {mode_label(new_mode)}")
    except Exception:
        pass
    await callback.answer("Режим выбран")


# ================== СООБЩЕНИЯ ИЗ ГРУППЫ ==================

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

    data = reminders.get(topic_id)
    if data and not data["answered"]:
        data["answered"] = True
        task = data.get("task")
        if task:
            task.cancel()
    waiting_admin_replied[user_id] = True

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


@dp.edited_message(F.chat.id == GROUP_ID)
async def handle_admin_edited(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if not message.message_thread_id or not message.text:
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
    except Exception:
        pass


@dp.edited_message(F.chat.type == "private")
async def handle_user_edited(message: Message):
    user_id = message.from_user.id
    if not message.text:
        return
    topic_id = user_topics.get(user_id)
    if not topic_id:
        return
    if chat_mode.get(user_id) != "group":
        return
    key = (user_id, message.message_id)
    admin_msg_id = user_to_admin_msg.get(key)
    if not admin_msg_id:
        return
    try:
        await bot.edit_message_text(chat_id=GROUP_ID, message_id=admin_msg_id, text=message.text)
    except Exception:
        pass


# ================== КНОПКИ КАРТОЧКИ ==================

@dp.callback_query(F.data.startswith("block:"))
async def process_block(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    blocked_users.add(user_id)
    read_status[user_id] = False
    await save_data()
    original = card_texts.get(callback.message.message_id, callback.message.text)
    base = original.split("\n\n🔒 Заблокирован")[0].split("\n\n✅ Прочитано")[0]
    try:
        await bot.send_message(user_id, "Вы заблокированы.")
    except Exception:
        pass
    try:
        await callback.message.edit_text(base + "\n\n🔒 Заблокирован", reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer("Заблокирован")


@dp.callback_query(F.data.startswith("unblock:"))
async def process_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    try:
        await callback.message.edit_text(callback.message.text + "\n\n❓ Разблокировать?", reply_markup=get_confirm_keyboard(user_id))
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_unblock:"))
async def process_confirm_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    blocked_users.discard(user_id)
    read_status[user_id] = False
    await save_data()
    original = card_texts.get(callback.message.message_id, callback.message.text)
    base = original.split("\n\n🔒 Заблокирован")[0].split("\n\n✅ Прочитано")[0]
    try:
        await bot.send_message(user_id, "Вы разблокированы.")
    except Exception:
        pass
    try:
        await callback.message.edit_text(base, reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer("Разблокирован")


@dp.callback_query(F.data.startswith("cancel_unblock:"))
async def process_cancel_unblock(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    original = card_texts.get(callback.message.message_id, callback.message.text)
    base = original.split("\n\n🔒 Заблокирован")[0].split("\n\n✅ Прочитано")[0]
    try:
        await callback.message.edit_text(base, reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("read:"))
async def process_read(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    read_status[user_id] = True
    await save_data()
    original = card_texts.get(callback.message.message_id, callback.message.text)
    base = original.split("\n\n🔒 Заблокирован")[0].split("\n\n✅ Прочитано")[0]
    try:
        await bot.send_message(user_id, "Запрос прочитан, скоро свяжутся.")
    except Exception:
        pass
    try:
        await callback.message.edit_text(base + "\n\n✅ Прочитано", reply_markup=get_keyboard(user_id, read=True))
    except Exception:
        pass
    await callback.answer("Прочитано")


@dp.callback_query(F.data.startswith("unread:"))
async def process_unread(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    read_status[user_id] = False
    await save_data()
    original = card_texts.get(callback.message.message_id, callback.message.text)
    base = original.split("\n\n🔒 Заблокирован")[0].split("\n\n✅ Прочитано")[0]
    try:
        await callback.message.edit_text(base, reply_markup=get_keyboard(user_id, read=False))
    except Exception:
        pass
    await callback.answer("Отменено")


@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery):
    if callback.data == "rate_skip":
        await callback.message.edit_text("Спасибо!")
        await callback.answer()
        return
    await callback.message.edit_text("Спасибо за оценку 🤍")
    await callback.answer()


async def delete_user_temp_messages(user_id: int):
    ids = user_temp_messages.pop(user_id, [])
    for msg_id in ids:
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass


# ================== ЗАПУСК ==================

async def main():
    logging.basicConfig(level=logging.INFO)
    await load_data()
    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать заново"),
        BotCommand(command="help", description="Что я умею"),
        BotCommand(command="rules", description="Правила общения"),
        BotCommand(command="status", description="Статус диалога"),
        BotCommand(command="change", description="Сменить хранителя"),
        BotCommand(command="report", description="Жалоба на админа"),
        BotCommand(command="myrank", description="Мой ранг"),
        BotCommand(command="stop", description="Завершить диалог"),
    ])

    polling_task = asyncio.create_task(dp.start_polling(bot))
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT}")
    await polling_task


if __name__ == "__main__":
    asyncio.run(main())
