import asyncio
import logging
import datetime
import random
import string
import aiosqlite
import aiohttp
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
    "week": {"name": "⚡ Премиум на 7 дней", "price": 149, "days": 7, "description": "Пробный период"},
    "month": {"name": "💎 Премиум на 30 дней", "price": 399, "days": 30, "description": "Оптимальный вариант"},
    "quarter": {"name": "👑 Премиум на 90 дней", "price": 999, "days": 90, "description": "Экономия 25%"},
    "year": {"name": "🏆 Премиум на 365 дней", "price": 2999, "days": 365, "description": "Экономия 50%"}
}

CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград",
    "Краснодар", "Саратов", "Тюмень", "Тольятти", "Ижевск",
    "Барнаул", "Иркутск", "Хабаровск", "Ярославль", "Владивосток",
    "Махачкала", "Томск", "Оренбург", "Кемерово", "Новокузнецк",
    "Рязань", "Астрахань", "Набережные Челны", "Пенза", "Липецк",
    "Киров", "Тула", "Чебоксары", "Калининград", "Брянск",
    "Курск", "Иваново", "Магнитогорск", "Улан-Удэ", "Тверь",
    "Ставрополь", "Симферополь", "Севастополь", "Донецк", "Луганск",
    "Макеевка", "Горловка", "Мариуполь", "Алчевск",
    "Сочи", "Архангельск", "Вологда", "Калуга", "Смоленск",
    "Орёл", "Белгород", "Владимир", "Сургут", "Нижневартовск"
]

BOT_NAME = "LoveSpark"
BOT_DESCRIPTION = "Бот знакомств для всех городов России"
DB_NAME = "lovespark.db"
YOOMONEY_API_URL = "https://yoomoney.ru/api"

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    confirm = State()

class EditProfile(StatesGroup):
    choosing_field = State()
    new_value = State()

class ChatState(StatesGroup):
    chatting = State()

class AdminState(StatesGroup):
    broadcast = State()

class CityInput(StatesGroup):
    waiting_city = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                city TEXT NOT NULL,
                gender TEXT NOT NULL,
                looking_for TEXT NOT NULL,
                photo TEXT,
                bio TEXT,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                likes_today INTEGER DEFAULT 0,
                messages_today INTEGER DEFAULT 0,
                last_activity TEXT,
                is_active INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                profile_views INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL,
                is_mutual INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_user, to_user)
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1 INTEGER NOT NULL,
                user2 INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user1, user2)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content TEXT NOT NULL,
                file_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL,
                amount INTEGER NOT NULL,
                label TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT "pending",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(referred_id)
            );
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE DEFAULT CURRENT_DATE,
                new_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0,
                likes_count INTEGER DEFAULT 0,
                matches_count INTEGER DEFAULT 0,
                payments_count INTEGER DEFAULT 0,
                revenue INTEGER DEFAULT 0
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
            INSERT INTO users (telegram_id, username, name, age, city, gender, looking_for,
                              photo, bio, referral_code, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_id, username, name, age, city, gender, looking_for,
              photo, bio, referral_code, datetime.datetime.now().isoformat()))
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
            SELECT * FROM users
            WHERE telegram_id != ? AND is_active = 1 AND is_banned = 0
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

        if city and not get_premium_status(user):
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
            await db.execute("INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
                (min(from_user, to_user), max(from_user, to_user)))
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
            SELECT m.*, u.name, u.username, u.photo, u.age, u.city
            FROM matches m
            JOIN users u ON (u.telegram_id = CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END)
            WHERE m.user1 = ? OR m.user2 = ?
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def add_message(match_id: int, from_user: int, content_type: str, content: str, file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO messages (match_id, from_user, content_type, content, file_id) VALUES (?, ?, ?, ?, ?)",
            (match_id, from_user, content_type, content, file_id))
        await db.commit()

