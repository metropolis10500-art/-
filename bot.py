
import logging
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, BotCommand,
    InputMediaPhoto, CallbackQuery, Message,
    MenuButtonCommands
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
ADMIN_ID = 5494544187
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"

# Настройки премиума
PREMIUM_PRICES = {
    "week": {"price": 199, "days": 7, "name": "Неделя", "emoji": "📅"},
    "month": {"price": 499, "days": 30, "name": "Месяц", "emoji": "🌙"},
    "quarter": {"price": 1299, "days": 90, "name": "3 месяца", "emoji": "⭐"},
    "half_year": {"price": 1999, "days": 180, "name": "6 месяцев", "emoji": "💎"},
    "year": {"price": 3499, "days": 365, "name": "Год", "emoji": "👑"},
}

# Лимиты
FREE_LIMITS = {
    "daily_likes": 10,
    "daily_messages": 5,
    "profile_photos": 3,
    "search_radius": 50,
    "can_see_likes": False,
    "can_use_filters": False,
    "can_boost": False,
}

PREMIUM_LIMITS = {
    "daily_likes": 999999,
    "daily_messages": 999999,
    "profile_photos": 10,
    "search_radius": 500,
    "can_see_likes": True,
    "can_use_filters": True,
    "can_boost": True,
}

# Города России + ДНР/ЛНР
CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Красноярск", "Челябинск", "Самара", "Уфа",
    "Ростов-на-Дону", "Омск", "Краснодар", "Воронеж", "Волгоград",
    "Пермь", "Тюмень", "Тольятти", "Ижевск", "Барнаул",
    "Ульяновск", "Иркутск", "Хабаровск", "Ярославль", "Владивосток",
    "Махачкала", "Томск", "Оренбург", "Кемерово", "Новокузнецк",
    "Рязань", "Набережные Челны", "Астрахань", "Пенза", "Киров",
    "Липецк", "Балашиха", "Чебоксары", "Калининград", "Тула",
    "Курск", "Ставрополь", "Сочи", "Севастополь", "Симферополь",
    "Донецк (ДНР)", "Макеевка (ДНР)", "Горловка (ДНР)", "Мариуполь (ДНР)",
    "Луганск (ЛНР)", "Алчевск (ЛНР)", "Северодонецк (ЛНР)", "Лисичанск (ЛНР)",
]

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БОТ И ДИСПЕТЧЕР ==========
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ========== БАЗА ДАННЫХ (В ПАМЯТИ) ==========
users_db: Dict[int, dict] = {}
profiles_db: Dict[int, dict] = {}
likes_db: Dict[int, List[int]] = {}
matches_db: Dict[int, List[int]] = {}
reports_db: Dict[int, List[dict]] = {}
pending_payments: Dict[str, dict] = {}
user_current_view: Dict[int, int] = {}

# ========== FSM СОСТОЯНИЯ ==========
class Registration(StatesGroup):
    name = State()
    age = State()
    gender = State()
    looking_for = State()
    city = State()
    bio = State()
    photo = State()
    confirm = State()

class EditProfile(StatesGroup):
    field = State()
    value = State()

class AdminStates(StatesGroup):
    broadcast = State()
    user_id_check = State()

class ReportState(StatesGroup):
    reason = State()

class MessageState(StatesGroup):
    target_id = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(user_id: int) -> dict:
    if user_id not in users_db:
        users_db[user_id] = {
            "id": user_id,
            "registered": False,
            "premium_until": None,
            "daily_likes": 0,
            "daily_messages": 0,
            "last_reset": datetime.now().date(),
            "banned": False,
            "created_at": datetime.now(),
            "notifications": True,
        }
    return users_db[user_id]

def get_profile(user_id: int) -> Optional[dict]:
    return profiles_db.get(user_id)

def is_premium(user_id: int) -> bool:
    user = get_user(user_id)
    if user.get("premium_until"):
        return datetime.now() < user["premium_until"]
    return False

def get_limits(user_id: int) -> dict:
    if is_premium(user_id):
        return PREMIUM_LIMITS
    return FREE_LIMITS

def reset_daily_limits(user_id: int):
    user = get_user(user_id)
    today = datetime.now().date()
    if user.get("last_reset") != today:
        user["daily_likes"] = 0
        user["daily_messages"] = 0
        user["last_reset"] = today

def format_age(age: int) -> str:
    if age % 10 == 1 and age % 100 != 11:
        return str(age) + " год"
    elif 2 <= age % 10 <= 4 and not (12 <= age % 100 <= 14):
        return str(age) + " года"
    else:
        return str(age) + " лет"

