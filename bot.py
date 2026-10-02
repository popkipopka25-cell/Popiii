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

# ================== БЕЗОПАСНЫЙ ПАРСИНГ ==================
def safe_int(value, default=0):
    if value is None:
        return default
    try:
        s = str(value).strip()
        if not s:
            return default
        s = s.split()[0]
        return int(s) if s.lstrip("-").isdigit() else default
    except Exception:
        return default

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не задан!")
    raise SystemExit(1)

GROUP_ID = safe_int(os.getenv("GROUP_ID"), 0)
PORT = safe_int(os.getenv("PORT"), 10000) or 10000

_raw_owners = (os.getenv("OWNER_IDS") or "").strip()
OWNER_IDS = set()
for _x in _raw_owners.split(","):
    _x = _x.strip()
    if _x.lstrip("-").isdigit():
        OWNER_IDS.add(int(_x))

JSONBLOB_URL = (os.getenv("JSONBLOB_URL") or "").strip()

logger.info(f"✅ Конфиг: GROUP_ID={GROUP_ID}, PORT={PORT}, OWNERS={OWNER_IDS}, JSONBLOB={'да' if JSONBLOB_URL else 'нет'}")

# ================== КОНСТАНТЫ ==================
PRESET_ADMIN_TAGS = {
    7790900154: "#Серафим", 6354283893: "#Киса", 2087257865: "#Чапа",
    8275375761: "#лютик", 6870680424: "#цена", 5812572110: "#Темная",
    6698192304: "#минерва", 6599739238: "#Мадока", 7894506921: "#добряк",
    7479469048: "#сатана", 8973469291: "#фитоняшка", 7803825182: "#мурлыка",
}
PRESET_ADMIN_ROLES = {
    7790900154: "Влд", 6354283893: "Сов.влд",
    2087257865: "Зам.Сов.Влд // админженер // общение",
    8275375761: "адм.универсал", 6870680424: "адм.общения",
    5812572110: "адм.универсал", 6698192304: "адм.универсал",
    6599739238: "адм.универсал", 7894506921: "Мальчик · Универсал",
    7479469048: "Девочка · Универсал", 8973469291: "Девочка · Универсал",
    7803825182: "Мальчик · Универсал",
}
ADMIN_EMOJI = {
    7790900154: "🕊", 6354283893: "🐱", 2087257865: "👑",
    8275375761: "🌼", 6870680424: "💰", 5812572110: "🖤",
    6698192304: "⚡", 6599739238: "🌙", 7894506921: "🌿",
    7479469048: "😈", 8973469291: "💪", 7803825182: "🐾",
}
FORBIDDEN_TAGS = {"#люстра", "#зефирка2.0", "#падшая", "#тигрица"}

# Категории → список ID админов, подходящих под категорию
CATEGORIES = {
    "male_comm":     {"label": "👦 Мальчик · Общение",     "role_key": "Мальчик", "type": "общение"},
    "male_support":  {"label": "👦 Мальчик · Поддержка",   "role_key": "Мальчик", "type": "поддержка"},
    "female_comm":   {"label": "👧 Девочка · Общение",     "role_key": "Девочка", "type": "общение"},
    "female_support":{"label": "👧 Девочка · Поддержка",   "role_key": "Девочка", "type": "поддержка"},
    "any_comm":      {"label": "🌈 Любой · Общение",       "role_key": None,      "type": "общение"},
    "any_support":   {"label": "🌈 Любой · Поддержка",     "role_key": None,      "type": "поддержка"},
}

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

# ================== ХРАНИЛИЩА ==================
user_topics = {}
topic_to_user = {}
chat_mode = {}
user_admin_map = {}
admin_user_map = {}
admin_msg_to_user = {}
private_admin_msg_to_user = {}
user_username = {}
user_first_name = {}
user_category = {}     # user_id -> категория (для "поболтать")

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


