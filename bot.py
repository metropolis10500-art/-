import logging
import random
import asyncio
import aiohttp
from html import escape
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, BotCommand,
    InputMediaPhoto, CallbackQuery, Message,
    MenuButtonCommands
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# ========== КОНФИГУРАЦИЯ ==========
# ВНИМАНИЕ: Для продакшена храните токены в файле .env!
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
}

PREMIUM_LIMITS = {
    "daily_likes": 999999,
    "daily_messages": 999999,
    "profile_photos": 10,
    "search_radius": 500,
    "can_see_likes": True,
}

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== БОТ И ДИСПЕТЧЕР ==========
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ========== БАЗА ДАННЫХ (В ПАМЯТИ) ==========
# ВНИМАНИЕ: В памяти данные сбрасываются при перезапуске! Для продакшена используйте SQLite/PostgreSQL
users_db: Dict[int, dict] = {}
profiles_db: Dict[int, dict] = {}
likes_db: Dict[int, List[int]] = {}
matches_db: Dict[int, List[int]] = {}
viewed_db: Dict[int, Set[int]] = {} # ИСТОРИЯ ПРОСМОТРОВ (чтобы не показывать одних и тех же)
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

class EditProfile(StatesGroup):
    value = State()

class AdminStates(StatesGroup):
    broadcast = State()

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
    return PREMIUM_LIMITS if is_premium(user_id) else FREE_LIMITS

def reset_daily_limits(user_id: int):
    user = get_user(user_id)
    today = datetime.now().date()
    if user.get("last_reset") != today:
        user["daily_likes"] = 0
        user["daily_messages"] = 0
        user["last_reset"] = today

def format_age(age: int) -> str:
    if age % 10 == 1 and age % 100 != 11:
        return f"{age} год"
    elif 2 <= age % 10 <= 4 and not (12 <= age % 100 <= 14):
        return f"{age} года"
    else:
        return f"{age} лет"