def generate_profile_text(profile: dict, user_id: int) -> str:
    gender_emoji = {"male": "👨", "female": "👩", "other": "🌈"}.get(profile.get("gender", ""), "👤")
    looking_map = {"male": "мужчин", "female": "женщин", "all": "всех"}
    looking_emoji = {"male": "👨", "female": "👩", "all": "💕"}.get(profile.get("looking_for", ""), "💕")
    premium_badge = "\n💎 <b>ПРЕМИУМ ПОЛЬЗОВАТЕЛЬ</b>" if is_premium(user_id) else ""

    text = gender_emoji + " <b>" + profile.get("name", "Неизвестно") + "</b>, " + format_age(profile.get("age", 0)) + "\n"
    text += "📍 " + profile.get("city", "Не указан") + "\n"
    text += "🔍 Ищу: " + looking_emoji + " " + looking_map.get(profile.get("looking_for", "all"), "всех") + premium_badge + "\n\n"
    text += "📝 О себе:\n"
    text += "<i>" + profile.get("bio", "Нет описания") + "</i>\n\n"
    text += "✨ Анкета создана: " + profile.get("created_at", "недавно")
    return text

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    is_premium_user = is_premium(user_id)
    if is_premium_user:
        premium_btn = "👑 Мой премиум"
    else:
        premium_btn = "💎 Премиум"

    kb = [
        [KeyboardButton(text="🔍 Смотреть анкеты")],
        [KeyboardButton(text="❤️ Мои лайки"), KeyboardButton(text="💬 Мои чаты")],
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="✏️ Редактировать")],
        [KeyboardButton(text=premium_btn)],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_inline_profile_actions(target_id: int, has_liked: bool = False) -> InlineKeyboardMarkup:
    if has_liked:
        like_btn = InlineKeyboardButton(text="💔 Убрать лайк", callback_data="unlike_" + str(target_id))
    else:
        like_btn = InlineKeyboardButton(text="❤️ Лайк", callback_data="like_" + str(target_id))

    buttons = [
        [like_btn, InlineKeyboardButton(text="💌 Написать", callback_data="message_" + str(target_id))],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data="skip_" + str(target_id)),
         InlineKeyboardButton(text="🚫 Жалоба", callback_data="report_" + str(target_id))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_compatible_profiles(user_id: int) -> List[tuple]:
    profile = get_profile(user_id)
    if not profile:
        return []

    candidates = []
    for uid, p in profiles_db.items():
        if uid == user_id:
            continue
        if not p.get("active", True):
            continue
        if p.get("banned", False):
            continue
        if profile.get("looking_for") != "all" and p.get("gender") != profile.get("looking_for"):
            continue
        if p.get("looking_for") != "all" and profile.get("gender") != p.get("looking_for"):
            continue
        candidates.append((uid, p))

    random.shuffle(candidates)
    return candidates

async def show_next_profile(user_id: int, message: Message):
    candidates = get_compatible_profiles(user_id)
    if not candidates:
        await message.answer(
            "😔 Пока нет подходящих анкет. Попробуй позже или расширь критерии поиска!\n\n"
            "💡 Совет: оформи премиум для поиска в радиусе 500 км!",
            reply_markup=get_main_menu(user_id)
        )
        return

    target_id, target_profile = candidates[0]
    user_current_view[user_id] = target_id

    text = generate_profile_text(target_profile, target_id)
    has_liked = user_id in likes_db.get(target_id, [])

    if target_profile.get("photos"):
        await message.answer_photo(
            photo=target_profile["photos"][0],
            caption=text,
            reply_markup=get_inline_profile_actions(target_id, has_liked)
        )
    else:
        await message.answer(
            text,
            reply_markup=get_inline_profile_actions(target_id, has_liked)
        )

# ========== YOOMONEY API ==========
async def check_yoomoney_payment(label: str) -> Optional[dict]:
    url = "https://yoomoney.ru/api/operation-history"
    headers = {
        "Authorization": "Bearer " + YOOMONEY_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "type": "deposition",
        "label": label,
        "details": "true"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    operations = result.get("operations", [])
                    if operations:
                        op = operations[0]
                        if op.get("status") == "success":
                            return {
                                "success": True,
                                "amount": op.get("amount", 0),
                                "operation_id": op.get("operation_id"),
                            }
    except Exception as e:
        logger.error("YooMoney API error: " + str(e))

    return None

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = get_user(user_id)

    if user["registered"] and get_profile(user_id):
        await message.answer(
            "👋 С возвращением в LoveSpark!\n\n"
            "Что будем делать сегодня?",
            reply_markup=get_main_menu(user_id)
        )
        return

    welcome_text = "✨ <b>Добро пожаловать в LoveSpark!</b> ✨\n\n"
    welcome_text += "🔥 <b>Лучший бот знакомств для всей России!</b>\n\n"
    welcome_text += "❤️ Находи свою половинку среди тысяч пользователей\n"
    welcome_text += "💬 Общайся без ограничений с премиумом\n"
    welcome_text += "🎯 Умные фильтры поиска по городу и интересам\n"
    welcome_text += "🔒 Полная безопасность и анонимность\n\n"
    welcome_text += "<i>Знакомства в Москве, Санкт-Петербурге, Донецке, Луганске и во всех городах России!</i>\n\n"
    welcome_text += "<b>Нажми кнопку ниже, чтобы начать регистрацию анкеты 👇</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Создать анкету", callback_data="start_reg")],
        [InlineKeyboardButton(text="📖 Как это работает", callback_data="how_it_works")],
        [InlineKeyboardButton(text="💎 Тарифы премиум", callback_data="premium_info")],
    ])

    await message.answer(welcome_text, reply_markup=kb)

