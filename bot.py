import asyncio
import logging
import datetime
import random
import string
import aiosqlite
import aiohttp
import uuid
import html

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==================== CONFIG ====================
BOT_TOKEN = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
ADMIN_ID = 5494544187

YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"

FREE_LIKES_PER_DAY = 10
FREE_MESSAGES_PER_DAY = 5

PREMIUM_TARIFFS = {
    "week": {"name": "⚡ Премиум на 7 дней", "price": 149, "days": 7, "description": "Пробный VIP-статус"},
    "month": {"name": "💎 Премиум на 30 дней", "price": 399, "days": 30, "description": "Выбор 80% пользователей"},
    "quarter": {"name": "👑 Премиум на 90 дней", "price": 999, "days": 90, "description": "Экономия 25%"},
    "year": {"name": "🏆 Премиум на 365 дней", "price": 2999, "days": 365, "description": "Максимальная выгода"}
}

CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград",
    "Донецк", "Луганск", "Макеевка", "Горловка", "Мариуполь", "Алчевск",
    "Сочи", "Краснодар", "Тюмень", "Калининград", "Симферополь", "Севастополь"
]

DB_NAME = "lovespark.db"
YOOMONEY_API_URL = "https://yoomoney.ru/api"

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ==================== BOT INIT ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== STATES ====================
class Registration(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    looking_for = State()
    photo = State()
    bio = State()

class ChatState(StatesGroup):
    chatting = State()

class AdminState(StatesGroup):
    broadcast = State()

# ==================== DATABASE (Сокращено для читаемости, логика та же) ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT, name TEXT NOT NULL, age INTEGER NOT NULL, city TEXT NOT NULL,
                gender TEXT NOT NULL, looking_for TEXT NOT NULL, photo TEXT, bio TEXT,
                is_premium INTEGER DEFAULT 0, premium_until TEXT, likes_today INTEGER DEFAULT 0,
                messages_today INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, referral_code TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL, is_mutual INTEGER DEFAULT 0, UNIQUE(from_user, to_user)
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user1 INTEGER NOT NULL,
                user2 INTEGER NOT NULL, UNIQUE(user1, user2)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL, content_type TEXT NOT NULL,
                content TEXT NOT NULL, file_id TEXT
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL, amount INTEGER NOT NULL, label TEXT UNIQUE NOT NULL, status TEXT DEFAULT "pending"
            );
        """)
        await db.commit()

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_user(telegram_id: int, username: str, name: str, age: int, city: str,
                     gender: str, looking_for: str, photo: str, bio: str, referral_code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, name, age, city, gender, looking_for, photo, bio, referral_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_id, username, name, age, city, gender, looking_for, photo, bio, referral_code))
        await db.commit()

async def update_user(telegram_id: int, **kwargs):
    async with aiosqlite.connect(DB_NAME) as db:
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]
        await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
        await db.commit()

async def get_random_profile(telegram_id: int, looking_for: str, city: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        user = await get_user(telegram_id)
        if not user: return None

        query = """
            SELECT * FROM users WHERE telegram_id != ? AND is_active = 1
            AND telegram_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
            AND telegram_id NOT IN (SELECT user2 FROM matches WHERE user1 = ? UNION SELECT user1 FROM matches WHERE user2 = ?)
        """
        params = [telegram_id, telegram_id, telegram_id, telegram_id]

        if looking_for == "both":
            query += " AND (looking_for = ? OR looking_for = ? OR looking_for = ?)"
            params.extend([user["gender"], "both", user["gender"]])
        else:
            query += " AND gender = ? AND (looking_for = ? OR looking_for = ?)"
            params.extend([looking_for, user["gender"], "both"])

        if city and not user.get("is_premium"):
            query += " AND city = ?"
            params.append(city)

        query += " ORDER BY RANDOM() LIMIT 1"
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def add_like(from_user: int, to_user: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM likes WHERE from_user = ? AND to_user = ?", (to_user, from_user)) as cursor:
            mutual = await cursor.fetchone()

        await db.execute("INSERT OR IGNORE INTO likes (from_user, to_user, is_mutual) VALUES (?, ?, ?)",
            (from_user, to_user, 1 if mutual else 0))

        if mutual:
            await db.execute("INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)", (min(from_user, to_user), max(from_user, to_user)))
            await db.execute("UPDATE likes SET is_mutual = 1 WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)",
                (from_user, to_user, to_user, from_user))
        await db.commit()
        return mutual is not None

async def get_match(user1: int, user2: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)",
            (user1, user2, user2, user1)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_matches(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.*, u.name, u.photo, u.age, u.city 
            FROM matches m JOIN users u ON (u.telegram_id = CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END)
            WHERE m.user1 = ? OR m.user2 = ? ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

# ==================== UI & KEYBOARDS ====================
def start_reg_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Зажечь искру (Создать анкету)", callback_data="start_registration")]
    ])

def gender_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕺 Я парень", callback_data="gender_male"), InlineKeyboardButton(text="💃 Я девушка", callback_data="gender_female")]
    ])

def looking_for_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💃 Девушек", callback_data="look_female"), InlineKeyboardButton(text="🕺 Парней", callback_data="look_male")],
        [InlineKeyboardButton(text="🥂 Всех", callback_data="look_both")]
    ])

def confirm_reg_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё супер, погнали!", callback_data="confirm_reg")],
        [InlineKeyboardButton(text="🔄 Заполнить заново", callback_data="start_registration")]
    ])

def city_kb():
    kb = [[KeyboardButton(text=city) for city in CITIES[i:i+3]] for i in range(0, 15, 3)]
    kb.append([KeyboardButton(text="🌍 Напишу свой город")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Выбери или напиши свой город...")

def main_menu_kb(is_premium: bool = False):
    kb = [
        [KeyboardButton(text="🔥 Искать пару")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💌 Мои мэтчи")],
    ]
    kb.append([KeyboardButton(text="👑 VIP Статус")] if is_premium else [KeyboardButton(text="💎 Получить Premium")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def profile_actions_kb(profile_id: int, is_premium: bool = False):
    buttons = [
        [InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{profile_id}"), InlineKeyboardButton(text="👎 Дальше", callback_data=f"skip_{profile_id}")],
    ]
    if is_premium: buttons.append([InlineKeyboardButton(text="⭐ Супер-лайк (Обратить внимание)", callback_data=f"superlike_{profile_id}")])
    buttons.append([InlineKeyboardButton(text="🚫 В ЧС", callback_data=f"block_{profile_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== UTILITIES ====================
def get_premium_status(user):
    if not user or not user.get("is_premium"): return False
    if user.get("premium_until"):
        return datetime.datetime.fromisoformat(user["premium_until"]) > datetime.datetime.now()
    return False

def format_profile(data):
    gender_emoji = "🕺" if data.get("gender") == "male" else "💃"
    prem_badge = "💎" if data.get("is_premium") else ""
    return f"{gender_emoji} <b>{data.get('name', 'Имя')}</b>, {data.get('age', '?')} {prem_badge}\n📍 {data.get('city', 'Город')}\n\n📝 <i>«{data.get('bio', 'О себе')}»</i>"

# ==================== ONBOARDING / REGISTRATION ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user and user.get("is_active"):
        return await message.answer(f"🔥 <b>С возвращением в LoveSpark, {user['name']}!</b>\n\nТвоя идеальная пара уже ждёт тебя.", reply_markup=main_menu_kb(get_premium_status(user)), parse_mode=ParseMode.HTML)
    
    welcome_text = (
        "🔥 <b>Добро пожаловать в LoveSpark!</b> 🔥\n\n"
        "Забудь про скучные свайпы. Здесь собираются самые яркие и интересные люди со всей России, ДНР и ЛНР. 🇷🇺\n\n"
        "✨ <b>Почему мы?</b>\n"
        "• Умный подбор пар 🧠\n"
        "• Общение без фейков 🛡️\n"
        "• Закрытые VIP-комнаты 💎\n\n"
        "Готов(а) найти свою любовь или крутую компанию? 😉👇"
    )
    await message.answer(welcome_text, reply_markup=start_reg_kb(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "start_registration")
async def start_reg(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("👋 Отлично! Я буду твоим Купидоном 🏹.\n\n<b>Как мне к тебе обращаться?</b>\n(Напиши своё имя)", parse_mode=ParseMode.HTML)
    await state.set_state(Registration.name)

@dp.message(Registration.name)
async def reg_name(message: Message, state: FSMContext):
    name = html.escape(message.text.strip())
    if not (2 <= len(name) <= 20): return await message.answer("Имя должно быть от 2 до 20 символов. Давай еще раз:")
    await state.update_data(name=name)
    await message.answer(f"Приятно познакомиться, <b>{name}</b>! ✨\n\n<b>А сколько тебе лет?</b> (напиши цифрой, например: 25)", parse_mode=ParseMode.HTML)
    await state.set_state(Registration.age)

@dp.message(Registration.age)
async def reg_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not (16 <= age <= 100): raise ValueError
    except ValueError: return await message.answer("Упс! Возраст должен быть числом от 16 до 100 🤫. Попробуй еще раз:")
    
    await state.update_data(age=age)
    await message.answer("Супер! 📍 <b>В каком городе ты сейчас находишься?</b>\n(Выбери на клавиатуре или напиши текстом)", reply_markup=city_kb(), parse_mode=ParseMode.HTML)
    await state.set_state(Registration.city)

@dp.message(Registration.city)
async def reg_city(message: Message, state: FSMContext):
    if message.text == "🌍 Напишу свой город":
        return await message.answer("Введи название своего города текстом:", reply_markup=ReplyKeyboardRemove())
        
    city = html.escape(message.text.strip())
    await state.update_data(city=city)
    
    await message.answer("Отлично! Теперь давай определимся. <b>Кто ты?</b> 👇", reply_markup=gender_inline_kb(), parse_mode=ParseMode.HTML)
    # Remove reply keyboard if it was open
    msg = await message.answer("...", reply_markup=ReplyKeyboardRemove())
    await msg.delete()
    await state.set_state(Registration.gender)

@dp.callback_query(F.data.startswith("gender_"), Registration.gender)
async def reg_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split("_")[1]
    await state.update_data(gender=gender)
    await callback.message.edit_text("🎯 <b>А кого мы ищем?</b> 👇", reply_markup=looking_for_inline_kb(), parse_mode=ParseMode.HTML)
    await state.set_state(Registration.looking_for)

@dp.callback_query(F.data.startswith("look_"), Registration.looking_for)
async def reg_looking(callback: CallbackQuery, state: FSMContext):
    look = callback.data.split("_")[1]
    await state.update_data(looking_for=look)
    await callback.message.delete()
    await callback.message.answer("📸 <b>Время сиять!</b>\n\nОтправь своё лучшее фото (не файлом, а как картинку). Люди с хорошим фото получают в 3 раза больше лайков! 🔥", parse_mode=ParseMode.HTML)
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Остался последний штрих! 🎨\n\n<b>Напиши пару слов о себе.</b> Чем увлекаешься? Что любишь? Какая у тебя суперспособность?\n\n<i>(Оригинальные описания работают лучше всего!)</i>", parse_mode=ParseMode.HTML)
    await state.set_state(Registration.bio)

@dp.message(Registration.bio)
async def reg_bio(message: Message, state: FSMContext):
    bio = html.escape(message.text.strip())
    if len(bio) < 5: return await message.answer("Ну же, не скромнячай! Напиши чуть больше о себе 😊")
    await state.update_data(bio=bio[:500])
    
    data = await state.get_data()
    preview = f"🎉 <b>Вот как выглядит твоя анкета:</b>\n\n{format_profile(data)}"
    
    await message.answer_photo(photo=data['photo'], caption=preview, reply_markup=confirm_reg_kb(), parse_mode=ParseMode.HTML)
    await state.set_state(None)

@dp.callback_query(F.data == "confirm_reg")
async def finish_reg(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    code = f"LS{uuid.uuid4().hex[:6].upper()}"
    await create_user(callback.from_user.id, callback.from_user.username, data['name'], data['age'], data['city'], data['gender'], data['looking_for'], data['photo'], data['bio'], code)
    
    await callback.message.delete()
    await callback.message.answer(
        "🚀 <b>Твоя анкета успешно опубликована!</b>\n\n"
        "Мы уже начали показывать её тем, кто рядом. Давай искать твою любовь!",
        reply_markup=main_menu_kb(False), parse_mode=ParseMode.HTML
    )
    await state.clear()

# ==================== MAIN LOGIC ====================

@dp.message(F.text == "🔥 Искать пару")
async def find_pair(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return await message.answer("Для начала нужно зарегистрироваться! Нажми /start")
    
    if not get_premium_status(user) and user.get("likes_today", 0) >= FREE_LIKES_PER_DAY:
        return await message.answer("😔 <b>Лимит симпатий на сегодня исчерпан.</b>\n\nУстанови 💎 Premium, чтобы снять все ограничения и общаться безлимитно!", parse_mode=ParseMode.HTML)

    profile = await get_random_profile(user['telegram_id'], user['looking_for'], user['city'])
    if not profile: 
        return await message.answer("💤 Сейчас нет новых анкет по твоим критериям. Попробуй зайти чуть позже!")
        
    await message.answer_photo(
        photo=profile['photo'], 
        caption=format_profile(profile), 
        reply_markup=profile_actions_kb(profile['telegram_id'], get_premium_status(user)), 
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return
    status = "👑 VIP Пользователь" if get_premium_status(user) else "⭐ Базовый"
    await message.answer_photo(photo=user['photo'], caption=f"{format_profile(user)}\n\n📊 Твой статус: <b>{status}</b>\n❤️ Лайков осталось: {FREE_LIKES_PER_DAY - user['likes_today'] if not get_premium_status(user) else 'Безлимит'}", parse_mode=ParseMode.HTML)

@dp.message(F.text == "💌 Мои мэтчи")
async def my_matches(message: Message):
    matches = await get_matches(message.from_user.id)
    if not matches: return await message.answer("💔 У тебя пока нет взаимных симпатий. Но это только начало! Листай анкеты и ставь лайки.")
    
    await message.answer(f"💌 Ура! У тебя <b>{len(matches)}</b> взаимных симпатий!\nВыбери, с кем хочешь начать общение:", parse_mode=ParseMode.HTML)
    for m in matches[:5]: 
        p_id = m['user2'] if m['user1'] == message.from_user.id else m['user1']
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Написать", callback_data=f"chat_{m['id']}_{p_id}")]])
        await message.answer_photo(photo=m['photo'], caption=f"💕 <b>{m['name']}</b>, {m['age']}", reply_markup=kb, parse_mode=ParseMode.HTML)

# ==================== ACTIONS (LIKES, CHATS) ====================

@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)
    
    await update_user(user['telegram_id'], likes_today=user.get("likes_today", 0) + 1)
    is_mutual = await add_like(user['telegram_id'], target_id)
    
    if is_mutual:
        partner = await get_user(target_id)
        await callback.message.answer(f"🎉 <b>It's a MATCH! Взаимная симпатия!</b>\n\nТебе и {partner['name']} нравитесь друг другу. Почему бы не сказать «Привет»? 👇", parse_mode=ParseMode.HTML)
        try: 
            await bot.send_message(target_id, f"🎉 <b>У тебя новый мэтч!</b>\n{user['name']} лайкнул(а) тебя в ответ! Действуй!", parse_mode=ParseMode.HTML)
        except Exception: pass
    
    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("skip_") | F.data.startswith("block_"))
async def skip_profile(callback: CallbackQuery):
    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat_cb(callback: CallbackQuery, state: FSMContext):
    _, match_id, p_id = callback.data.split("_")
    partner = await get_user(int(p_id))
    await state.set_state(ChatState.chatting)
    await state.update_data(partner_id=int(p_id))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="exit_chat")]])
    await callback.message.answer(f"🔒 <b>Защищенный чат с {partner['name']}</b>\n\nПросто пиши свои сообщения сюда, а я буду передавать их анонимно.", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.message(ChatState.chatting)
async def process_chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data.get("partner_id")
    if not partner_id: return await state.clear()
    
    user = await get_user(message.from_user.id)
    try:
        if message.text: await bot.send_message(partner_id, f"💌 <b>{user['name']}:</b>\n{message.text}", parse_mode=ParseMode.HTML)
        elif message.photo: await bot.send_photo(partner_id, message.photo[-1].file_id, caption=f"📸 <b>{user['name']}</b>", parse_mode=ParseMode.HTML)
    except Exception:
        await message.answer("❌ Собеседник недоступен.")

@dp.callback_query(F.data == "exit_chat")
async def exit_chat_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🚪 Диалог завершен. Можешь продолжать поиск!")

# ==================== RUNNER ====================
async def main():
    await init_db()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