def generate_profile_text(profile: dict, user_id: int) -> str:
    gender_emoji = {"male": "👨", "female": "👩", "other": "🌈"}.get(profile.get("gender", ""), "👤")
    looking_map = {"male": "мужчин", "female": "женщин", "all": "всех"}
    looking_emoji = {"male": "👨", "female": "👩", "all": "💕"}.get(profile.get("looking_for", ""), "💕")
    premium_badge = "\n💎 <b>ПРЕМИУМ ПОЛЬЗОВАТЕЛЬ</b>" if is_premium(user_id) else ""

    # Обязательно экранируем пользовательский ввод!
    name = escape(profile.get('name', 'Неизвестно'))
    city = escape(profile.get('city', 'Не указан'))
    bio = escape(profile.get('bio', 'Нет описания'))
    looking_text = looking_map.get(profile.get("looking_for", "all"), "всех")

    text = f"{gender_emoji} <b>{name}</b>, {format_age(profile.get('age', 0))}\n"
    text += f"📍 {city}\n"
    text += f"🔍 Ищу: {looking_emoji} {looking_text}{premium_badge}\n\n"
    text += f"📝 О себе:\n<i>{bio}</i>\n\n"
    text += f"✨ Анкета создана: {profile.get('created_at', 'недавно')}"
    return text

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    premium_btn = "👑 Мой премиум" if is_premium(user_id) else "💎 Премиум"
    kb = [
        [KeyboardButton(text="🔍 Смотреть анкеты")],
        [KeyboardButton(text="❤️ Мои лайки"), KeyboardButton(text="💬 Мои чаты")],
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="✏️ Редактировать")],
        [KeyboardButton(text=premium_btn)],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_inline_profile_actions(target_id: int, has_liked: bool = False) -> InlineKeyboardMarkup:
    like_btn = InlineKeyboardButton(text="💔 Убрать лайк", callback_data=f"unlike_{target_id}") if has_liked else InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{target_id}")
    buttons = [
        [like_btn, InlineKeyboardButton(text="💌 Написать", callback_data=f"message_{target_id}")],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{target_id}"),
         InlineKeyboardButton(text="🚫 Жалоба", callback_data=f"report_{target_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_compatible_profiles(user_id: int) -> List[tuple]:
    profile = get_profile(user_id)
    if not profile:
        return []

    viewed = viewed_db.get(user_id, set())
    candidates = []

    for uid, p in profiles_db.items():
        if uid == user_id or uid in viewed:
            continue
        if not p.get("active", True) or p.get("banned", False):
            continue
        
        pref_looking = profile.get("looking_for")
        p_looking = p.get("looking_for")
        
        if pref_looking != "all" and p.get("gender") != pref_looking:
            continue
        if p_looking != "all" and profile.get("gender") != p_looking:
            continue
            
        candidates.append((uid, p))

    random.shuffle(candidates)
    return candidates

async def show_next_profile(user_id: int, message: Message):
    candidates = get_compatible_profiles(user_id)
    if not candidates:
        # Если просмотрели всех, сбрасываем историю
        viewed_db[user_id] = set()
        candidates = get_compatible_profiles(user_id)
        
        if not candidates:
            await message.answer(
                "😔 Пока нет подходящих анкет. Попробуй позже или расширь критерии поиска!\n\n"
                "💡 Совет: оформи премиум для расширенного поиска!",
                reply_markup=get_main_menu(user_id)
            )
            return

    target_id, target_profile = candidates[0]
    
    # Добавляем в просмотренные
    if user_id not in viewed_db:
        viewed_db[user_id] = set()
    viewed_db[user_id].add(target_id)
    
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
        await message.answer(text, reply_markup=get_inline_profile_actions(target_id, has_liked))

# ========== YOOMONEY API ==========
async def check_yoomoney_payment(label: str) -> Optional[dict]:
    url = "https://yoomoney.ru/api/operation-history"
    headers = {
        "Authorization": f"Bearer {YOOMONEY_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"type": "deposition", "label": label, "details": "true"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    operations = result.get("operations", [])
                    if operations:
                        op = operations[0]
                        if op.get("status") == "success":
                            return {"success": True, "amount": op.get("amount", 0), "operation_id": op.get("operation_id")}
    except Exception as e:
        logger.error(f"YooMoney API error: {e}")
    return None

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user = get_user(user_id)

    if user["registered"] and get_profile(user_id):
        await message.answer(
            "👋 С возвращением в LoveSpark!\n\nЧто будем делать сегодня?",
            reply_markup=get_main_menu(user_id)
        )
        return

    welcome_text = (
        "✨ <b>Добро пожаловать в LoveSpark!</b> ✨\n\n"
        "🔥 <b>Лучший бот знакомств!</b>\n\n"
        "❤️ Находи свою половинку среди тысяч пользователей\n"
        "💬 Общайся без ограничений\n"
        "🔒 Полная безопасность и анонимность\n\n"
        "<b>Нажми кнопку ниже, чтобы начать регистрацию анкеты 👇</b>"
    )

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
        "🌟 <b>Начинаем создание твоей анкеты!</b>\n\nКак тебя зовут? (напиши свое имя)",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.name)
    await callback.answer()

@dp.message(Registration.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("❌ Имя должно быть от 2 до 30 символов. Попробуй еще раз:")
        return
    await state.update_data(name=name)
    await message.answer("🎂 Сколько тебе лет? (напиши число)")
    await state.set_state(Registration.age)

@dp.message(Registration.age, F.text)
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

@dp.callback_query(F.data.startswith("gender_"), Registration.gender)
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

@dp.callback_query(F.data.startswith("looking_"), Registration.looking_for)
async def reg_looking(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.split("_")[1]
    looking_map = {"male": "мужчин", "female": "женщин", "all": "всех"}
    await state.update_data(looking_for=looking, looking_for_text=looking_map[looking])

    await callback.message.delete()
    await callback.message.answer("📍 Напиши название своего города:\n\n<i>Например: Москва, Санкт-Петербург...</i>")
    await state.set_state(Registration.city)
    await callback.answer()

@dp.message(Registration.city, F.text)
async def reg_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        await message.answer("❌ Название города слишком короткое или длинное. Попробуй еще раз:")
        return

    await state.update_data(city=city)
    await message.answer("📝 Расскажи немного о себе (хобби, интересы, что ищешь):\n<i>Минимум 10 символов, максимум 500</i>")
    await state.set_state(Registration.bio)

@dp.message(Registration.bio, F.text)
async def reg_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10:
        await message.answer("❌ Описание слишком короткое. Расскажи о себе подробнее:")
        return
    if len(bio) > 500:
        await message.answer("❌ Описание слишком длинное (максимум 500 символов). Сократи:")
        return

    await state.update_data(bio=bio)
    await message.answer("📸 Отправь свое фото для анкеты:\n\n<i>Желательно хорошее качество, где видно лицо 😊</i>")
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    data = await state.get_data()
    photos_list = data.get("photos", [])
    photos_list.append(photo_file_id)
    await state.update_data(photos=photos_list)

    limits = get_limits(message.from_user.id)
    if len(photos_list) < limits["profile_photos"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Это все, продолжить", callback_data="photos_done")],
        ])
        await message.answer(f"📷 Фото {len(photos_list)}/{limits['profile_photos']} добавлено. Можешь прислать еще или нажать кнопку.", reply_markup=kb)
    else:
        await finish_registration(message, state)

@dp.callback_query(F.data == "photos_done")
async def photos_done(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await finish_registration(callback.message, state)
    await callback.answer()

async def finish_registration(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    if not data.get("name"):
        return # Защита от дублей при множественной отправке фото

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
        await message.answer_photo(photo=profile["photos"][0], caption=profile_text, reply_markup=get_main_menu(user_id))
    else:
        await message.answer(profile_text, reply_markup=get_main_menu(user_id))

    await message.answer(
        "🎉 <b>Анкета создана!</b>\n\nТеперь ты можешь:\n"
        "🔍 <b>Смотреть анкеты</b>\n❤️ <b>Ставить лайки</b>\n💬 <b>Общаться</b>\n\n"
        "<i>💡 Совет: оформи премиум, чтобы снять все ограничения!</i>"
    )

# Обработчик ошибок ввода при регистрации
@dp.message(StateFilter(Registration), ~F.photo, ~F.text)
async def reg_invalid_input(message: Message):
    await message.answer("❌ Пожалуйста, отправь правильный формат (текст или фото в зависимости от шага).")

# ========== ГЛАВНОЕ МЕНЮ ==========
@dp.message(F.text == "🔍 Смотреть анкеты")
async def browse_profiles(message: Message):
    user_id = message.from_user.id
    reset_daily_limits(user_id)
    if not get_profile(user_id):
        return await message.answer("❌ Сначала создай анкету! Напиши /start")
    await show_next_profile(user_id, message)

@dp.callback_query(F.data.startswith("like_"))
async def like_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])
    reset_daily_limits(user_id)
    
    user = get_user(user_id)
    if user["daily_likes"] >= get_limits(user_id)["daily_likes"]:
        return await callback.answer("❌ Лимит лайков на сегодня исчерпан! Оформи премиум 💎", show_alert=True)

    if target_id not in likes_db:
        likes_db[target_id] = []

    if user_id not in likes_db[target_id]:
        likes_db[target_id].append(user_id)
        user["daily_likes"] += 1

    # Взаимный лайк
    if target_id in likes_db.get(user_id, []):
        matches_db.setdefault(target_id, []).append(user_id)
        matches_db.setdefault(user_id, []).append(target_id)
        target_profile = get_profile(user_id)

        try:
            await bot.send_message(
                target_id,
                f"🎉 <b>Взаимная симпатия!</b>\n\n"
                f"❤️ Тебе понравился(ась) <b>{escape(target_profile['name'])}</b>, {target_profile['age']}!\n"
                f"💬 Начни общение — нажми на кнопку ниже!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💌 Написать", callback_data=f"message_{user_id}")]
                ])
            )
        except TelegramAPIError:
            pass # Пользователь заблокировал бота

        await callback.answer("🎉 Взаимная симпатия!")
    else:
        await callback.answer("❤️ Лайк отправлен!")

    try:
        await callback.message.edit_reply_markup(reply_markup=get_inline_profile_actions(target_id, True))
    except TelegramAPIError:
        pass