@dp.callback_query(F.data == "start_reg")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(
        "🌟 <b>Начинаем создание твоей анкеты!</b>\n\n"
        "Как тебя зовут? (напиши свое имя)",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.name)
    await callback.answer()

@dp.message(Registration.name)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("❌ Имя должно быть от 2 до 30 символов. Попробуй еще раз:")
        return
    await state.update_data(name=name)
    await message.answer("🎂 Сколько тебе лет? (напиши число)")
    await state.set_state(Registration.age)

@dp.message(Registration.age)
async def reg_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 16 or age > 100:
            await message.answer("❌ Возраст должен быть от 16 до 100 лет. Попробуй еще раз:")
            return
    except ValueError:
        await message.answer("❌ Напиши число, например: 25")
        return

    await state.update_data(age=age)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужчина", callback_data="gender_male")],
        [InlineKeyboardButton(text="👩 Женщина", callback_data="gender_female")],
        [InlineKeyboardButton(text="🌈 Другой", callback_data="gender_other")],
    ])
    await message.answer("👤 Какой твой пол?", reply_markup=kb)
    await state.set_state(Registration.gender)

@dp.callback_query(F.data.startswith("gender_"))
async def reg_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split("_")[1]
    await state.update_data(gender=gender)

    looking_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужчин", callback_data="looking_male")],
        [InlineKeyboardButton(text="👩 Женщин", callback_data="looking_female")],
        [InlineKeyboardButton(text="💕 Всех", callback_data="looking_all")],
    ])

    await callback.message.edit_text("🔍 Кого ты ищешь?", reply_markup=looking_kb)
    await state.set_state(Registration.looking_for)
    await callback.answer()

@dp.callback_query(F.data.startswith("looking_"))
async def reg_looking(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.split("_")[1]
    looking_map = {"male": "мужчин", "female": "женщин", "all": "всех"}
    await state.update_data(looking_for=looking, looking_for_text=looking_map[looking])

    cities_text = "📍 Напиши название своего города:\n\n"
    cities_text += "<i>Например: Москва, Санкт-Петербург, Донецк, Луганск...</i>"

    await callback.message.delete()
    await callback.message.answer(cities_text)
    await state.set_state(Registration.city)
    await callback.answer()

@dp.message(Registration.city)
async def reg_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        await message.answer("❌ Название города слишком короткое или длинное. Попробуй еще раз:")
        return

    await state.update_data(city=city)
    await message.answer(
        "📝 Расскажи немного о себе (хобби, интересы, что ищешь):\n"
        "<i>Минимум 10 символов, максимум 500</i>"
    )
    await state.set_state(Registration.bio)

@dp.message(Registration.bio)
async def reg_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10:
        await message.answer("❌ Описание слишком короткое. Расскажи о себе подробнее:")
        return
    if len(bio) > 500:
        await message.answer("❌ Описание слишком длинное (максимум 500 символов). Сократи:")
        return

    await state.update_data(bio=bio)
    await message.answer(
        "📸 Отправь свое фото для анкеты:\n\n"
        "<i>Желательно хорошее качество, где видно лицо 😊</i>\n"
        "<i>Можно отправить несколько фото (до 3 для бесплатных, до 10 для премиум)</i>"
    )
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    photos = message.photo
    photo_file_id = photos[-1].file_id

    data = await state.get_data()
    photos_list = data.get("photos", [])
    photos_list.append(photo_file_id)
    await state.update_data(photos=photos_list)

    limits = get_limits(message.from_user.id)
    max_photos = limits["profile_photos"]

    if len(photos_list) < max_photos:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Это все, продолжить", callback_data="photos_done")],
            [InlineKeyboardButton(text="📸 Добавить еще фото", callback_data="more_photos")],
        ])
        await message.answer(
            "📷 Фото " + str(len(photos_list)) + " добавлено (макс " + str(max_photos) + "). Хочешь добавить еще?",
            reply_markup=kb
        )
    else:
        await finish_registration(message, state)

