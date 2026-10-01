import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================== НАСТРОЙКИ ==================
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
    7790900154: "#Серафим", 6354283893: "#Киса", 2087257865: "#Чапа",
    8275375761: "#лютик", 6870680424: "#цена", 5812572110: "#Темная",
    6698192304: "#минерва", 6599739238: "#Мадока", 7894506921: "#добряк",
    7479469048: "#сатана", 8973469291: "#фитоняшка", 7803825182: "#мурлыка",
}
PRESET_ADMIN_ROLES = {
    7790900154: "Влд", 6354283893: "Сов.влд",
    2087257865: "Зам.Сов.Влд//адм.инженер//общение",
    8275375761: "адм.универсал", 6870680424: "адм.общения",
    5812572110: "адм.универсал", 6698192304: "адм.универсал",
    6599739238: "адм.универсал", 7894506921: "Мальчик · Универсал",
    7479469048: "Девочка · Универсал", 8973469291: "Девочка · Универсал",
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================== ХРАНИЛИЩА ==================
user_topics = {}
topic_to_user = {}
chat_mode = {}
user_admin_map = {}
admin_user_map = {}
admin_msg_to_user = {}            # (bot_id, msg_id в группе) -> user_id
private_admin_msg_to_user = {}    # (admin_id, msg_id в ЛС) -> user_id
user_username = {}                # user_id -> @username
user_first_name = {}              # user_id -> first_name

pending_mode_topics = set()
pending_user_messages = {}

blocked_users = set()
admins = set()
owners = set(OWNER_IDS)
all_users = set()
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


# ================== КЛАВИАТУРЫ ==================
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
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock:{user_id}")
        ]])
    if read:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Отменить прочтение", callback_data=f"unread:{user_id}")
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"),
        InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}"),
    ]])


def get_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_unblock:{user_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_unblock:{user_id}"),
    ]])


# ================== УТИЛИТЫ ==================
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


def user_display(user_id: int) -> str:
    """Красивое отображение: @username (ID) или ID."""
    uname = user_username.get(user_id)
    if uname:
        return f"@{uname} (<code>{user_id}</code>)"
    return f"<code>{user_id}</code>"


def user_header(user_id: int, first_name: str = "") -> str:
    """Шапка с юзернеймом для карточек."""
    uname = user_username.get(user_id)
    uname_str = f"@{uname}" if uname else "без юза"
    fname = first_name or user_first_name.get(user_id, "")
    lines = [
        f"👤 <b>@{uname_str}</b>" if uname else "👤 <b>без юза</b>",
        f"🆔 <code>{user_id}</code>",
    ]
    if fname:
        lines.append(f"📛 {fname}")
    return "\n".join(lines)


def remember_user(message: Message):
    """Сохранить username и first_name пользователя."""
    uid = message.from_user.id
    all_users.add(uid)
    if message.from_user.username:
        user_username[uid] = message.from_user.username
    if message.from_user.first_name:
        user_first_name[uid] = message.from_user.first_name


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
                await bot.send_message(
                    GROUP_ID, f"🔔 {mention}, у тебя новый пользователь.",
                    message_thread_id=topic_id
                )
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


# ================== СОХРАНЕНИЕ ==================
async def load_data():
    global user_topics, topic_to_user, blocked_users, admins, owners, all_users
    global warns, mutes, admin_tags, admin_roles, read_status, chat_mode
    global user_admin_map, admin_user_map, user_username, user_first_name

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
                        user_username = {int(k): v for k, v in data.get("user_username", {}).items()}
                        user_first_name = {int(k): v for k, v in data.get("user_first_name", {}).items()}
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
        "user_username": {str(k): v for k, v in user_username.items()},
        "user_first_name": {str(k): v for k, v in user_first_name.items()},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(JSONBLOB_URL, json=data) as resp:
                _ = resp.status
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")


# ================== 1. ВЛАДЕЛЕЦ (ЛИЧКА) ==================
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


@dp.message(Command("users"), F.chat.type == "private")
async def cmd_users(message: Message):
    """Показывает владельцу всех пользователей с юзернеймами."""
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец.")
        return
    if not all_users:
        await message.answer("Пользователей ещё нет.")
        return
    lines = [f"👥 Всего: {len(all_users)}\n"]
    for uid in list(all_users)[:50]:
        uname = user_username.get(uid)
        uname_str = f"@{uname}" if uname else "без юза"
        topic = user_topics.get(uid)
        status = "🔒" if uid in blocked_users else ("💬" if topic else "⚪")
        lines.append(f"{status} <code>{uid}</code> | {uname_str}")
    await message.answer("\n".join(lines))