@dp.callback_query(F.data.startswith("unlike_"))
async def unlike_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    if target_id in likes_db and user_id in likes_db[target_id]:
        likes_db[target_id].remove(user_id)

    await callback.answer("💔 Лайк убран")
    await callback.message.edit_reply_markup(reply_markup=get_inline_profile_actions(target_id, False))

@dp.callback_query(F.data.startswith("message_"))
async def send_message_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    if not is_premium(user_id) and target_id not in matches_db.get(user_id, []):
        return await callback.answer("💎 Нужен премиум или взаимный лайк для отправки сообщений!", show_alert=True)

    await state.update_data(message_target=target_id)
    target_profile = get_profile(target_id)
    name = escape(target_profile["name"]) if target_profile else "пользователю"

    await callback.message.answer(f"💌 Напиши сообщение для <b>{name}</b>:\n<i>Он(а) получит его сразу!</i>")
    await state.set_state(MessageState.target_id)
    await callback.answer()

@dp.message(MessageState.target_id, F.text)
async def send_direct_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("message_target")
    if not target_id:
        return await state.clear()

    user_id = message.from_user.id
    reset_daily_limits(user_id)
    user = get_user(user_id)

    if not is_premium(user_id):
        if user["daily_messages"] >= get_limits(user_id)["daily_messages"]:
            await message.answer("❌ Лимит сообщений на сегодня исчерпан!\n💎 Оформи премиум!")
            return await state.clear()
        user["daily_messages"] += 1

    my_profile = get_profile(user_id)
    sender_name = escape(my_profile["name"]) if my_profile else "Аноним"

    try:
        await bot.send_message(
            target_id,
            f"💌 <b>Новое сообщение от {sender_name}:</b>\n\n"
            f"{escape(message.text)}\n\n"
            f"<i>Ответь через бота — нажми кнопку ниже 👇</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💌 Ответить", callback_data=f"message_{user_id}")]
            ])
        )
        await message.answer("✅ Сообщение отправлено!")
    except TelegramAPIError:
        await message.answer("❌ Не удалось отправить сообщение. Возможно, пользователь заблокировал бота.")
    finally:
        await state.clear()