@dp.callback_query(F.data == "more_photos")
async def more_photos(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📸 Отправь еще фото:")
    await callback.answer()

@dp.callback_query(F.data == "photos_done")
async def photos_done(callback: CallbackQuery, state: FSMContext):
    await finish_registration(callback.message, state)
    await callback.answer()

async def finish_registration(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id

    profile = {
        "user_id": user_id,
        "name": data["name"],
        "age": data["age"],
        "gender": data["gender"],
        "looking_for": data["looking_for"],
        "looking_for_text": data["looking_for_text"],
        "city": data["city"],
        "bio": data["bio"],
        "photos": data.get("photos", []),
        "created_at": datetime.now().strftime("%d.%m.%Y"),
        "active": True,
    }

    profiles_db[user_id] = profile
    users_db[user_id]["registered"] = True

    await state.clear()

    profile_text = generate_profile_text(profile, user_id)

    if profile["photos"]:
        await message.answer_photo(
            photo=profile["photos"][0],
            caption=profile_text,
            reply_markup=get_main_menu(user_id)
        )
    else:
        await message.answer(profile_text, reply_markup=get_main_menu(user_id))

    welcome_msg = "🎉 <b>Анкета создана!</b>\n\n"
    welcome_msg += "Теперь ты можешь:\n"
    welcome_msg += "🔍 <b>Смотреть анкеты</b> — найди интересных людей\n"
    welcome_msg += "❤️ <b>Ставить лайки</b> — покажи симпатию\n"
    welcome_msg += "💬 <b>Общаться</b> — при взаимном интересе\n\n"
    welcome_msg += "<i>💡 Совет: оформи премиум, чтобы снять все ограничения!</i>"
    await message.answer(welcome_msg)

# ========== ГЛАВНОЕ МЕНЮ ==========
@dp.message(F.text == "🔍 Смотреть анкеты")
async def browse_profiles(message: Message):
    user_id = message.from_user.id
    reset_daily_limits(user_id)

    profile = get_profile(user_id)
    if not profile:
        await message.answer("❌ Сначала создай анкету! Напиши /start")
        return

    await show_next_profile(user_id, message)

@dp.callback_query(F.data.startswith("like_"))
async def like_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    reset_daily_limits(user_id)
    limits = get_limits(user_id)
    user = get_user(user_id)

    if user["daily_likes"] >= limits["daily_likes"]:
        await callback.answer("❌ Лимит лайков на сегодня исчерпан! Оформи премиум 💎", show_alert=True)
        return

    if target_id not in likes_db:
        likes_db[target_id] = []

    if user_id not in likes_db[target_id]:
        likes_db[target_id].append(user_id)
        user["daily_likes"] += 1

    # Проверяем взаимный лайк
    if target_id in likes_db.get(user_id, []):
        if user_id not in matches_db.get(target_id, []):
            if target_id not in matches_db:
                matches_db[target_id] = []
            if user_id not in matches_db:
                matches_db[user_id] = []
            matches_db[target_id].append(user_id)
            matches_db[user_id].append(target_id)

            target_profile = get_profile(user_id)
            if target_profile:
                await bot.send_message(
                    target_id,
                    "🎉 <b>Взаимная симпатия!</b>\n\n"
                    "❤️ Тебе понравился(ась) <b>" + target_profile["name"] + "</b>, " + str(target_profile["age"]) + "!\n"
                    "💬 Начни общение — нажми на кнопку ниже!",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💌 Написать", callback_data="message_" + str(user_id))]
                    ])
                )

        await callback.answer("🎉 Взаимная симпатия!")
    else:
        await callback.answer("❤️ Лайк отправлен!")

    await callback.message.edit_reply_markup(
        reply_markup=get_inline_profile_actions(target_id, True)
    )

@dp.callback_query(F.data.startswith("unlike_"))
async def unlike_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    if target_id in likes_db and user_id in likes_db[target_id]:
        likes_db[target_id].remove(user_id)

    await callback.answer("💔 Лайк убран")
    await callback.message.edit_reply_markup(
        reply_markup=get_inline_profile_actions(target_id, False)
    )

@dp.callback_query(F.data.startswith("message_"))
async def send_message_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    if not is_premium(user_id):
        has_match = target_id in matches_db.get(user_id, [])
        if not has_match:
            await callback.answer(
                "💎 Нужен премиум или взаимный лайк для отправки сообщений!",
                show_alert=True
            )
            return

    await state.update_data(message_target=target_id)
    target_profile = get_profile(target_id)
    name = target_profile["name"] if target_profile else "пользователю"

    await callback.message.answer(
        "💌 Напиши сообщение для <b>" + name + "</b>:\n"
        "<i>Он(а) получит его сразу!</i>"
    )
    await state.set_state(MessageState.target_id)
    await callback.answer()

@dp.message(MessageState.target_id)
async def send_direct_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("message_target")

    if not target_id:
        await state.clear()
        return

    user_id = message.from_user.id
    reset_daily_limits(user_id)
    limits = get_limits(user_id)
    user = get_user(user_id)

    if not is_premium(user_id):
        if user["daily_messages"] >= limits["daily_messages"]:
            await message.answer(
                "❌ Лимит сообщений на сегодня исчерпан!\n"
                "💎 Оформи премиум для безлимитных сообщений!"
            )
            await state.clear()
            return
        user["daily_messages"] += 1

    my_profile = get_profile(user_id)
    sender_name = my_profile["name"] if my_profile else "Аноним"

    await bot.send_message(
        target_id,
        "💌 <b>Новое сообщение от " + sender_name + ":</b>\n\n"
        + message.text + "\n\n"
        + "<i>Ответь через бота — нажми кнопку ниже 👇</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💌 Ответить", callback_data="message_" + str(user_id))]
        ])
    )

    await message.answer("✅ Сообщение отправлено!")
    await state.clear()

@dp.callback_query(F.data.startswith("skip_"))
async def skip_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.delete()
    await callback.answer("👎 Пропущено")
    await show_next_profile(user_id, callback.message)