WELCOME_TEXT = (
    "🌙 Врата распахнулись — и этот секунд будто замедлил бег.\n\n"
    "🕊 «Что случилось, ангелочек мой?» — этот вопрос здесь не для галочки.\n\n"
    "💭 Здесь можно выговориться, отвлечься или просто помолчать рядом.\n\n"
    "📬 Канал: https://t.me/Yasu737\n"
    "💬 Отзывы: https://t.me/ooih865"
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


def admins_keyboard() -> InlineKeyboardMarkup:
    """Список админов с эмодзи + тегами."""
    buttons = []
    for admin_id in list(admin_tags.keys()):
        if admin_id in owners or admin_id in admins:
            emoji = ADMIN_EMOJI.get(admin_id, "🛡️")
            tag = admin_tags.get(admin_id, "—")
            role = admin_roles.get(admin_id, "")
            label = f"{emoji} {tag}"
            if role:
                label += f" · {role}"
            if len(label) > 60:
                label = label[:57] + "…"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pick_admin:{admin_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def categories_keyboard() -> InlineKeyboardMarkup:
    """Категории для 'Поболтать'."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👦 Мальчик · Общение", callback_data="pick_cat:male_comm"),
         InlineKeyboardButton(text="👦 Мальчик · Поддержка", callback_data="pick_cat:male_support")],
        [InlineKeyboardButton(text="👧 Девочка · Общение", callback_data="pick_cat:female_comm"),
         InlineKeyboardButton(text="👧 Девочка · Поддержка", callback_data="pick_cat:female_support")],
        [InlineKeyboardButton(text="🌈 Любой · Общение", callback_data="pick_cat:any_comm"),
         InlineKeyboardButton(text="🌈 Любой · Поддержка", callback_data="pick_cat:any_support")],
    ])


def mode_choice_keyboard(source: str, source_id: str) -> InlineKeyboardMarkup:
    """
    source: "admin" | "cat"
    source_id: ID админа (для admin) или ключ категории (для cat)
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Переписка в теме группы", callback_data=f"mode_group:{source}:{source_id}")],
        [InlineKeyboardButton(text="🤍 Переписка в ЛС бота", callback_data=f"mode_private:{source}:{source_id}")],
        [InlineKeyboardButton(text="🌙 Пусть админ выберет сам", callback_data=f"mode_admin:{source}:{source_id}")],
    ])