@dp.message(MessageState.target_id)
async def invalid_direct_message(message: Message):
    await message.answer("❌ Бот пока поддерживает только текстовые сообщения. Пожалуйста, отправь текст.")

@dp.callback_query(F.data.startswith("skip_"))
async def skip_profile(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("👎 Пропущено")
    await show_next_profile(callback.from_user.id, callback.message)

# ========== ПРЕМИУМ ==========
@dp.message(F.text.in_(["💎 Премиум", "👑 Мой премиум"]))
async def premium_menu(message: Message):
    user_id = message.from_user.id
    if is_premium(user_id):
        premium_until = users_db[user_id]["premium_until"]
        return await message.answer(
            f"👑 <b>Твой премиум активен!</b>\n\n"
            f"💎 Действует до: {premium_until.strftime('%d.%m.%Y')}\n\n"
            "✅ Безлимитные лайки и сообщения\n"
            "✅ Видеть, кто тебя лайкнул\n"
            "✅ До 10 фото в анкете\n\n🎉 Наслаждайся!",
            reply_markup=get_main_menu(user_id)
        )

    text = (
        "💎 <b>LoveSpark Премиум</b> 💎\n\n"
        "✅ Безлимитные лайки и сообщения\n"
        "✅ Видеть, кто тебя лайкнул\n"
        "✅ Расширенные фильтры поиска\n\n<b>Тарифы:</b>\n"
    )
    for plan in PREMIUM_PRICES.values():
        text += f"{plan['emoji']} <b>{plan['name']}</b> — {plan['price']}₽\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p['emoji']} {p['name']} — {p['price']}₽", callback_data=f"buy_{k}")]
        for k, p in PREMIUM_PRICES.items()
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_premium(callback: CallbackQuery):
    plan_key = callback.data.split("_")[1]
    plan = PREMIUM_PRICES.get(plan_key)
    if not plan: return await callback.answer("❌ Ошибка", show_alert=True)

    payment_id = f"LS_{callback.from_user.id}_{plan_key}_{int(datetime.now().timestamp())}"
    pending_payments[payment_id] = {
        "user_id": callback.from_user.id,
        "plan_key": plan_key,
        "amount": plan["price"]
    }

    yoomoney_url = (f"https://yoomoney.ru/quickpay/confirm?receiver={YOOMONEY_WALLET}&"
                    f"quickpay-form=button&paymentType=AC&sum={plan['price']}&label={payment_id}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {plan['price']}₽", url=yoomoney_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_{payment_id}")],
    ])
    await callback.message.edit_text(
        f"💎 <b>Оформление премиума: {plan['name']}</b>\n\n"
        f"Сумма: <b>{plan['price']}₽</b>\n"
        f"1️⃣ Нажми «Оплатить» и соверши платеж\n"
        f"2️⃣ После оплаты нажми «Я оплатил»", reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.split("check_")[1]
    payment = pending_payments.get(payment_id)
    if not payment: return await callback.answer("❌ Платеж не найден или устарел", show_alert=True)

    result = await check_yoomoney_payment(payment_id)
    if result and result["success"]:
        plan = PREMIUM_PRICES[payment["plan_key"]]
        user_id = payment["user_id"]
        
        premium_until = datetime.now() + timedelta(days=plan["days"])
        users_db[user_id]["premium_until"] = premium_until
        del pending_payments[payment_id]

        await callback.message.edit_text(
            f"🎉 <b>Премиум активирован!</b>\n\n"
            f"💎 Тариф: {plan['name']}\n"
            f"📅 Действует до: {premium_until.strftime('%d.%m.%Y')}"
        )
        try:
            await bot.send_message(ADMIN_ID, f"💰 <b>Оплата!</b>\nID: {user_id}\nТариф: {plan['name']}")
        except TelegramAPIError:
            pass
    else:
        await callback.answer("⏳ Платеж еще не поступил. Попробуй через минуту!", show_alert=True)

# ========== РЕДАКТИРОВАНИЕ АНКЕТЫ ==========
@dp.message(F.text == "✏️ Редактировать")
async def edit_profile_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name"),
         InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
        [InlineKeyboardButton(text="📍 Город", callback_data="edit_city"),
         InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio")],
        [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photos")],
    ])
    await message.answer("✏️ Что хочешь изменить?", reply_markup=kb)

@dp.callback_query(F.data.startswith("edit_"))
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    await state.update_data(edit_field=field)

    if field == "photos":
        await callback.message.edit_text("📸 Отправь новое фото (оно заменит текущие):")
    else:
        await callback.message.edit_text("✏️ Введи новое значение:")
    await state.set_state(EditProfile.value)
    await callback.answer()

@dp.message(EditProfile.value)
async def edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    user_id = message.from_user.id

    if field == "photos" and message.photo:
        profiles_db[user_id]["photos"] = [message.photo[-1].file_id]
    elif message.text:
        value = message.text.strip()
        if field == "name" and 2 <= len(value) <= 30: profiles_db[user_id]["name"] = value
        elif field == "age" and value.isdigit() and 16 <= int(value) <= 100: profiles_db[user_id]["age"] = int(value)
        elif field == "city" and 2 <= len(value) <= 50: profiles_db[user_id]["city"] = value
        elif field == "bio" and 10 <= len(value) <= 500: profiles_db[user_id]["bio"] = value
        else: return await message.answer("❌ Неверный формат данных. Попробуй еще раз:")
    else:
        return await message.answer("❌ Отправь корректные данные.")

    await message.answer("✅ Изменения сохранены!", reply_markup=get_main_menu(user_id))
    await state.clear()

# ========== ПРОСМОТР ЛАЙКОВ, ЧАТОВ И ПРОФИЛЯ ==========
@dp.message(F.text == "❤️ Мои лайки")
async def my_likes(message: Message):
    user_id = message.from_user.id
    likes = likes_db.get(user_id, [])
    if not likes: return await message.answer("😔 Пока никто не лайкнул тебя.")

    if not get_limits(user_id)["can_see_likes"]:
        return await message.answer("💎 <b>Доступно только с премиумом!</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Оформить", callback_data="premium_info")]]))

    text = f"❤️ <b>Тебя лайкнули ({len(likes)}):</b>\n\n"
    for liker_id in likes[:20]:
        p = get_profile(liker_id)
        if p: text += f"• {escape(p['name'])}, {p['age']} — {escape(p['city'])}\n"
    await message.answer(text)