@dp.callback_query(F.data.startswith("report_"))
async def report_profile(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target=target_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Фейк/обман", callback_data="report_fake")],
        [InlineKeyboardButton(text="🔞 Неприемлемый контент", callback_data="report_inappropriate")],
        [InlineKeyboardButton(text="💢 Оскорбления", callback_data="report_harass")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="report_cancel")],
    ])

    await callback.message.edit_text("🚫 Выбери причину жалобы:", reply_markup=kb)
    await state.set_state(ReportState.reason)
    await callback.answer()

@dp.callback_query(F.data.startswith("report_"), ReportState.reason)
async def report_reason(callback: CallbackQuery, state: FSMContext):
    if callback.data == "report_cancel":
        await state.clear()
        await callback.message.edit_text("❌ Жалоба отменена")
        await callback.answer()
        return

    data = await state.get_data()
    target_id = data.get("report_target")
    reason = callback.data.replace("report_", "")

    if target_id not in reports_db:
        reports_db[target_id] = []

    reports_db[target_id].append({
        "from": callback.from_user.id,
        "reason": reason,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    await bot.send_message(
        ADMIN_ID,
        "🚫 <b>Новая жалоба!</b>\n\n"
        "От: " + str(callback.from_user.id) + "\n"
        "На: " + str(target_id) + "\n"
        "Причина: " + reason + "\n"
        "Всего жалоб: " + str(len(reports_db[target_id]))
    )

    await callback.message.edit_text("✅ Жалоба отправлена администратору. Спасибо!")
    await state.clear()
    await callback.answer()

# ========== ПРЕМИУМ ==========
@dp.message(F.text.in_(["💎 Премиум", "👑 Мой премиум"]))
async def premium_menu(message: Message):
    user_id = message.from_user.id

    if is_premium(user_id):
        premium_until = users_db[user_id]["premium_until"]
        await message.answer(
            "👑 <b>Твой премиум активен!</b>\n\n"
            "💎 Действует до: " + premium_until.strftime("%d.%m.%Y") + "\n\n"
            "✅ Безлимитные лайки\n"
            "✅ Безлимитные сообщения\n"
            "✅ Видеть, кто тебя лайкнул\n"
            "✅ Расширенные фильтры\n"
            "✅ До 10 фото в анкете\n"
            "✅ Радиус поиска 500 км\n\n"
            "🎉 Наслаждайся общением!",
            reply_markup=get_main_menu(user_id)
        )
        return

    text = "💎 <b>LoveSpark Премиум</b> 💎\n\n"
    text += "<b>Что ты получаешь:</b>\n"
    text += "✅ Безлимитные лайки ❤️\n"
    text += "✅ Безлимитные сообщения 💬\n"
    text += "✅ Видеть, кто тебя лайкнул 👀\n"
    text += "✅ Расширенные фильтры поиска 🔍\n"
    text += "✅ До 10 фото в анкете 📸\n"
    text += "✅ Радиус поиска 500 км 🌍\n"
    text += "✅ Буст анкеты (показывайся первым) 🚀\n"
    text += "✅ Значок премиум в анкете 💎\n\n"
    text += "<b>Тарифы:</b>\n"

    for key, plan in PREMIUM_PRICES.items():
        text += plan["emoji"] + " <b>" + plan["name"] + "</b> — " + str(plan["price"]) + "₽\n"

    text += "\n<i>💡 Чем дольше подписка, тем выгоднее!</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Неделя — 199₽", callback_data="buy_week")],
        [InlineKeyboardButton(text="🌙 Месяц — 499₽", callback_data="buy_month")],
        [InlineKeyboardButton(text="⭐ 3 месяца — 1299₽", callback_data="buy_quarter")],
        [InlineKeyboardButton(text="💎 6 месяцев — 1999₽", callback_data="buy_half_year")],
        [InlineKeyboardButton(text="👑 Год — 3499₽", callback_data="buy_year")],
    ])

    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_premium(callback: CallbackQuery):
    plan_key = callback.data.split("_")[1]
    plan = PREMIUM_PRICES.get(plan_key)

    if not plan:
        await callback.answer("❌ Ошибка", show_alert=True)
        return

    payment_id = "LS_" + str(callback.from_user.id) + "_" + plan_key + "_" + str(int(datetime.now().timestamp()))

    pending_payments[payment_id] = {
        "user_id": callback.from_user.id,
        "plan_key": plan_key,
        "amount": plan["price"],
        "created": datetime.now(),
    }

    yoomoney_url = (
        "https://yoomoney.ru/quickpay/confirm?"
        "receiver=" + YOOMONEY_WALLET + "&"
        "quickpay-form=button&"
        "paymentType=AC&"
        "sum=" + str(plan["price"]) + "&"
        "label=" + payment_id + "&"
        "successURL=https://t.me/LoveSparkBot"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить " + str(plan["price"]) + "₽", url=yoomoney_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="check_" + payment_id)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="premium_info")],
    ])

    await callback.message.edit_text(
        "💎 <b>Оформление премиума: " + plan["name"] + "</b>\n\n"
        "Сумма: <b>" + str(plan["price"]) + "₽</b>\n"
        "Срок: " + str(plan["days"]) + " дней\n\n"
        "1️⃣ Нажми «Оплатить» и соверши платеж через ЮMoney\n"
        "2️⃣ После оплаты нажми «Я оплатил»\n\n"
        "<i>Средства поступят мгновенно!</i>",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.split("check_")[1]
    payment = pending_payments.get(payment_id)

    if not payment:
        await callback.answer("❌ Платеж не найден", show_alert=True)
        return

    result = await check_yoomoney_payment(payment_id)

    if result and result["success"]:
        plan_key = payment["plan_key"]
        plan = PREMIUM_PRICES[plan_key]
        user_id = payment["user_id"]

        premium_until = datetime.now() + timedelta(days=plan["days"])
        users_db[user_id]["premium_until"] = premium_until

        del pending_payments[payment_id]

        await callback.message.edit_text(
            "🎉 <b>Премиум активирован!</b>\n\n"
            "💎 Тариф: " + plan["name"] + "\n"
            "📅 Действует до: " + premium_until.strftime("%d.%m.%Y") + "\n\n"
            "✅ Все ограничения сняты!\n"
            "🎉 Наслаждайся общением! ❤️"
        )

        await bot.send_message(
            ADMIN_ID,
            "💰 <b>Новая оплата!</b>\n\n"
            "Пользователь: " + str(user_id) + "\n"
            "Тариф: " + plan["name"] + "\n"
            "Сумма: " + str(plan["price"]) + "₽"
        )
    else:
        await callback.answer(
            "⏳ Платеж еще не поступил. Попробуй через минуту!",
            show_alert=True
        )

# ========== МОЯ АНКЕТА ==========
@dp.message(F.text == "👤 Моя анкета")
async def my_profile(message: Message):
    user_id = message.from_user.id
    profile = get_profile(user_id)

    if not profile:
        await message.answer("❌ У тебя нет анкеты. Напиши /start")
        return

    text = generate_profile_text(profile, user_id)

    if profile.get("photos"):
        await message.answer_photo(
            photo=profile["photos"][0],
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📸 Все фото", callback_data="view_all_photos")],
            ])
        )
    else:
        await message.answer(text)