def get_card_keyboard(user_id: int, mode: str) -> InlineKeyboardMarkup:
    """4 кнопки в карточке темы."""
    top = []
    if user_id in blocked_users:
        top.append(InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock:{user_id}"))
    else:
        top.append(InlineKeyboardButton(text="🔒 Заблокировать", callback_data=f"block:{user_id}"))

    if read_status.get(user_id):
        top.append(InlineKeyboardButton(text="↩️ Отменить прочтение", callback_data=f"unread:{user_id}"))
    else:
        top.append(InlineKeyboardButton(text="✅ Прочитать", callback_data=f"read:{user_id}"))

    bottom = []
    if mode == "private":
        bottom.append(InlineKeyboardButton(text="💬 Переключить в тему", callback_data=f"switch_group:{user_id}"))
    elif mode == "group":
        bottom.append(InlineKeyboardButton(text="🤍 Переключить в ЛС", callback_data=f"switch_private:{user_id}"))
    else:
        bottom.append(InlineKeyboardButton(text="🤍 В ЛС бота", callback_data=f"switch_private:{user_id}"))
        bottom.append(InlineKeyboardButton(text="💬 В тему", callback_data=f"switch_group:{user_id}"))

    return InlineKeyboardMarkup(inline_keyboard=[top, bottom])


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
    uname = user_username.get(user_id)
    if uname:
        return f"@{uname} (<code>{user_id}</code>)"
    return f"<code>{user_id}</code>"


def remember_user(message: Message):
    uid = message.from_user.id
    all_users.add(uid)
    if message.from_user.username:
        user_username[uid] = message.from_user.username
    if message.from_user.first_name:
        user_first_name[uid] = message.from_user.first_name


def mode_label(mode: str) -> str:
    if mode == "group":
        return "💬 в теме группы"
    if mode == "private":
        return "🤍 в ЛС бота"
    if mode == "admin":
        return "🌙 админ выбирает"
    return "—"


def find_admin_for_category(cat_key: str):
    """Находит свободного админа, подходящего под категорию. Возвращает admin_id или None."""
    cat = CATEGORIES.get(cat_key)
    if not cat:
        return None
    candidates = []
    for admin_id in list(admin_tags.keys()):
        if admin_id not in admins and admin_id not in owners:
            continue
        role = admin_roles.get(admin_id, "").lower()
        if cat["role_key"] == "Мальчик" and "мальчик" not in role:
            continue
        if cat["role_key"] == "Девочка" and "девочка" not in role:
            continue
        candidates.append(admin_id)
    if not candidates:
        return None
    # Берём самого свободного (у кого меньше юзеров)
    candidates.sort(key=lambda a: len([u for u, ad in user_admin_map.items() if ad == a]))
    return candidates[0]


# ================== СОХРАНЕНИЕ ==================
async def load_data():
    global user_topics, topic_to_user, blocked_users, admins, owners, all_users
    global warns, mutes, admin_tags, admin_roles, read_status, chat_mode
    global user_admin_map, admin_user_map, user_username, user_first_name

    if JSONBLOB_URL:
        session = aiohttp.ClientSession()
        try:
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
        finally:
            await session.close()

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
    session = aiohttp.ClientSession()
    try:
        async with session.put(JSONBLOB_URL, json=data) as resp:
            _ = resp.status
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")
    finally:
        await session.close()


# ================== 1. ВЛАДЕЛЕЦ ==================
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
    for a in admins:
        lines.append(f"  {a} — {admin_tags.get(a, '—')} ({admin_roles.get(a, '—')})")
    await message.answer("\n".join(lines))


@dp.message(Command("users"), F.chat.type == "private")
async def cmd_users(message: Message):
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
        admin_id = user_admin_map.get(uid)
        admin_tag = admin_tags.get(admin_id, "—") if admin_id else "—"
        mode = mode_label(chat_mode.get(uid, "—"))
        status = "🔒" if uid in blocked_users else ("💬" if uid in user_topics else "⚪")
        lines.append(f"{status} <code>{uid}</code> | {uname_str} | {admin_tag} | {mode}")
    await message.answer("\n".join(lines))


# ================== 2. ПОЛЬЗОВАТЕЛЬ ==================
@dp.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    remember_user(message)
    await save_data()
    msg = await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    user_temp_messages.setdefault(user_id, []).append(msg.message_id)


@dp.message(Command("help"), F.chat.type == "private")
async def cmd_user_help(message: Message):
    await message.answer(
        "🤍 Что я умею:\n\n"
        "/rules — правила\n/status — статус\n/stop — завершить диалог\n"
        "/report — жалоба\n/myrank — мой ранг"
    )


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(RULES_TEXT)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    if user_id in user_topics:
        admin_id = user_admin_map.get(user_id)
        tag = admin_tags.get(admin_id, "—") if admin_id else "—"
        mode = mode_label(chat_mode.get(user_id, "—"))
        await message.answer(f"💬 Активный диалог.\nХранитель: <b>{tag}</b>\nРежим: {mode}")
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
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception:
            pass
        read_status.pop(user_id, None)
        chat_mode.pop(user_id, None)
        user_category.pop(user_id, None)
        admin_id = user_admin_map.pop(user_id, None)
        if admin_id:
            admin_user_map.pop(admin_id, None)
        await save_data()
        await message.answer(
            "Диалог завершён. Нажми «🤍 Позвать хранителя» или «🌸 Поболтать».",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer("У тебя нет активного диалога.")


# ================== 3. CALLBACK'И ==================
@dp.callback_query(F.data.startswith("pick_admin:"))
async def on_pick_admin(callback: CallbackQuery):
    try:
        admin_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    user_id = callback.from_user.id
    admin_tag = admin_tags.get(admin_id, "—")
    emoji = ADMIN_EMOJI.get(admin_id, "🛡️")

    if user_id in user_topics:
        await callback.answer(
            "У тебя уже есть хранитель. Напиши /stop, чтобы сменить.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        f"{emoji} Ты выбрал хранителя <b>{admin_tag}</b>.\n\n"
        f"Как хочешь общаться?",
        reply_markup=mode_choice_keyboard("admin", str(admin_id)),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pick_cat:"))
async def on_pick_category(callback: CallbackQuery):
    try:
        cat_key = callback.data.split(":")[1]
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    user_id = callback.from_user.id
    cat = CATEGORIES.get(cat_key)
    if not cat:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    if user_id in user_topics:
        await callback.answer(
            "У тебя уже есть хранитель. Напиши /stop, чтобы сменить.",
            show_alert=True,
        )
        return

    user_category[user_id] = cat_key
    await callback.message.edit_text(
        f"Ты выбрал категорию: <b>{cat['label']}</b>\n\n"
        f"Как хочешь общаться?",
        reply_markup=mode_choice_keyboard("cat", cat_key),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("mode_"))
async def on_mode_choice(callback: CallbackQuery):
    parts = callback.data.split(":")
    # mode_group:admin:12345  или  mode_group:cat:male_comm
    if len(parts) != 3:
        await callback.answer("Ошибка", show_alert=True)
        return
    mode_key, source, source_id = parts

    mode_map = {
        "mode_group": "group",
        "mode_private": "private",
        "mode_admin": "admin",
    }
    mode = mode_map.get(mode_key, "admin")

    user_id = callback.from_user.id
    username = user_username.get(user_id) or callback.from_user.username or f"id{user_id}"
    fname = user_first_name.get(user_id, "")

    if user_id in user_topics:
        await callback.answer("У тебя уже есть активный диалог.", show_alert=True)
        return

    # Определяем админа и текст темы
    if source == "admin":
        try:
            admin_id = int(source_id)
        except ValueError:
            await callback.answer("Ошибка", show_alert=True)
            return
        admin_tag = admin_tags.get(admin_id, "—")
        topic_suffix = admin_tag
        category_label = None
    else:  # cat
        cat = CATEGORIES.get(source_id)
        if not cat:
            await callback.answer("Ошибка", show_alert=True)
            return
        admin_id = find_admin_for_category(source_id)
        admin_tag = admin_tags.get(admin_id, "—") if admin_id else "—"
        topic_suffix = cat["label"]
        category_label = cat["label"]

    # Создаём тему В ЛЮБОМ СЛУЧАЕ
    topic_name = f"@{username} · {topic_suffix}"
    try:
        new_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name[:120])
        new_topic_id = new_topic.message_thread_id
    except Exception as e:
        logging.error(f"Не удалось создать тему: {e}")
        await callback.message.edit_text("⚠️ Не удалось создать диалог. Попробуй позже.")
        await callback.answer()
        return

    user_topics[user_id] = new_topic_id
    topic_to_user[new_topic_id] = user_id
    chat_mode[user_id] = mode
    read_status[user_id] = False
    if admin_id:
        user_admin_map[user_id] = admin_id
        admin_user_map[admin_id] = user_id
    await save_data()

    mode_str = mode_label(mode)
    cat_line = f"📂 Категория: <b>{category_label}</b>\n" if category_label else ""
    card = (
        f"👤 <b>Пользователь</b>\n"
        f"  ID: <code>{user_id}</code>\n"
        f"  Username: @{username}\n"
        f"  Имя: {fname}\n"
        f"{cat_line}"
        f"🎯 Хранитель: <b>{admin_tag}</b>\n"
        f"💬 Режим: <b>{mode_str}</b>"
    )
    try:
        sent = await bot.send_message(
            GROUP_ID, card, message_thread_id=new_topic_id,
            reply_markup=get_card_keyboard(user_id, mode),
        )
        card_texts[sent.message_id] = card
    except Exception as e:
        logging.error(f"Не удалось отправить карточку: {e}")

    # Ответ пользователю
    if mode == "private":
        await callback.message.edit_text(
            f"🤍 Тебя соединили с <b>{admin_tag}</b>.\n\n"
            f"Пиши сюда — сообщения уйдут хранителю лично."
        )
    elif mode == "group":
        await callback.message.edit_text(
            f"💬 Тебя соединили с <b>{admin_tag}</b>.\n\n"
            f"Пиши сюда — сообщения уйдут в тему группы."
        )
    else:
        await callback.message.edit_text(
            f"🌙 Ты в очереди к <b>{admin_tag}</b>.\n\n"
            f"Он сам выберет, как с тобой общаться."
        )
    await callback.answer()

    # Уведомление админу в ЛС бота
    if admin_id:
        notif = (
            f"🔔 <b>Новый пользователь!</b>\n"
            f"👤 @{username} (<code>{user_id}</code>)\n"
            f"📛 {fname}\n"
            + (f"📂 Категория: {category_label}\n" if category_label else "")
            + f"🎯 Тег: {admin_tag}\n"
            f"💬 Режим: <b>{mode_str}</b>"
        )
        try:
            notif_msg = await bot.send_message(admin_id, notif)
            private_admin_msg_to_user[(admin_id, notif_msg.message_id)] = user_id
        except Exception as e:
            logging.error(f"Не удалось уведомить админа {admin_id}: {e}")


@dp.callback_query(F.data.startswith("block:"))
async def on_block(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    blocked_users.add(user_id)
    await save_data()
    mode = chat_mode.get(user_id, "admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, mode))
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
    mode = chat_mode.get(user_id, "admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, mode))
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
    mode = chat_mode.get(user_id, "admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, mode))
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
    mode = chat_mode.get(user_id, "admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, mode))
    except Exception:
        pass
    await callback.answer("Отменено ↩️")


@dp.callback_query(F.data.startswith("switch_private:"))
async def on_switch_private(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    chat_mode[user_id] = "private"
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, "private"))
    except Exception:
        pass
    await callback.answer("🤍 Режим: ЛС бота")
    try:
        await bot.send_message(user_id, "💬 Хранитель переключил переписку в ЛС бота 🤍")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("switch_group:"))
async def on_switch_group(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return
    chat_mode[user_id] = "group"
    await save_data()
    try:
        await callback.message.edit_reply_markup(reply_markup=get_card_keyboard(user_id, "group"))
    except Exception:
        pass
    await callback.answer("💬 Режим: тема группы")
    try:
        await bot.send_message(user_id, "💬 Хранитель переключил переписку в тему группы.")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("rate_"))
async def on_rate(callback: CallbackQuery):
    val = callback.data.replace("rate_", "")
    await callback.message.edit_text(f"Спасибо за оценку: {val} 🌙")
    await callback.answer()


# ================== 4. ГРУППА ==================
@dp.message(Command("help"), F.chat.id == GROUP_ID)
async def cmd_help_group(message: Message):
    await message.answer(
        "/stats /id /rank /close /warn /mute /unmute /warns /greet /resetkb /who"
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
    uname = user_username.get(uid, "—")
    admin_id = user_admin_map.get(uid)
    admin_tag = admin_tags.get(admin_id, "—") if admin_id else "—"
    mode = mode_label(chat_mode.get(uid, "—"))
    await message.answer(
        f"👤 Пользователь:\n"
        f"  ID: <code>{uid}</code>\n"
        f"  Username: @{uname}\n"
        f"  Хранитель: {admin_tag}\n"
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
        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception:
            await message.answer("Не удалось.")
            return
        user_topics.pop(user_id, None)
        topic_to_user.pop(topic_id, None)
        read_status.pop(user_id, None)
        chat_mode.pop(user_id, None)
        user_category.pop(user_id, None)
        admin_id = user_admin_map.pop(user_id, None)
        if admin_id:
            admin_user_map.pop(admin_id, None)
        await save_data()
        await message.answer("Тема удалена.")
        try:
            await bot.send_message(user_id, "Оцените работу админа от 1 до 10:", reply_markup=rating_keyboard())
        except Exception:
            pass


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


# ================== 5. REPLY-КНОПКИ ==================
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
    if user_id in user_topics:
        admin_id = user_admin_map.get(user_id)
        tag = admin_tags.get(admin_id, "—") if admin_id else "—"
        await message.answer(
            f"У тебя уже есть хранитель <b>{tag}</b>.\n\nНапиши /stop, чтобы сменить."
        )
        return

    await message.answer("🤍 Выбери хранителя 👇", reply_markup=admins_keyboard())


@dp.message(F.chat.type == "private", F.text == "🌸 Поболтать")
async def btn_small_talk(message: Message, state: FSMContext):
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
    if user_id in user_topics:
        admin_id = user_admin_map.get(user_id)
        tag = admin_tags.get(admin_id, "—") if admin_id else "—"
        await message.answer(
            f"У тебя уже есть хранитель <b>{tag}</b>.\n\nНапиши /stop, чтобы сменить."
        )
        return

    await message.answer("🌸 Выбери категорию 👇", reply_markup=categories_keyboard())


@dp.message(F.chat.type == "private", F.text == "📜 Правила")
async def btn_rules(message: Message):
    await message.answer(RULES_TEXT)


# ================== 6. ЛИЧКА ==================
@dp.message(F.chat.type == "private")
async def handle_private(message: Message, state: FSMContext):
    user_id = message.from_user.id
    remember_user(message)

    # ==== АДМИН ====
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
                    logging.error(f"Ошибка пересылки: {e}")
                    await message.answer("⚠️ Не удалось отправить.")
                return
        await message.answer(
            "⚠️ Чтобы ответить пользователю — сделай reply на его сообщение."
        )
        return

    # ==== ПОЛЬЗОВАТЕЛЬ ====
    if user_id in blocked_users:
        await message.answer("🚫 Ты заблокирован.")
        return
    if user_id in mutes and mutes[user_id] > datetime.now():
        await message.answer(f"🔇 Мут до {mutes[user_id].strftime('%H:%M')}")
        return

    if user_id not in user_topics:
        await message.answer(
            "Привет! Нажми «🤍 Позвать хранителя» или «🌸 Поболтать».",
            reply_markup=main_menu_keyboard(),
        )
        await save_data()
        return

    topic_id = user_topics.get(user_id)
    admin_id = user_admin_map.get(user_id)
    mode = chat_mode.get(user_id, "admin")

    if mode == "group" and topic_id:
        try:
            sent = await message.forward(chat_id=GROUP_ID, message_thread_id=topic_id)
            admin_msg_to_user[(bot.id, sent.message_id)] = user_id
        except Exception as e:
            logging.error(f"Не удалось переслать в тему: {e}")

    if mode in ("private", "admin") and admin_id:
        try:
            forwarded = await message.forward(admin_id)
            private_admin_msg_to_user[(admin_id, forwarded.message_id)] = user_id
        except Exception as e:
            logging.error(f"Не удалось переслать админу {admin_id}: {e}")

    await save_data()


# ================== 7. ГРУППА ==================
@dp.message(F.chat.id == GROUP_ID)
async def handle_group(message: Message):
    if message.from_user.id not in admins and message.from_user.id not in owners:
        return

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

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await bot.session.close()
        await runner.cleanup()
        logging.info("🔒 Сессии закрыты.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("👋 Бот остановлен.")