@dp.message(F.text == "💬 Мои чаты")
async def my_chats(message: Message):
    user_id = message.from_user.id
    matches = matches_db.get(user_id, [])
    if not matches: return await message.answer("💬 Пока нет взаимных симпатий.")

    kb_buttons = []
    for match_id in matches:
        p = get_profile(match_id)
        if p: kb_buttons.append([InlineKeyboardButton(text=f"💌 Написать {escape(p['name'])}", callback_data=f"message_{match_id}")])
    await message.answer("💕 <b>Взаимные симпатии:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@dp.message(F.text == "👤 Моя анкета")
async def my_profile(message: Message):
    user_id = message.from_user.id
    profile = get_profile(user_id)
    if not profile: return await message.answer("❌ У тебя нет анкеты. Напиши /start")
    
    text = generate_profile_text(profile, user_id)
    if profile.get("photos"):
        await message.answer_photo(photo=profile["photos"][0], caption=text)
    else:
        await message.answer(text)

# ========== АДМИН ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]])
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=kb)

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("📢 Введи текст для рассылки:")
    await state.set_state(AdminStates.broadcast)

@dp.message(AdminStates.broadcast)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    sent, failed = 0, 0
    # list() защищает от ошибки изменения словаря во время итерации
    for user_id in list(users_db.keys()):
        try:
            await bot.send_message(user_id, f"📢 <b>Сообщение:</b>\n\n{message.html_text}")
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            failed += 1
    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")
    await state.clear()

# ========== БАЗОВЫЕ КОМАНДЫ ==========
@dp.message(F.text.in_(["⚙️ Настройки", "📊 Статистика"]))
async def misc_menus(message: Message):
    await message.answer("В разработке / Выбрано в меню.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("❓ /start - Главное меню\n/premium - Премиум\n/profile - Анкета")

@dp.message()
async def unknown_message(message: Message, state: FSMContext):
    # Если юзер не в состоянии FSM и пишет текст, показываем меню
    if await state.get_state() is None:
        await message.answer("❓ Используй кнопки меню.", reply_markup=get_main_menu(message.from_user.id))

# ========== ЗАПУСК ==========
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="help", description="❓ Помощь")
    ])
    logger.info("🚀 LoveSpark Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