@dp.callback_query(F.data == "view_all_photos")
async def view_all_photos(callback: CallbackQuery):
    user_id = callback.from_user.id
    profile = get_profile(user_id)

    if not profile or not profile.get("photos"):
        await callback.answer("❌ Нет фото", show_alert=True)
        return

    media = []
    for i, photo in enumerate(profile["photos"]):
        if i == 0:
            media.append(InputMediaPhoto(media=photo, caption="📸 Фото " + str(i+1) + "/" + str(len(profile["photos"]))))
        else:
            media.append(InputMediaPhoto(media=photo))

    await callback.message.answer_media_group(media=media)
    await callback.answer()

# ========== РЕДАКТИРОВАНИЕ ==========
@dp.message(F.text == "✏️ Редактировать")
async def edit_profile_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name")],
        [InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
        [InlineKeyboardButton(text="📍 Город", callback_data="edit_city")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio")],
        [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photos")],
        [InlineKeyboardButton(text="🔍 Кого ищу", callback_data="edit_looking")],
    ])
    await message.answer("✏️ Что хочешь изменить?", reply_markup=kb)

@dp.callback_query(F.data.startswith("edit_"))
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    await state.update_data(edit_field=field)

    field_names = {
        "name": "имя",
        "age": "возраст",
        "city": "город",
        "bio": "описание",
        "photos": "фото",
        "looking": "предпочтения в поиске"
    }

    if field == "photos":
        await callback.message.edit_text(
            "📸 Отправь новое фото:\n\n"
            "<i>Текущие фото будут заменены</i>"
        )
    elif field == "looking":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨 Мужчин", callback_data="editlooking_male")],
            [InlineKeyboardButton(text="👩 Женщин", callback_data="editlooking_female")],
            [InlineKeyboardButton(text="💕 Всех", callback_data="editlooking_all")],
        ])
        await callback.message.edit_text("🔍 Кого ищешь?", reply_markup=kb)
        return
    else:
        await callback.message.edit_text("✏️ Введи новое " + field_names.get(field, "значение") + ":")

    await state.set_state(EditProfile.value)
    await callback.answer()

@dp.message(EditProfile.value)
async def edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    user_id = message.from_user.id

    if not field or user_id not in profiles_db:
        await state.clear()
        return

    value = message.text.strip()

    if field == "name":
        if len(value) < 2 or len(value) > 30:
            await message.answer("❌ Имя должно быть от 2 до 30 символов")
            return
        profiles_db[user_id]["name"] = value
    elif field == "age":
        try:
            age = int(value)
            if age < 16 or age > 100:
                await message.answer("❌ Возраст от 16 до 100")
                return
            profiles_db[user_id]["age"] = age
        except ValueError:
            await message.answer("❌ Напиши число")
            return
    elif field == "city":
        if len(value) < 2 or len(value) > 50:
            await message.answer("❌ Слишком короткое или длинное название")
            return
        profiles_db[user_id]["city"] = value
    elif field == "bio":
        if len(value) < 10 or len(value) > 500:
            await message.answer("❌ От 10 до 500 символов")
            return
        profiles_db[user_id]["bio"] = value

    await message.answer("✅ Изменения сохранены!")
    await state.clear()