@dp.message(Command("who"), F.chat.type == "private")
async def cmd_who_private(message: Message):
    """Админ пишет /who <id> — получает инфу о пользователе."""
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Формат: /who <id>")
        return
    try:
        uid = int(args[1])
    except ValueError:
        await message.answer("Неверный ID.")
        return
    uname = user_username.get(uid)
    uname_str = f"@{uname}" if uname else "без юза"
    fname = user_first_name.get(uid, "—")
    mode = mode_label(chat_mode.get(uid, "—"))
    topic = user_topics.get(uid, "—")
    status = "🔒 заблокирован" if uid in blocked_users else "🟢 активен"
    await message.answer(
        f"👤 <b>Пользователь</b>\n"
        f"  ID: <code>{uid}</code>\n"
        f"  Username: {uname_str}\n"
        f"  Имя: {fname}\n"
        f"  Режим: {mode}\n"
        f"  Тема: <code>{topic}</code>\n"
        f"  Статус: {status}"
    )


# ================== 2. ПОЛЬЗОВАТЕЛЬ (КОМАНДЫ ЛИЧКИ) ==================
@dp.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    chat_mode.pop(user_id, None)
    remember_user(message)
    await save_data()
    msg = await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    user_temp_messages.setdefault(user_id, []).append(msg.message_id)


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
    text = f"🚨 Репорт от {user_display(message.from_user.id)}:\n{message.text}"
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