async def add_payment(user_id: int, tariff: str, amount: int, label: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO payments (user_id, tariff, amount, label) VALUES (?, ?, ?, ?)", (user_id, tariff, amount, label))
        await db.commit()

async def update_payment(label: str, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE payments SET status = ?, paid_at = ? WHERE label = ?",
            (status, datetime.datetime.now().isoformat(), label))
        await db.commit()

async def get_payment(label: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM payments WHERE label = ?", (label,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT COUNT(*) as total_users,
                   SUM(CASE WHEN is_premium = 1 THEN 1 ELSE 0 END) as premium_users,
                   SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_users
            FROM users
        """) as cursor:
            return dict(await cursor.fetchone())

async def get_top_cities():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT city, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY city ORDER BY count DESC LIMIT 10") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def reset_daily_limits():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET likes_today = 0, messages_today = 0")
        await db.commit()

async def increment_stat(field: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"INSERT INTO stats (date, {field}) VALUES (CURRENT_DATE, 1) ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1")
        await db.commit()

async def get_referrals_count(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)) as cursor:
            return (await cursor.fetchone())[0]

# ==================== YOOMONEY ====================
async def create_payment_ym(amount: int, label: str, description: str = "LoveSpark Premium"):
    return (f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YOOMONEY_WALLET}&quickpay-form=shop&"
            f"targets={description}&paymentType=AC&sum={amount}&label={label}&successURL=https://t.me/LoveSparkBot")

async def check_payment_ym(label: str):
    headers = {"Authorization": f"Bearer {YOOMONEY_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"type": "deposition", "label": label, "details": "true"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{YOOMONEY_API_URL}/operation-history", headers=headers, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    for op in result.get("operations", []):
                        if op.get("label") == label and op.get("status") == "success": return True
    except Exception as e:
        logger.error(f"YooMoney API Error: {e}")
    return False

def generate_payment_label(user_id: int, tariff: str) -> str:
    return f"LS_{user_id}_{tariff}_{uuid.uuid4().hex[:8]}"

# ==================== KEYBOARDS ====================
def main_menu_kb(is_premium: bool = False):
    kb = [
        [KeyboardButton(text="❤️ Найти пару")],
        [KeyboardButton(text="📋 Моя анкета"), KeyboardButton(text="✏️ Редактировать анкету")],
        [KeyboardButton(text="💕 Мои мэтчи"), KeyboardButton(text="📊 Статистика")],
    ]
    if not is_premium:
        kb.append([KeyboardButton(text="💎 Получить Премиум")])
    else:
        kb.append([KeyboardButton(text="👑 Мой Премиум")])
    kb.append([KeyboardButton(text="❓ Помощь")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]], resize_keyboard=True)

def looking_for_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👨 Мужчин"), KeyboardButton(text="👩 Женщин")], [KeyboardButton(text="👫 Всех")]], resize_keyboard=True)

def city_kb():
    cities = CITIES[:30]
    kb = [[KeyboardButton(text=city) for city in cities[i:i+3]] for i in range(0, len(cities), 3)]
    kb.append([KeyboardButton(text="📝 Ввести свой город")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def profile_actions_kb(profile_id: int, is_premium: bool = False):
    buttons = [
        [InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{profile_id}")],
        [InlineKeyboardButton(text="💬 Написать", callback_data=f"message_{profile_id}")],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{profile_id}")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_{profile_id}")],
    ]
    if is_premium:
        buttons.insert(2, [InlineKeyboardButton(text="⭐ Супер-лайк", callback_data=f"superlike_{profile_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def match_actions_kb(match_id: int, partner_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Начать чат", callback_data=f"chat_{match_id}_{partner_id}")],
        [InlineKeyboardButton(text="👤 Посмотреть анкету", callback_data=f"view_{partner_id}")],
    ])

def chat_actions_kb(match_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Фото", callback_data="hint_photo"), InlineKeyboardButton(text="🎙️ Голосовое", callback_data="hint_voice")],
        [InlineKeyboardButton(text="🎭 Стикер", callback_data="hint_sticker")],
        [InlineKeyboardButton(text="🔙 Вернуться к мэтчам", callback_data="back_to_matches")],
    ])

def premium_kb():
    buttons = [[InlineKeyboardButton(text=f"{v['name']} - {v['price']}₽", callback_data=f"premium_{k}")] for k, v in PREMIUM_TARIFFS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def payment_kb(payment_url: str, label: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{label}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_premium")],
    ])

def edit_profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo"), InlineKeyboardButton(text="📝 Имя", callback_data="edit_name")],
        [InlineKeyboardButton(text="🔢 Возраст", callback_data="edit_age"), InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio"), InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking")],
        [InlineKeyboardButton(text="🔙 Готово", callback_data="back_menu")],
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    ])

def confirm_delete_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete")],
        [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_delete")],
    ])

# ==================== UTILITIES ====================
def generate_referral_code():
    return "LS" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_premium_status(user):
    if not user or not user.get("is_premium"): return False
    if user.get("premium_until"):
        return datetime.datetime.fromisoformat(user["premium_until"]) > datetime.datetime.now()
    return False

def format_profile(user, show_contact=False):
    gender_emoji = "👨" if user.get("gender") == "male" else "👩"
    premium_badge = "💎" if get_premium_status(user) else ""
    name, age = user.get('name', 'Неизвестно'), user.get('age', '?')
    city, bio = user.get('city', 'Не указан'), user.get('bio') or 'Нет описания'

    text = f"{gender_emoji} <b>{name}</b>, {age} {premium_badge}\n🏙️ {city}\n\n📝 {bio}\n"
    if show_contact and user.get("username"): text += f"\n📱 @{user['username']}"
    return text

def get_remaining_likes(user):
    return "∞" if get_premium_status(user) else max(0, FREE_LIKES_PER_DAY - user.get("likes_today", 0))

def get_remaining_messages(user):
    return "∞" if get_premium_status(user) else max(0, FREE_MESSAGES_PER_DAY - user.get("messages_today", 0))

async def show_user_matches(user_id: int, bot_instance: Bot, chat_id: int):
    matches = await get_matches(user_id)
    if not matches:
        await bot_instance.send_message(chat_id, "💔 У тебя пока нет мэтчей.\nСтавь лайки понравившимся людям!")
        return
    await bot_instance.send_message(chat_id, f"💕 <b>Твои мэтчи ({len(matches)}):</b>", parse_mode=ParseMode.HTML)
    for match in matches:
        partner_id = match["user2"] if match["user1"] == user_id else match["user1"]
        await bot_instance.send_photo(chat_id, photo=match["photo"],
            caption=f"💕 <b>{match['name']}</b>, {match['age']}\n🏙️ {match['city']}",
            reply_markup=match_actions_kb(match["id"], partner_id), parse_mode=ParseMode.HTML)

# ==================== HANDLERS ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user and user.get("is_active"):
        await message.answer(
            f"💘 <b>Добро пожаловать обратно в LoveSpark!</b>\n\n"
            f"✨ Начни поиск своей второй половинки прямо сейчас!\n\n"
            f"📊 Твоя статистика:\n"
            f"❤️ Лайков сегодня: {get_remaining_likes(user)}\n"
            f"💬 Сообщений сегодня: {get_remaining_messages(user)}\n",
            reply_markup=main_menu_kb(get_premium_status(user)), parse_mode=ParseMode.HTML
        )
        return

    await message.answer(
        f"💘 <b>LoveSpark - Бот знакомств</b> 💘\n\n"
        f"Привет! Я помогу тебе найти пару среди тысяч реальных анкет по всей России (включая ДНР и ЛНР)!\n\n"
        f"<b>Что я умею:</b>\n"
        f"❤️ Умный поиск по городу\n💕 Взаимные лайки и мэтчи\n💬 Чат прямо в боте\n💎 Премиум без ограничений\n\n"
        f"Как тебя зовут?", parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.name)

@dp.message(Registration.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not (2 <= len(name) <= 30):
        return await message.answer("Имя должно быть от 2 до 30 символов. Попробуй еще раз:")
    await state.update_data(name=name)
    await message.answer(f"Отлично, {name}! Сколько тебе лет?")
    await state.set_state(Registration.age)

@dp.message(Registration.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not (16 <= age <= 100): return await message.answer("Возраст должен быть от 16 до 100 лет:")
    except ValueError: return await message.answer("Введи число:")
    await state.update_data(age=age)
    await message.answer("Выбери свой город:", reply_markup=city_kb())
    await state.set_state(Registration.city)

@dp.message(Registration.city)
async def process_city(message: Message, state: FSMContext):
    if message.text == "📝 Ввести свой город":
        await message.answer("Напиши название города:")
        return await state.set_state(CityInput.waiting_city)
    await state.update_data(city=message.text.strip())
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(CityInput.waiting_city)
async def process_custom_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if not (2 <= len(city) <= 50): return await message.answer("Некорректное название. Попробуй еще:")
    await state.update_data(city=city)
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(Registration.gender)
async def process_gender(message: Message, state: FSMContext):
    gender_map = {"👨 Мужчина": "male", "👩 Женщина": "female"}
    if message.text not in gender_map: return await message.answer("Выбери из кнопок:", reply_markup=gender_kb())
    await state.update_data(gender=gender_map[message.text])
    await message.answer("Кого ты ищешь?", reply_markup=looking_for_kb())
    await state.set_state(Registration.looking_for)

@dp.message(Registration.looking_for)
async def process_looking_for(message: Message, state: FSMContext):
    look_map = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
    if message.text not in look_map: return await message.answer("Выбери из меню:", reply_markup=looking_for_kb())
    await state.update_data(looking_for=look_map[message.text])
    await message.answer("Отправь свое лучшее фото для анкеты! 📸")
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Расскажи немного о себе (хобби, цели). Это поможет найти идеальную пару!")
    await state.set_state(Registration.bio)

@dp.message(Registration.photo)
async def process_photo_error(message: Message):
    await message.answer("Пожалуйста, отправь именно ФОТО (а не файл или текст).")

@dp.message(Registration.bio)
async def process_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10: return await message.answer("Опиши себя чуть подробнее (минимум 10 символов):")
    if len(bio) > 500: return await message.answer("Текст слишком длинный (макс 500 символов):")
    await state.update_data(bio=bio)
    data = await state.get_data()

    preview = f"📋 <b>Предпросмотр анкеты:</b>\n\n{format_profile({'name': data['name'], 'age': data['age'], 'city': data['city'], 'gender': data['gender'], 'bio': data['bio']})}\n\nВсе верно?"
    await message.answer_photo(photo=data['photo'], caption=preview, parse_mode=ParseMode.HTML)
    await message.answer("Нажми /confirm для подтверждения или /cancel для отмены")
    await state.set_state(Registration.confirm)

@dp.message(Command("confirm"), Registration.confirm)
async def confirm_reg(message: Message, state: FSMContext):
    data = await state.get_data()
    ref_code = generate_referral_code()
    await create_user(message.from_user.id, message.from_user.username, data['name'], data['age'], data['city'], data['gender'], data['looking_for'], data['photo'], data['bio'], ref_code)
    await increment_stat("new_users")
    await message.answer(f"🎉 <b>Анкета создана!</b>\n\nТвой реферальный код: <code>{ref_code}</code>\nНачнем поиск?", reply_markup=main_menu_kb(False), parse_mode=ParseMode.HTML)
    await state.clear()

@dp.message(Command("cancel"), Registration.confirm)
async def cancel_reg(message: Message, state: FSMContext):
    await message.answer("Регистрация отменена. Нажми /start чтобы начать заново.")
    await state.clear()

# --- MAIN MENU LOGIC ---
@dp.message(F.text == "❤️ Найти пару")
async def find_pair(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return await message.answer("Сначала создай анкету! Нажми /start")

    if user.get("likes_today", 0) >= FREE_LIKES_PER_DAY and not get_premium_status(user):
        return await message.answer("😔 Лимит лайков исчерпан!\n\n💎 Купи Премиум для безлимита!", reply_markup=main_menu_kb(False))

    profile = await get_random_profile(message.from_user.id, user["looking_for"], user["city"])
    if not profile:
        return await message.answer("😔 Пока нет подходящих анкет. Загляни попозже!", reply_markup=main_menu_kb(get_premium_status(user)))

    await message.answer_photo(photo=profile["photo"], caption=format_profile(profile), reply_markup=profile_actions_kb(profile["telegram_id"], get_premium_status(user)), parse_mode=ParseMode.HTML)

@dp.message(F.text == "📋 Моя анкета")
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return await message.answer("Создай анкету через /start")
    premium = get_premium_status(user)
    status = "💎 Премиум" if premium else "⭐ Бесплатный"
    text = f"{format_profile(user)}\n\n📊 Статус: {status}\n❤️ Лайков сегодня: {get_remaining_likes(user)}\n💬 Сообщений сегодня: {get_remaining_messages(user)}"
    await message.answer_photo(photo=user["photo"], caption=text, reply_markup=edit_profile_kb(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "✏️ Редактировать анкету")
async def edit_profile_cmd(message: Message):
    await message.answer("Что хочешь изменить?", reply_markup=edit_profile_kb())

@dp.message(F.text == "💕 Мои мэтчи")
async def my_matches_cmd(message: Message):
    await show_user_matches(message.from_user.id, bot, message.chat.id)

@dp.message(F.text == "💎 Получить Премиум")
async def get_premium_cmd(message: Message):
    await message.answer(f"💎 <b>Премиум подписка LoveSpark</b>\n\n✅ Безлимит лайков и чатов\n✅ Поиск по всей России\n✅ Супер-лайки\n✅ Приоритет в поиске\n\nВыберите тариф:", reply_markup=premium_kb(), parse_mode=ParseMode.HTML)

# --- ACTIONS CALLBACKS ---
@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)
    if not user: return await callback.answer("Сначала создай анкету!")

    if not get_premium_status(user) and user.get("likes_today", 0) >= FREE_LIKES_PER_DAY:
        return await callback.answer("Лимит лайков исчерпан! Купи Премиум.", show_alert=True)

    is_mutual = await add_like(callback.from_user.id, profile_id)
    await update_user(callback.from_user.id, likes_today=user.get("likes_today", 0) + 1)
    await increment_stat("likes_count")

    if is_mutual:
        await increment_stat("matches_count")
        partner = await get_user(profile_id)
        await callback.message.answer(f"💕 <b>Взаимный мэтч!</b>\n\nВы и {partner['name']} понравились друг другу!", reply_markup=match_actions_kb(0, profile_id), parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(profile_id, f"💕 <b>Взаимный мэтч!</b>\n\n{user['name']} лайкнул(а) тебя в ответ!", reply_markup=match_actions_kb(0, callback.from_user.id), parse_mode=ParseMode.HTML)
        except Exception: pass
    else:
        await callback.answer("❤️ Лайк отправлен!")

    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("skip_") | F.data.startswith("block_"))
async def process_skip(callback: CallbackQuery):
    await callback.answer("Пропущено" if "skip" in callback.data else "Заблокировано")
    await callback.message.delete()
    await find_pair(callback.message)

# --- CHAT LOGIC ---
@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(callback: CallbackQuery, state: FSMContext):
    match_id, partner_id = int(callback.data.split("_")[1]), int(callback.data.split("_")[2])
    partner = await get_user(partner_id)
    await state.set_state(ChatState.chatting)
    await state.update_data(match_id=match_id, partner_id=partner_id)
    await callback.message.answer(f"💬 <b>Чат с {partner['name']}</b>\n\nПиши текст, присылай фото или голосовые. Для выхода нажми /exit", reply_markup=chat_actions_kb(match_id), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("message_"))
async def message_profile(callback: CallbackQuery, state: FSMContext):
    profile_id = int(callback.data.split("_")[1])
    match = await get_match(callback.from_user.id, profile_id)
    if not match: return await callback.answer("Сначала нужен взаимный мэтч!", show_alert=True)
    # Имитация callback для start_chat
    callback.data = f"chat_{match['id']}_{profile_id}"
    await start_chat(callback, state)

@dp.callback_query(F.data == "back_to_matches")
async def back_to_matches_from_chat(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Возвращаемся к мэтчам...")
    await show_user_matches(callback.from_user.id, bot, callback.message.chat.id)

@dp.callback_query(F.data.startswith("hint_"))
async def chat_media_hints(callback: CallbackQuery):
    hints = {"photo": "📸 Отправь фото прямо в чат!", "voice": "🎙 Запиши голосовое сообщение в этот чат!", "sticker": "🎭 Отправь стикер в чат!"}
    media_type = callback.data.split("_")[1]
    await callback.answer(hints.get(media_type, "Просто отправьте это в чат!"), show_alert=True)

@dp.message(ChatState.chatting)
async def chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("match_id"): return await state.clear()
    
    user = await get_user(message.from_user.id)
    if not get_premium_status(user) and user.get("messages_today", 0) >= FREE_MESSAGES_PER_DAY:
        return await message.answer("😔 Лимит сообщений исчерпан! Купи Премиум.")

    content, content_type, file_id = message.text or "[Вложение]", "text", None
    if message.photo: content_type, file_id = "photo", message.photo[-1].file_id
    elif message.voice: content_type, file_id = "voice", message.voice.file_id
    elif message.sticker: content_type, file_id = "sticker", message.sticker.file_id

    await add_message(data["match_id"], message.from_user.id, content_type, content, file_id)
    if not get_premium_status(user): await update_user(message.from_user.id, messages_today=user.get("messages_today", 0) + 1)

    try:
        if content_type == "text": await bot.send_message(data["partner_id"], f"💬 {user['name']}: {content}")
        elif content_type == "photo": await bot.send_photo(data["partner_id"], photo=file_id, caption=f"📸 {user['name']}")
        elif content_type == "voice": await bot.send_voice(data["partner_id"], voice=file_id, caption=f"🎙 {user['name']}")
        elif content_type == "sticker": await bot.send_sticker(data["partner_id"], sticker=file_id)
    except Exception: await message.answer("Не удалось отправить. Возможно, пользователь заблокировал бота.")

@dp.message(Command("exit"), ChatState.chatting)
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    await message.answer("🔙 Ты вышел из чата.", reply_markup=main_menu_kb(get_premium_status(user)))

# --- PREMIUM CALLBACKS ---
@dp.callback_query(F.data.startswith("premium_"))
async def process_premium_select(callback: CallbackQuery):
    tariff = PREMIUM_TARIFFS.get(callback.data.split("_")[1])
    if not tariff: return
    label = generate_payment_label(callback.from_user.id, callback.data.split("_")[1])
    await add_payment(callback.from_user.id, callback.data.split("_")[1], tariff["price"], label)
    pay_url = await create_payment_ym(tariff["price"], label, f"LoveSpark Premium - {tariff['name']}")
    await callback.message.answer(f"💎 <b>{tariff['name']}</b>\n\n💰 К оплате: {tariff['price']}₽", reply_markup=payment_kb(pay_url, label), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: CallbackQuery):
    label = callback.data.split("_", 2)[2]
    if await check_payment_ym(label):
        payment = await get_payment(label)
        if payment and payment["status"] != "paid":
            await update_payment(label, "paid")
            days = PREMIUM_TARIFFS[payment["tariff"]]["days"]
            await update_user(payment["user_id"], is_premium=1, premium_until=(datetime.datetime.now() + datetime.timedelta(days=days)).isoformat())
            await callback.message.answer("🎉 <b>Оплата прошла успешно! Премиум активирован!</b>", reply_markup=main_menu_kb(True), parse_mode=ParseMode.HTML)
    else:
        await callback.answer("⏳ Платеж еще не поступил. Подождите пару минут.", show_alert=True)

# --- ADMIN PANEL ---
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🔧 <b>Админ-панель LoveSpark</b>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

# ==================== CRON ====================
async def reset_limits():
    while True:
        now = datetime.datetime.now()
        next_reset = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0)
        await asyncio.sleep((next_reset - now).total_seconds())
        await reset_daily_limits()

# ==================== RUN ====================
async def main():
    await init_db()
    asyncio.create_task(reset_limits())
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