@dp.callback_query(F.data.startswith("editlooking_"))
async def edit_looking(callback: CallbackQuery):
    looking = callback.data.split("_")[1]
    user_id = callback.from_user.id
    looking_map = {"male": "мужчин", "female": "женщин", "all": "всех"}

    if user_id in profiles_db:
        profiles_db[user_id]["looking_for"] = looking
        profiles_db[user_id]["looking_for_text"] = looking_map[looking]

    await callback.message.edit_text("✅ Предпочтения обновлены!")
    await callback.answer()

# ========== ЛАЙКИ ==========
@dp.message(F.text == "❤️ Мои лайки")
async def my_likes(message: Message):
    user_id = message.from_user.id
    likes = likes_db.get(user_id, [])

    if not likes:
        await message.answer(
            "😔 Пока никто не лайкнул тебя.\n\n"
            "Скоро обязательно кто-то появится! ❤️\n\n"
            "💡 Совет: активнее ставь лайки другим — это увеличит твою видимость!"
        )
        return

    limits = get_limits(user_id)
    if not limits["can_see_likes"]:
        await message.answer(
            "💎 <b>Функция доступна только для премиум-пользователей!</b>\n\n"
            "Оформи премиум, чтобы увидеть, кто тебя лайкнул 👀",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Оформить премиум", callback_data="premium_info")]
            ])
        )
        return

    text = "❤️ <b>Тебя лайкнули (" + str(len(likes)) + "):</b>\n\n"
    for liker_id in likes[:20]:
        p = get_profile(liker_id)
        if p:
            text += "• " + p["name"] + ", " + str(p["age"]) + " — " + p["city"] + "\n"

    if len(likes) > 20:
        text += "\n...и еще " + str(len(likes) - 20) + " человек"

    await message.answer(text)

# ========== ЧАТЫ ==========
@dp.message(F.text == "💬 Мои чаты")
async def my_chats(message: Message):
    user_id = message.from_user.id
    matches = matches_db.get(user_id, [])

    if not matches:
        await message.answer(
            "💬 <b>Пока нет взаимных симпатий.</b>\n\n"
            "Ставь лайки анкетам, и когда кто-то ответит взаимностью, вы сможете общаться! ❤️"
        )
        return

    text = "💕 <b>Взаимные симпатии:</b>\n\n"
    kb_buttons = []
    for match_id in matches:
        p = get_profile(match_id)
        if p:
            text += "• " + p["name"] + ", " + str(p["age"]) + " — " + p["city"] + "\n"
            kb_buttons.append([InlineKeyboardButton(
                text="💌 Написать " + p["name"],
                callback_data="message_" + str(match_id)
            )])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

# ========== НАСТРОЙКИ ==========
@dp.message(F.text == "⚙️ Настройки")
async def settings(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔕 Вкл/выкл уведомления", callback_data="toggle_notif")],
        [InlineKeyboardButton(text="🚫 Удалить анкету", callback_data="delete_profile")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
    ])
    await message.answer("⚙️ Настройки:", reply_markup=kb)

@dp.callback_query(F.data == "toggle_notif")
async def toggle_notif(callback: CallbackQuery):
    user_id = callback.from_user.id
    users_db[user_id]["notifications"] = not users_db[user_id].get("notifications", True)
    status = "включены" if users_db[user_id]["notifications"] else "выключены"
    await callback.answer("🔔 Уведомления " + status + "!")