# ================== 3. CALLBACK'И ==================
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
    username = user_username.get(user_id) or callback.from_user.username or f"id{user_id}"
    old_exists = True
    try:
        await bot.edit_forum_topic(
            chat_id=GROUP_ID, message_thread_id=old_topic_id,
            name=f"[ЗАМОРОЖЕНО] @{username}"
        )
    except Exception:
        old_exists = False
    try:
        new_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=f"@{username}")
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
            await bot.copy_message(
                chat_id=GROUP_ID, from_chat_id=GROUP_ID,
                message_id=msg_id, message_thread_id=new_topic_id
            )
        except Exception:
            continue

    card = f"🔄 Изменено: {user_display(user_id)} сменил админа/категорию.\nИстория перенесена."
    try:
        sent = await bot.send_message(
            GROUP_ID, card, message_thread_id=new_topic_id,
            reply_markup=get_keyboard(user_id)
        )
        card_texts[sent.message_id] = card
    except Exception:
        pass

    if old_exists:
        frozen_topics[old_topic_id] = True
        try:
            await bot.send_message(
                GROUP_ID, "❄️ Тема заморожена.", message_thread_id=old_topic_id
            )
        except Exception:
            pass

    stop_reminder(old_topic_id)
    user_topics[user_id] = new_topic_id
    topic_to_user.pop(old_topic_id, None)
    topic_to_user[new_topic_id] = user_id
    read_status[user_id] = False
    waiting_admin_replied[user_id] = False
    topic_history.pop(old_topic_id, None)
    chat_mode.pop(user_id, None)
    admin_id = user_admin_map.pop(user_id, None)
    if admin_id:
        admin_user_map.pop(admin_id, None)
    await save_data()

    if callback.message.chat.type == "private":
        await callback.message.answer(
            "Готово! Выбери админа/категорию заново.",
            reply_markup=main_menu_keyboard(),
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        await callback.message.edit_text("Готово! Пользователь выберет админа/категорию заново.")
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def on_category(callback: CallbackQuery):
    category = callback.data.replace("cat_", "")
    user_id = callback.from_user.id
    label_map = {
        "male_comm": "👦 Мальчик · Общение",
        "male_support": "👦 Мальчик · Поддержка",
        "female_comm": "👧 Девочка · Общение",
        "female_support": "👧 Девочка · Поддержка",
        "any_comm": "🌈 Любой · Общение",
        "any_support": "🌈 Любой · Поддержка",
    }
    label = label_map.get(category, category)
    await callback.message.edit_text(
        f"Категория: <b>{label}</b>\n\nОпиши, что случилось 👇"
    )

    # Уведомляем админов с @username
    uname = user_username.get(user_id)
    uname_str = f"@{uname}" if uname else "без юза"
    fname = user_first_name.get(user_id, "")
    notif = (
        f"📩 <b>Новая заявка</b>\n"
        f"👤 {uname_str} (<code>{user_id}</code>)\n"
        f"📛 {fname}\n"
        f"🎯 Категория: <b>{label}</b>"
    )
    for adm in (admins | owners):
        try:
            await bot.send_message(adm, notif)
        except Exception:
            pass

    await callback.answer()


@dp.callback_query(F.data.startswith("mode_"))
async def on_mode(callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_id = callback.from_user.id
    chat_mode[user_id] = mode
    await save_data()
    admin_id = user_admin_map.get(user_id)
    if admin_id:
        try:
            await bot.send_message(
                admin_id,
                f"🌙 {user_display(user_id)} выбрал режим: <b>{mode_label(mode)}</b>.",
            )
        except Exception:
            pass
    await callback.message.edit_text(f"Режим: <b>{mode_label(mode)}</b>\n\nОпиши, что случилось 👇")
    await callback.answer()


@dp.callback_query(F.data.startswith("adminset_"))
async def on_admin_set(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка", show_alert=True)
        return
    kind, user_id_str = parts
    try:
        user_id = int(user_id_str)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    mode = "group" if kind == "adminset_group" else "private"
    chat_mode[user_id] = mode
    await save_data()
    await callback.answer(f"✅ Режим: {mode_label(mode)}", show_alert=True)
    try:
        await callback.message.edit_text(
            f"✅ Режим установлен: <b>{mode_label(mode)}</b>\n"
            f"Пользователь: {user_display(user_id)}"
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("block:"))
async def on_block(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    blocked_users.add(user_id)
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_keyboard(user_id))
    except Exception:
        pass
    await callback.answer("Заблокирован ✅")


@dp.callback_query(F.data.startswith("unblock:"))
async def on_unblock(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    blocked_users.discard(user_id)
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_keyboard(user_id))
    except Exception:
        pass
    await callback.answer("Разблокирован 🔓")


@dp.callback_query(F.data.startswith("read:"))
async def on_read(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    read_status[user_id] = True
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_keyboard(user_id, read=True))
    except Exception:
        pass
    await callback.answer("Отмечено ✅")


@dp.callback_query(F.data.startswith("unread:"))
async def on_unread(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    read_status[user_id] = False
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_keyboard(user_id))
    except Exception:
        pass
    await callback.answer("Отменено ↩️")


@dp.callback_query(F.data.startswith("rate_"))
async def on_rate(callback: CallbackQuery):
    val = callback.data.replace("rate_", "")
    await callback.message.edit_text(f"Спасибо за оценку: {val} 🌙")
    await callback.answer()


# ================== 4. КОМАНДЫ ГРУППЫ ==================
@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help_group(message: Message):
    await message.answer(
        "/stats /id /rank /close /block /unblock /warn /mute /unmute "
        "/warns /myrank /greet /resetkb /who"
    )


@dp.message(Command("stats"), F.chat.id == GROUP_ID)
async def cmd_stats(message: Message):
    await message.answer(f"👥 {len(all_users)} | 💬 {len(user_topics)} | 🔒 {len(blocked_users)}")


@dp.message(Command("id"), F.chat.id == GROUP_ID)
async def cmd_id(message: Message):
    uid = find_user_by_topic(message.message_thread_id)
    if not uid:
        await message.answer("Не найден")
        return
    await message.answer(f"Пользователь: {user_display(uid)}")


@dp.message(Command("who"), F.chat.id == GROUP_ID)
async def cmd_who_group(message: Message):
    uid = find_user_by_topic(message.message_thread_id)
    if not uid:
        await message.answer("Не найден")
        return
    uname = user_username.get(uid)
    uname_str = f"@{uname}" if uname else "нет юзернейма"
    mode = mode_label(chat_mode.get(uid, "—"))
    await message.answer(
        f"👤 Пользователь:\n"
        f"  ID: <code>{uid}</code>\n"
        f"  Username: {uname_str}\n"
        f"  Режим: {mode}"
    )


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
    await message.answer(f"Ранг {user_display(target)}: {get_rank(target)}")


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


# ================== 🧹 СБРОС REPLY-КЛАВИАТУРЫ В ГРУППЕ ==================
@dp.message(Command("resetkb"), F.chat.id == GROUP_ID)
async def cmd_resetkb(message: Message):
    if not is_owner(message.from_user.id):
        return
    msg = await message.answer("🧹 Клавиатура очищена.", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(2)
    try:
        await msg.delete()
    except Exception:
        pass


# ================== 5. REPLY-КНОПКИ ЛИЧКИ ==================
@dp.message(F.chat.type == "private", F.text == "🤍 Позвать хранителя")
async def btn_call_keeper(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    remember_user(message)
    await save_data()

    if user_id in blocked_users:
        await message.answer("🚫 Ты заблокирован.")
        return
    if user_id in mutes and mutes[user_id] > datetime.now():
        await message.answer(f"🔇 Мут до {mutes[user_id].strftime('%H:%M')}")
        return

    await message.answer(
        "🤍 Хранитель уже в пути.\n\n"
        "Выбери категорию ниже 👇",
        reply_markup=category_keyboard(),
    )

    # --- Уведомляем всех админов с юзом ---
    uname = user_username.get(user_id)
    uname_str = f"@{uname}" if uname else "без юза"
    fname = user_first_name.get(user_id, "")
    notif = (
        f"🔔 <b>Зовут хранителя!</b>\n"
        f"👤 {uname_str} (<code>{user_id}</code>)\n"
        f"📛 {fname}\n\n"
        f"Выбери категорию и напиши пользователю."
    )
    for adm in (admins | owners):
        try:
            await bot.send_message(adm, notif)
        except Exception:
            pass


@dp.message(F.chat.type == "private", F.text == "🌸 Поболтать")
async def btn_small_talk(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    remember_user(message)
    await save_data()

    msg = await message.answer(
        "🌸 О чём хочешь поболтать? Выбери категорию:",
        reply_markup=category_keyboard(),
    )
    user_temp_messages.setdefault(user_id, []).append(msg.message_id)


@dp.message(F.chat.type == "private", F.text == "📜 Правила")
async def btn_rules(message: Message):
    await message.answer(RULES_TEXT)


# ================== 6. ЛИЧКА — ОБЩИЙ ПРИЁМ ==================
@dp.message(F.chat.type == "private")
async def handle_private(message: Message, state: FSMContext):
    user_id = message.from_user.id
    remember_user(message)

    # ==== АДМИН в личке — отвечает реплаем ====
    if is_admin(user_id):
        if message.reply_to_message:
            key = (user_id, message.reply_to_message.message_id)
            target_user = private_admin_msg_to_user.get(key)
            if target_user is not None:
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
                    await message.answer("✅ Отправлено пользователю.")
                except Exception as e:
                    logging.error(f"Ошибка пересылки пользователю: {e}")
                    await message.answer("⚠️ Не удалось отправить пользователю.")
                return
        await message.answer(
            "⚠️ Чтобы ответить пользователю в ЛС, сделай reply на его "
            "пересланное сообщение и напиши ответ."
        )
        return

    # ==== ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ ====
    if user_id in blocked_users:
        await message.answer("🚫 Ты заблокирован.")
        return
    if user_id in mutes and mutes[user_id] > datetime.now():
        await message.answer(f"🔇 Мут до {mutes[user_id].strftime('%H:%M')}")
        return

    if user_id not in user_topics:
        await message.answer(
            "Привет! Напиши /start, чтобы открыть меню 🤍",
            reply_markup=main_menu_keyboard(),
        )
        await save_data()
        return

    # Активный диалог
    topic_id = user_topics.get(user_id)
    if topic_id:
        try:
            sent = await message.forward(chat_id=GROUP_ID, message_thread_id=topic_id)
            admin_msg_to_user[(bot.id, sent.message_id)] = user_id
        except Exception as e:
            logging.error(f"Не удалось переслать в тему: {e}")

    # --- Уведомляем админов в ЛС с юзернеймом ---
    admin_id = user_admin_map.get(user_id)
    targets = [admin_id] if admin_id else list(admins | owners)

    uname = user_username.get(user_id)
    uname_str = f"@{uname}" if uname else "без юза"
    fname = user_first_name.get(user_id, "")
    header = (
        f"📩 <b>Новое сообщение</b>\n"
        f"👤 {uname_str} (<code>{user_id}</code>)\n"
        f"📛 {fname}\n"
        f"─────\n"
        f"Сделай reply на сообщение ниже, чтобы ответить."
    )

    for adm in targets:
        if adm == user_id:
            continue
        try:
            await bot.send_message(adm, header)
            forwarded = await message.forward(adm)
            private_admin_msg_to_user[(adm, forwarded.message_id)] = user_id
        except Exception as e:
            logging.error(f"Не удалось уведомить админа {adm}: {e}")

    await save_data()


# ================== 7. ГРУППА — АДМИНЫ В ТЕМАХ ==================
@dp.message(F.chat.id == GROUP_ID)
async def handle_group(message: Message):
    if message.from_user.id not in admins and message.from_user.id not in owners:
        return

    # Админ отвечает реплаем на пересланное сообщение в теме
    if message.reply_to_message:
        key = (bot.id, message.reply_to_message.message_id)
        target_user = admin_msg_to_user.get(key)
        if target_user is not None:
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
                await message.reply("✅ Отправлено пользователю.")
            except Exception as e:
                logging.error(f"Ошибка ответа из темы: {e}")
                await message.reply("⚠️ Не удалось отправить.")
            return


# ================== ЗАПУСК ==================
async def on_startup():
    await load_data()
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🌙 Открыть меню"),
            BotCommand(command="help", description="🤍 Помощь"),
            BotCommand(command="rules", description="📜 Правила"),
            BotCommand(command="status", description="💬 Статус"),
            BotCommand(command="stop", description="🛑 Завершить диалог"),
            BotCommand(command="myrank", description="👤 Мой ранг"),
        ])
    except Exception as e:
        logging.error(f"set_my_commands: {e}")


async def main():
    await on_startup()
    await bot.delete_webhook(drop_pending_updates=True)

    # --- Веб-заглушка для Render ---
    async def health(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"✅ Web-заглушка запущена на порту {PORT}")

    # --- Polling ---
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