@dp.callback_query(F.data == "delete_profile")
async def delete_profile(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")],
    ])
    await callback.message.edit_text(
        "🚫 <b>Ты уверен, что хочешь удалить анкету?</b>\n\n"
        "Все данные будут безвозвратно удалены!",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in profiles_db:
        del profiles_db[user_id]
    users_db[user_id]["registered"] = False

    await callback.message.edit_text(
        "😢 <b>Анкета удалена.</b>\n\n"
        "Если передумаешь — всегда можешь создать новую через /start"
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text("✅ Удаление отменено.")
    await callback.answer()

# ========== СТАТИСТИКА ==========
@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    user_id = message.from_user.id
    profile = get_profile(user_id)

    if not profile:
        await message.answer("❌ Сначала создай анкету!")
        return

    likes_received = len(likes_db.get(user_id, []))
    matches_count = len(matches_db.get(user_id, []))
    days_in_bot = (datetime.now() - users_db[user_id]["created_at"]).days

    text = "📊 <b>Статистика LoveSpark</b>\n\n"
    text += "👥 Всего пользователей: " + str(len(profiles_db)) + "\n"
    text += "❤️ Тебя лайкнули: " + str(likes_received) + "\n"
    text += "💕 Взаимных симпатий: " + str(matches_count) + "\n"
    text += "💎 Премиум пользователей: " + str(sum(1 for u in users_db.values() if is_premium(u["id"]))) + "\n\n"
    text += "<b>Твоя активность:</b>\n"
    text += "📅 Дней в боте: " + str(days_in_bot) + "\n"
    text += "❤️ Лайков сегодня: " + str(users_db[user_id]["daily_likes"]) + "/" + str(get_limits(user_id)["daily_likes"]) + "\n"
    text += "💬 Сообщений сегодня: " + str(users_db[user_id]["daily_messages"]) + "/" + str(get_limits(user_id)["daily_messages"]) + "\n\n"
    text += "<i>Продолжай активность — так тебя заметят больше людей! 🚀</i>"

    await message.answer(text)

@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: CallbackQuery):
    await stats(callback.message)
    await callback.answer()

# ========== АДМИН ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👤 Найти пользователя", callback_data="admin_find")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="admin_ban")],
    ])
    await message.answer("👑 <b>Админ-панель LoveSpark</b>", reply_markup=kb)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    total = len(users_db)
    registered = sum(1 for u in users_db.values() if u["registered"])
    premium_count = sum(1 for u in users_db.values() if is_premium(u["id"]))

    text = "📊 <b>Статистика бота:</b>\n\n"
    text += "👥 Всего пользователей: " + str(total) + "\n"
    text += "✅ Зарегистрировано: " + str(registered) + "\n"
    text += "💎 Премиум: " + str(premium_count) + "\n"
    text += "📈 Конверсия: " + str(round(registered/max(total,1)*100, 1)) + "%\n"
    text += "💰 Активных платежей: " + str(len(pending_payments)) + "\n"
    text += "🚫 Жалоб: " + str(sum(len(v) for v in reports_db.values()))

    await callback.message.edit_text(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("📢 Введи текст для рассылки всем пользователям:")
    await state.set_state(AdminStates.broadcast)
    await callback.answer()

@dp.message(AdminStates.broadcast)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text
    sent = 0
    failed = 0

    for user_id in users_db:
        try:
            await bot.send_message(user_id, "📢 <b>Сообщение от администрации:</b>\n\n" + text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await message.answer("✅ Отправлено: " + str(sent) + "\n❌ Не удалось: " + str(failed))
    await state.clear()

# ========== КАК ЭТО РАБОТАЕТ ==========
@dp.callback_query(F.data == "how_it_works")
async def how_it_works(callback: CallbackQuery):
    text = "📖 <b>Как работает LoveSpark:</b>\n\n"
    text += "1️⃣ <b>Создай анкету</b>\n"
    text += "   Заполни профиль с фото и описанием\n\n"
    text += "2️⃣ <b>Смотри анкеты</b>\n"
    text += "   Листай профили других пользователей\n\n"
    text += "3️⃣ <b>Ставь лайки</b>\n"
    text += "   ❤️ Понравился — ставь лайк\n"
    text += "   👎 Нет — пропускай\n\n"
    text += "4️⃣ <b>Взаимная симпатия</b>\n"
    text += "   Если вы оба поставили лайк — можно общаться! 💕\n\n"
    text += "5️⃣ <b>Общайся</b>\n"
    text += "   Пиши сообщения своим мэтчам\n\n"
    text += "💡 <i>Оформи премиум для безлимитных лайков и сообщений!</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Создать анкету", callback_data="start_reg")],
        [InlineKeyboardButton(text="💎 Тарифы премиум", callback_data="premium_info")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "premium_info")
async def premium_info(callback: CallbackQuery):
    await premium_menu(callback.message)
    await callback.answer()

# ========== КОМАНДА ПОМОЩИ ==========
@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = "❓ <b>Помощь по LoveSpark</b>\n\n"
    text += "/start — Запустить бота / создать анкету\n"
    text += "/help — Эта справка\n"
    text += "/premium — Информация о премиуме\n"
    text += "/profile — Показать свою анкету\n"
    text += "/search — Начать просмотр анкет\n\n"
    text += "<b>Основные функции:</b>\n"
    text += "🔍 Смотреть анкеты — листай и находи людей\n"
    text += "❤️ Мои лайки — кто тебя лайкнул (премиум)\n"
    text += "💬 Мои чаты — взаимные симпатии\n"
    text += "👤 Моя анкета — посмотреть свой профиль\n"
    text += "✏️ Редактировать — изменить данные\n"
    text += "💎 Премиум — оформить подписку\n\n"
    text += "<b>По вопросам:</b> @admin_support"
    await message.answer(text)

@dp.message(Command("premium"))
async def cmd_premium(message: Message):
    await premium_menu(message)

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await my_profile(message)

@dp.message(Command("search"))
async def cmd_search(message: Message):
    await browse_profiles(message)

# ========== ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ ==========
@dp.message()
async def unknown_message(message: Message):
    user_id = message.from_user.id
    await message.answer(
        "❓ Я тебя не понял. Используй кнопки меню или команды:\n\n"
        "/start — начать\n"
        "/help — помощь\n"
        "/search — смотреть анкеты",
        reply_markup=get_main_menu(user_id)
    )

# ========== ЗАПУСК ==========
async def set_commands():
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="help", description="❓ Помощь"),
        BotCommand(command="premium", description="💎 Премиум"),
        BotCommand(command="profile", description="👤 Моя анкета"),
        BotCommand(command="search", description="🔍 Смотреть анкеты"),
    ]
    await bot.set_my_commands(commands)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands(type="commands"))

async def main():
    await set_commands()
    logger.info("🚀 LoveSpark Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
