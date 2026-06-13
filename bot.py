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
    "week": {
        "name": "⚡ Премиум на 7 дней",
        "price": 149,
        "days": 7,
        "description": "Пробный период с полным доступом"
    },
    "month": {
        "name": "💎 Премиум на 30 дней",
        "price": 399,
        "days": 30,
        "description": "Оптимальный вариант для знакомств"
    },
    "quarter": {
        "name": "👑 Премиум на 90 дней",
        "price": 999,
        "days": 90,
        "description": "Выгодный тариф с экономией 25%"
    },
    "year": {
        "name": "🏆 Премиум на 365 дней",
        "price": 2999,
        "days": 365,
        "description": "Максимальная выгода - экономия 50%"
    }
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
    "Курск", "Иваново", "Магнитогорск", "Улан-Уде", "Тверь",
    "Ставрополь", "Симферополь", "Севастополь", "Донецк", "Луганск",
    "Макеевка", "Горловка", "Мариуполь", "Алчевск",
    "Сочи", "Архангельск", "Вологда", "Калуга", "Смоленск",
    "Орёл", "Белгород", "Владимир", "Сургут", "Нижневартовск",
    "Стерлитамак", "Нефтекамск", "Салават", "Ноябрьск", "Новый Уренгой",
    "Мурманск", "Петрозаводск", "Сыктывкар", "Йошкар-Ола", "Черкесск",
    "Нальчик", "Владикавказ", "Грозный", "Назрань", "Элиста",
    "Абакан", "Кызыл", "Горно-Алтайск", "Анапа", "Геленджик",
    "Новороссийск", "Туапсе", "Таганрог", "Шахты", "Волгодонск",
    "Новочеркасск", "Батайск", "Азов", "Каменск-Шахтинский", "Сальск",
    "Миллерово", "Морозовск"
]

GENDERS = {"male": "👨 Мужчина", "female": "👩 Женщина"}
LOOKING_FOR = {"male": "👨 Мужчин", "female": "👩 Женщин", "both": "👫 Всех"}

BOT_NAME = "LoveSpark"
BOT_DESCRIPTION = """💘 LoveSpark - Бот знакомств для всех городов России, ДНР и ЛНР!

✨ Найди свою вторую половинку среди тысяч реальных анкет
🎯 Умный подбор по интересам и городу
💎 Премиум-функции для максимального результата

🔥 Каждый день новые знакомства!"""

DB_NAME = "lovespark.db"
YOOMONEY_API_URL = "https://yoomoney.ru/api"

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
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
    waiting_photo = State()
    waiting_voice = State()

class AdminState(StatesGroup):
    broadcast = State()
    ban_user = State()
    send_message = State()

class CityInput(StatesGroup):
    waiting_city = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
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
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL,
                is_mutual INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_user, to_user)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1 INTEGER NOT NULL,
                user2 INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user1, user2)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content TEXT NOT NULL,
                file_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL,
                amount INTEGER NOT NULL,
                label TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT "pending",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(referred_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE DEFAULT CURRENT_DATE,
                new_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0,
                likes_count INTEGER DEFAULT 0,
                matches_count INTEGER DEFAULT 0,
                payments_count INTEGER DEFAULT 0,
                revenue INTEGER DEFAULT 0
            )
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
        if not user:
            return None

        query = """
            SELECT * FROM users
            WHERE telegram_id != ?
            AND is_active = 1
            AND is_banned = 0
            AND telegram_id NOT IN (
                SELECT to_user FROM likes WHERE from_user = ?
            )
            AND telegram_id NOT IN (
                SELECT user2 FROM matches WHERE user1 = ?
                UNION
                SELECT user1 FROM matches WHERE user2 = ?
            )
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
        async with db.execute(
            "SELECT * FROM likes WHERE from_user = ? AND to_user = ?",
            (to_user, from_user)
        ) as cursor:
            mutual = await cursor.fetchone()

        await db.execute(
            "INSERT OR IGNORE INTO likes (from_user, to_user, is_mutual) VALUES (?, ?, ?)",
            (from_user, to_user, 1 if mutual else 0)
        )

        if mutual:
            await db.execute(
                "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
                (min(from_user, to_user), max(from_user, to_user))
            )
            await db.execute(
                "UPDATE likes SET is_mutual = 1 WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)",
                (from_user, to_user, to_user, from_user)
            )

        await db.commit()
        return mutual is not None

async def get_match(user1: int, user2: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)",
            (user1, user2, user2, user1)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_matches(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.*, u.name, u.username, u.photo
            FROM matches m
            JOIN users u ON (u.telegram_id = CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END)
            WHERE m.user1 = ? OR m.user2 = ?
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def add_message(match_id: int, from_user: int, content_type: str, content: str, file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO messages (match_id, from_user, content_type, content, file_id) VALUES (?, ?, ?, ?, ?)",
            (match_id, from_user, content_type, content, file_id)
        )
        await db.commit()

async def add_payment(user_id: int, tariff: str, amount: int, label: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO payments (user_id, tariff, amount, label) VALUES (?, ?, ?, ?)",
            (user_id, tariff, amount, label)
        )
        await db.commit()

async def update_payment(label: str, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE payments SET status = ?, paid_at = ? WHERE label = ?",
            (status, datetime.datetime.now().isoformat(), label)
        )
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
            SELECT
                COUNT(*) as total_users,
                SUM(CASE WHEN is_premium = 1 THEN 1 ELSE 0 END) as premium_users,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_users
            FROM users
        """) as cursor:
            return dict(await cursor.fetchone())

async def get_top_cities():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT city, COUNT(*) as count FROM users
            WHERE is_active = 1
            GROUP BY city
            ORDER BY count DESC
            LIMIT 10
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def reset_daily_limits():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET likes_today = 0, messages_today = 0")
        await db.commit()

async def increment_stat(field: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"""
            INSERT INTO stats (date, {field})
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1
        """)
        await db.commit()

async def get_referrals_count(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0]

async def add_referral(referrer_id: int, referred_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
            (referrer_id, referred_id)
        )
        await db.commit()

# ==================== YOOMONEY ====================
async def create_payment_ym(amount: int, label: str, description: str = "LoveSpark Premium"):
    payment_url = (
        f"https://yoomoney.ru/quickpay/confirm.xml?"
        f"receiver={YOOMONEY_WALLET}&"
        f"quickpay-form=shop&"
        f"targets={description}&"
        f"paymentType=AC&"
        f"sum={amount}&"
        f"label={label}&"
        f"successURL=https://t.me/LoveSparkBot"
    )
    return payment_url

async def check_payment_ym(label: str):
    headers = {
        "Authorization": f"Bearer {YOOMONEY_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"type": "deposition", "label": label, "details": "true"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{YOOMONEY_API_URL}/operation-history",
            headers=headers,
            data=data
        ) as response:
            if response.status == 200:
                result = await response.json()
                operations = result.get("operations", [])
                for op in operations:
                    if op.get("label") == label and op.get("status") == "success":
                        return True
            return False

def generate_payment_label(user_id: int, tariff: str) -> str:
    return f"LS_{user_id}_{tariff}_{uuid.uuid4().hex[:8]}"

# ==================== KEYBOARDS ====================
def main_menu_kb(is_premium: bool = False):
    kb = [
        [KeyboardButton(text="💘 Найти пару")],
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
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]],
        resize_keyboard=True
    )

def looking_for_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👨 Мужчин"), KeyboardButton(text="👩 Женщин")],
            [KeyboardButton(text="👫 Всех")]
        ],
        resize_keyboard=True
    )

def city_kb():
    cities = CITIES[:30]
    kb = []
    for i in range(0, len(cities), 3):
        row = [KeyboardButton(text=city) for city in cities[i:i+3]]
        kb.append(row)
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Начать чат", callback_data=f"chat_{match_id}_{partner_id}")],
            [InlineKeyboardButton(text="👤 Посмотреть анкету", callback_data=f"view_{partner_id}")],
        ]
    )

def chat_actions_kb(match_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 Фото", callback_data=f"send_photo_{match_id}")],
            [InlineKeyboardButton(text="🎙️ Голосовое", callback_data=f"send_voice_{match_id}")],
            [InlineKeyboardButton(text="🎭 Стикер", callback_data=f"send_sticker_{match_id}")],
            [InlineKeyboardButton(text="🔙 Вернуться к мэтчам", callback_data="back_to_matches")],
        ]
    )

def premium_kb():
    buttons = []
    for key, tariff in PREMIUM_TARIFFS.items():
        buttons.append([
            InlineKeyboardButton(
                text=f"{tariff['name']} - {tariff['price']}₽",
                callback_data=f"premium_{key}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def payment_kb(payment_url: str, label: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{label}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_premium")],
        ]
    )

def edit_profile_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo")],
            [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="🔢 Возраст", callback_data="edit_age")],
            [InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city")],
            [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio")],
            [InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking")],
            [InlineKeyboardButton(text="🔙 Готово", callback_data="back_menu")],
        ]
    )

def admin_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="💰 Платежи", callback_data="admin_payments")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🚫 Бан", callback_data="admin_ban")],
        ]
    )

def confirm_delete_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete")],
            [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_delete")],
        ]
    )

def back_to_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_menu")],
        ]
    )

# ==================== UTILITIES ====================
def generate_referral_code():
    return "LS" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_premium_status(user):
    if not user.get("is_premium"):
        return False
    if user.get("premium_until"):
        until = datetime.datetime.fromisoformat(user["premium_until"])
        if until > datetime.datetime.now():
            return True
    return False

def format_profile(user, show_contact=False):
    gender_emoji = "👨" if user["gender"] == "male" else "👩"
    premium_badge = "💎" if get_premium_status(user) else ""
    text = f"""{gender_emoji} <b>{user['name']}</b>, {user['age']} {premium_badge}
🏙️ {user['city']}

📝 {user['bio'] or 'Нет описания'}
"""
    if show_contact and user.get("username"):
        text += f"
📱 @{user['username']}"
    return text

def get_remaining_likes(user):
    if get_premium_status(user):
        return "∞"
    return max(0, FREE_LIKES_PER_DAY - user.get("likes_today", 0))

def get_remaining_messages(user):
    if get_premium_status(user):
        return "∞"
    return max(0, FREE_MESSAGES_PER_DAY - user.get("messages_today", 0))

# ==================== HANDLERS ====================

# --- START & REGISTRATION ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)

    if user and user.get("is_active"):
        await message.answer(
            f"""💘 <b>Добро пожаловать в LoveSpark!</b>

✨ Ты уже зарегистрирован!
🔥 Начни поиск своей второй половинки прямо сейчас!

📊 Твоя статистика:
❤️ Лайков сегодня: {get_remaining_likes(user)}
💬 Сообщений сегодня: {get_remaining_messages(user)}
""",
            reply_markup=main_menu_kb(get_premium_status(user)),
            parse_mode=ParseMode.HTML
        )
        return

    welcome_text = """💘 <b>LoveSpark - Бот знакомств</b> 💘

Привет! Я помогу тебе найти свою вторую половинку среди тысяч реальных анкет по всей России, включая ДНР и ЛНР!

<b>Что умеет бот:</b>
❤️ Умный поиск по городу и интересам
💕 Взаимные лайки и мэтчи
💬 Чат с совпадениями
💎 Премиум-функции без ограничений

Давай создадим твою анкету!"""

    await message.answer(welcome_text, parse_mode=ParseMode.HTML)
    await message.answer("Как тебя зовут? (напиши свое имя)")
    await state.set_state(Registration.name)

@dp.message(Registration.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("Имя должно быть от 2 до 30 символов. Попробуй еще раз:")
        return
    await state.update_data(name=name)
    await message.answer(f"Отлично, {name}! Сколько тебе лет?")
    await state.set_state(Registration.age)

@dp.message(Registration.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 16 or age > 100:
            await message.answer("Возраст должен быть от 16 до 100 лет. Попробуй еще раз:")
            return
    except ValueError:
        await message.answer("Пожалуйста, введи число (твой возраст):")
        return
    await state.update_data(age=age)
    await message.answer("Выбери свой город:", reply_markup=city_kb())
    await state.set_state(Registration.city)

@dp.message(Registration.city)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if city == "📝 Ввести свой город":
        await message.answer("Напиши название своего города:")
        await state.set_state(CityInput.waiting_city)
        return
    await state.update_data(city=city)
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(CityInput.waiting_city)
async def process_custom_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        await message.answer("Название города слишком короткое или длинное. Попробуй еще раз:")
        return
    await state.update_data(city=city)
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(Registration.gender)
async def process_gender(message: Message, state: FSMContext):
    gender_map = {"👨 Мужчина": "male", "👩 Женщина": "female"}
    gender = gender_map.get(message.text)
    if not gender:
        await message.answer("Пожалуйста, выбери пол из предложенных вариантов:", reply_markup=gender_kb())
        return
    await state.update_data(gender=gender)
    await message.answer("Кого ты ищешь?", reply_markup=looking_for_kb())
    await state.set_state(Registration.looking_for)

@dp.message(Registration.looking_for)
async def process_looking_for(message: Message, state: FSMContext):
    looking_map = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
    looking_for = looking_map.get(message.text)
    if not looking_for:
        await message.answer("Пожалуйста, выбери вариант из меню:", reply_markup=looking_for_kb())
        return
    await state.update_data(looking_for=looking_for)
    await message.answer("Отправь свое фото для анкеты (можно селфи). Это обязательно!")
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)
    await message.answer(
        "Расскажи немного о себе (хобби, интересы, кого хочешь найти). Это поможет найти подходящего человека!"
    )
    await state.set_state(Registration.bio)

@dp.message(Registration.photo)
async def process_photo_error(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, отправь фото (не файл, а именно фото):")

@dp.message(Registration.bio)
async def process_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10:
        await message.answer("Описание слишком короткое. Расскажи побольше о себе (минимум 10 символов):")
        return
    if len(bio) > 500:
        await message.answer("Описание слишком длинное (максимум 500 символов). Попробуй сократить:")
        return
    await state.update_data(bio=bio)
    data = await state.get_data()

    preview = f"""📋 <b>Предпросмотр твоей анкеты:</b>

{format_profile({
    'name': data['name'], 'age': data['age'], 'city': data['city'],
    'gender': data['gender'], 'bio': data['bio'], 'is_premium': 0
})}

Все верно?"""

    await message.answer_photo(photo=data['photo'], caption=preview, parse_mode=ParseMode.HTML)
    await message.answer("Нажми /confirm для подтверждения или /cancel для отмены")
    await state.set_state(Registration.confirm)

@dp.message(Command("confirm"), Registration.confirm)
async def confirm_registration(message: Message, state: FSMContext):
    data = await state.get_data()
    ref_code = generate_referral_code()

    await create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        name=data['name'],
        age=data['age'],
        city=data['city'],
        gender=data['gender'],
        looking_for=data['looking_for'],
        photo=data['photo'],
        bio=data['bio'],
        referral_code=ref_code
    )
    await increment_stat("new_users")

    await message.answer(
        f"""🎉 <b>Анкета создана!</b>

💘 Добро пожаловать в LoveSpark!
Твой реферальный код: <code>{ref_code}</code>

Теперь ты можешь:
❤️ Искать пары
💕 Смотреть мэтчи
💎 Получить Премиум

Начнем?""",
        reply_markup=main_menu_kb(False),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.message(Command("cancel"), Registration.confirm)
async def cancel_registration(message: Message, state: FSMContext):
    await message.answer("Регистрация отменена. Нажми /start чтобы начать заново.")
    await state.clear()

# --- MAIN MENU ---
@dp.message(F.text == "💘 Найти пару")
async def find_pair(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала создай анкету! Нажми /start")
        return

    if user.get("likes_today", 0) >= FREE_LIKES_PER_DAY and not get_premium_status(user):
        await message.answer(
            f"""😔 Ты исчерпал лимит лайков на сегодня!

💎 Получи Премиум для безлимитных лайков:
• Без ограничений на лайки
• Чат без ограничений
• Поиск по всей России
• Супер-лайки

Нажми "💎 Получить Премиум" в меню!""",
            reply_markup=main_menu_kb(False)
        )
        return

    profile = await get_random_profile(message.from_user.id, user["looking_for"], user["city"])
    if not profile:
        await message.answer(
            "😔 Пока нет подходящих анкет. Попробуй позже или расширь критерии поиска!",
            reply_markup=main_menu_kb(get_premium_status(user))
        )
        return

    await message.answer_photo(
        photo=profile["photo"],
        caption=format_profile(profile),
        reply_markup=profile_actions_kb(profile["telegram_id"], get_premium_status(user)),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📋 Моя анкета")
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала создай анкету! Нажми /start")
        return

    premium = get_premium_status(user)
    status = "💎 Премиум" if premium else "⭐ Бесплатный"
    text = format_profile(user) + f"

📊 Статус: {status}"
    text += f"
❤️ Лайков сегодня: {get_remaining_likes(user)}"
    text += f"
💬 Сообщений сегодня: {get_remaining_messages(user)}"
    text += f"
👥 Приглашено друзей: {await get_referrals_count(message.from_user.id)}"

    await message.answer_photo(
        photo=user["photo"],
        caption=text,
        reply_markup=edit_profile_kb(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "✏️ Редактировать анкету")
async def edit_profile(message: Message):
    await message.answer("Что хочешь изменить?", reply_markup=edit_profile_kb())

@dp.message(F.text == "💕 Мои мэтчи")
async def my_matches(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала создай анкету! Нажми /start")
        return

    matches = await get_matches(message.from_user.id)
    if not matches:
        await message.answer(
            "💔 У тебя пока нет мэтчей.

"
            "Ставь лайки понравившимся людям, и когда взаимность случится - "
            "ты сможешь начать общение!",
            reply_markup=main_menu_kb(get_premium_status(user))
        )
        return

    await message.answer(f"💕 <b>Твои мэтчи ({len(matches)}):</b>", parse_mode=ParseMode.HTML)
    for match in matches:
        partner_id = match["user2"] if match["user1"] == message.from_user.id else match["user1"]
        partner = await get_user(partner_id)
        if partner:
            await message.answer_photo(
                photo=partner["photo"],
                caption=f"💕 <b>{partner['name']}</b>, {partner['age']}
🏙️ {partner['city']}",
                reply_markup=match_actions_kb(match["id"], partner_id),
                parse_mode=ParseMode.HTML
            )

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: Message):
    stats = await get_stats()
    top_cities = await get_top_cities()
    cities_text = "
".join([f"{i+1}. {c['city']} - {c['count']} чел." for i, c in enumerate(top_cities[:5])])

    text = f"""📊 <b>Статистика LoveSpark</b>

👥 Всего пользователей: {stats['total_users']}
💎 Премиум пользователей: {stats['premium_users']}
🔥 Активных сегодня: {stats['active_users']}

🏙️ <b>Топ городов:</b>
{cities_text}

💘 Найди свою любовь среди них!"""

    user = await get_user(message.from_user.id)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(
        get_premium_status(user) if user else False
    ))

@dp.message(F.text == "💎 Получить Премиум")
async def get_premium_cmd(message: Message):
    await message.answer(
        f"""💎 <b>Премиум подписка LoveSpark</b>

<b>Что включено:</b>
✅ Безлимитные лайки
✅ Безлимитные сообщения
✅ Поиск по всей России (не только твой город)
✅ Супер-лайки (увеличивают шансы на мэтч)
✅ Приоритет в поиске
✅ Видно кто лайкнул твою анкету

<b>Выбери тариф:</b>""",
        reply_markup=premium_kb(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👑 Мой Премиум")
async def my_premium(message: Message):
    user = await get_user(message.from_user.id)
    if not user or not get_premium_status(user):
        await message.answer("У тебя нет активной Премиум подписки.", reply_markup=main_menu_kb(False))
        return

    until = datetime.datetime.fromisoformat(user["premium_until"])
    days_left = (until - datetime.datetime.now()).days

    await message.answer(
        f"""👑 <b>Твой Премиум</b>

💎 Статус: Активен
📅 До: {until.strftime('%d.%m.%Y')}
⏳ Осталось: {days_left} дней

Все функции доступны!""",
        reply_markup=main_menu_kb(True),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: Message):
    text = f"""❓ <b>Помощь по LoveSpark</b>

<b>Как пользоваться:</b>
1. Создай анкету через /start
2. Нажми "💘 Найти пару" и листай анкеты
3. Ставь ❤️ лайки понравившимся людям
4. При взаимном лайке получишь мэтч и сможешь писать

<b>Команды:</b>
/start - Начать / Перезапустить
/menu - Главное меню
/premium - Премиум подписка
/delete - Удалить анкету

<b>Ограничения бесплатного аккаунта:</b>
• {FREE_LIKES_PER_DAY} лайков в день
• {FREE_MESSAGES_PER_DAY} сообщений в день
• Поиск только по своему городу

<b>Премиум снимает все ограничения!</b>

<b>Поддержка:</b>
По вопросам пиши администратору.
"""
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- CALLBACKS ---
@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)

    if not user:
        await callback.answer("Сначала создай анкету!")
        return

    if not get_premium_status(user) and user.get("likes_today", 0) >= FREE_LIKES_PER_DAY:
        await callback.answer("Лимит лайков исчерпан! Получи Премиум.")
        return

    is_mutual = await add_like(callback.from_user.id, profile_id)
    await update_user(callback.from_user.id, likes_today=user.get("likes_today", 0) + 1)
    await increment_stat("likes_count")

    if is_mutual:
        await increment_stat("matches_count")
        partner = await get_user(profile_id)

        await callback.message.answer(
            f"""💕 <b>Ура! Новый мэтч!</b>

Ты и {partner['name']} понравились друг другу!
Теперь вы можете общаться.""",
            reply_markup=match_actions_kb(0, profile_id),
            parse_mode=ParseMode.HTML
        )

        try:
            await bot.send_message(
                profile_id,
                f"""💕 <b>Ура! Новый мэтч!</b>

{user['name']} лайкнул тебя в ответ!
Теперь вы можете общаться.""",
                reply_markup=match_actions_kb(0, callback.from_user.id),
                parse_mode=ParseMode.HTML
            )
            await bot.send_photo(profile_id, photo=user["photo"], caption=format_profile(user))
        except Exception as e:
            logger.error(f"Failed to notify partner: {e}")
    else:
        await callback.answer("❤️ Лайк отправлен!")

    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("superlike_"))
async def process_superlike(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)

    if not get_premium_status(user):
        await callback.answer("Супер-лайки доступны только для Премиум!")
        return

    is_mutual = await add_like(callback.from_user.id, profile_id)
    await increment_stat("likes_count")

    if is_mutual:
        await increment_stat("matches_count")
        partner = await get_user(profile_id)
        await callback.message.answer(
            f"""⭐ <b>Супер-мэтч!</b>

Твой супер-лайк сработал! Ты и {partner['name']} - мэтч!""",
            reply_markup=match_actions_kb(0, profile_id),
            parse_mode=ParseMode.HTML
        )
        try:
            await bot.send_message(
                profile_id,
                f"""⭐ <b>Супер-мэтч!</b>

{user['name']} поставил тебе супер-лайк!
Вы - мэтч!""",
                reply_markup=match_actions_kb(0, callback.from_user.id),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to notify partner: {e}")
    else:
        await callback.answer("⭐ Супер-лайк отправлен! Пользователь узнает о тебе первым делом!")

    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("skip_"))
async def process_skip(callback: CallbackQuery):
    await callback.answer("👎 Пропущено")
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("block_"))
async def process_block(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    await callback.answer("🚫 Пользователь заблокирован")
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    match_id = int(parts[1])
    partner_id = int(parts[2])
    partner = await get_user(partner_id)

    await state.set_state(ChatState.chatting)
    await state.update_data(match_id=match_id, partner_id=partner_id)

    await callback.message.answer(
        f"""💬 <b>Чат с {partner['name']}</b>

Теперь ты можешь отправлять:
• Текстовые сообщения
• Фото
• Голосовые сообщения
• Стикеры

Для выхода из чата нажми /exit""",
        reply_markup=chat_actions_kb(match_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(ChatState.chatting)
async def chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    match_id = data.get("match_id")
    partner_id = data.get("partner_id")

    if not match_id or not partner_id:
        await message.answer("Ошибка чата. Вернись в мэтчи.")
        await state.clear()
        return

    user = await get_user(message.from_user.id)
    if not get_premium_status(user) and user.get("messages_today", 0) >= FREE_MESSAGES_PER_DAY:
        await message.answer("😔 Лимит сообщений исчерпан! Получи Премиум для безлимитного общения.")
        return

    content_type = "text"
    content = message.text or ""
    file_id = None

    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        content = message.caption or "[Фото]"
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
        content = "[Голосовое сообщение]"
    elif message.sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
        content = "[Стикер]"
    elif message.video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id
        content = "[Видео-сообщение]"
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        content = message.caption or "[Видео]"

    await add_message(match_id, message.from_user.id, content_type, content, file_id)
    if not get_premium_status(user):
        await update_user(message.from_user.id, messages_today=user.get("messages_today", 0) + 1)

    try:
        if content_type == "text":
            await bot.send_message(partner_id, f"💬 {user['name']}: {content}")
        elif content_type == "photo":
            await bot.send_photo(partner_id, photo=file_id, caption=f"📸 {user['name']}: {content}")
        elif content_type == "voice":
            await bot.send_voice(partner_id, voice=file_id, caption=f"🎙️ {user['name']}")
        elif content_type == "sticker":
            await bot.send_sticker(partner_id, sticker=file_id)
        elif content_type == "video_note":
            await bot.send_video_note(partner_id, video_note=file_id)
        elif content_type == "video":
            await bot.send_video(partner_id, video=file_id, caption=f"🎬 {user['name']}: {content}")
    except Exception as e:
        logger.error(f"Failed to forward message: {e}")
        await message.answer("Не удалось отправить сообщение. Возможно, пользователь заблокировал бота.")

@dp.message(Command("exit"), ChatState.chatting)
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    await message.answer(
        "🔙 Ты вышел из чата.",
        reply_markup=main_menu_kb(get_premium_status(user) if user else False)
    )

# --- PREMIUM CALLBACKS ---
@dp.callback_query(F.data.startswith("premium_"))
async def process_premium_select(callback: CallbackQuery):
    tariff_key = callback.data.split("_")[1]
    tariff = PREMIUM_TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Ошибка выбора тарифа")
        return

    label = generate_payment_label(callback.from_user.id, tariff_key)
    await add_payment(callback.from_user.id, tariff_key, tariff["price"], label)
    payment_url = await create_payment_ym(tariff["price"], label, f"LoveSpark Premium - {tariff['name']}")

    await callback.message.answer(
        f"""💎 <b>{tariff['name']}</b>

💰 Стоимость: {tariff['price']}₽
📅 Срок: {tariff['days']} дней
📝 {tariff['description']}

Нажми кнопку ниже для оплаты:""",
        reply_markup=payment_kb(payment_url, label),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: CallbackQuery):
    label = callback.data.split("_", 2)[2]
    is_paid = await check_payment_ym(label)

    if is_paid:
        payment = await get_payment(label)
        if payment and payment["status"] != "paid":
            await update_payment(label, "paid")
            tariff = PREMIUM_TARIFFS[payment["tariff"]]
            premium_until = datetime.datetime.now() + datetime.timedelta(days=tariff["days"])
            await update_user(
                payment["user_id"],
                is_premium=1,
                premium_until=premium_until.isoformat()
            )
            await increment_stat("payments_count")
            await increment_stat("revenue")

            await callback.message.answer(
                f"""🎉 <b>Оплата прошла успешно!</b>

💎 Премиум активирован!
📅 Действует до: {premium_until.strftime('%d.%m.%Y')}

Все ограничения сняты! Приятного общения!""",
                reply_markup=main_menu_kb(True),
                parse_mode=ParseMode.HTML
            )
    else:
        await callback.answer("⏳ Платеж еще не поступил. Попробуй проверить позже.")

@dp.callback_query(F.data == "back_premium")
async def back_to_premium(callback: CallbackQuery):
    await get_premium_cmd(callback.message)

# --- EDIT PROFILE ---
@dp.callback_query(F.data.startswith("edit_"))
async def process_edit(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    field_names = {
        "photo": "📸 Отправь новое фото:",
        "name": "📝 Введи новое имя:",
        "age": "🔢 Введи новый возраст:",
        "city": "🏙️ Выбери новый город:",
        "bio": "📝 Напиши новое описание:",
        "looking": "👀 Кого ты ищешь?"
    }
    await state.update_data(edit_field=field)
    await state.set_state(EditProfile.new_value)
    if field == "city":
        await callback.message.answer(field_names[field], reply_markup=city_kb())
    elif field == "looking":
        await callback.message.answer(field_names[field], reply_markup=looking_for_kb())
    else:
        await callback.message.answer(field_names[field])

@dp.message(EditProfile.new_value)
async def process_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Ошибка. Нажми /start")
        await state.clear()
        return

    if field == "photo":
        if not message.photo:
            await message.answer("Пожалуйста, отправь фото:")
            return
        await update_user(message.from_user.id, photo=message.photo[-1].file_id)
    elif field == "name":
        name = message.text.strip()
        if len(name) < 2 or len(name) > 30:
            await message.answer("Имя от 2 до 30 символов. Попробуй еще:")
            return
        await update_user(message.from_user.id, name=name)
    elif field == "age":
        try:
            age = int(message.text.strip())
            if age < 16 or age > 100:
                await message.answer("Возраст от 16 до 100. Попробуй еще:")
                return
            await update_user(message.from_user.id, age=age)
        except ValueError:
            await message.answer("Введи число:")
            return
    elif field == "city":
        city = message.text.strip()
        await update_user(message.from_user.id, city=city)
    elif field == "bio":
        bio = message.text.strip()
        if len(bio) > 500:
            await message.answer("Максимум 500 символов. Попробуй сократить:")
            return
        await update_user(message.from_user.id, bio=bio)
    elif field == "looking":
        looking_map = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
        looking_for = looking_map.get(message.text)
        if not looking_for:
            await message.answer("Выбери из меню:", reply_markup=looking_for_kb())
            return
        await update_user(message.from_user.id, looking_for=looking_for)

    await message.answer("✅ Изменения сохранены!", reply_markup=main_menu_kb(get_premium_status(user)))
    await state.clear()

# --- ADMIN ---
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У тебя нет доступа к админ-панели.")
        return
    await message.answer(
        "🔧 <b>Админ-панель LoveSpark</b>",
        reply_markup=admin_kb(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    stats = await get_stats()
    await callback.message.answer(
        f"""📊 <b>Статистика:</b>
Всего пользователей: {stats['total_users']}
Премиум: {stats['premium_users']}
Активных: {stats['active_users']}""",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    await callback.message.answer("Введи текст рассылки для всех пользователей:")
    await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    await message.answer("📢 Рассылка отправлена! (в демо-версии)")
    await state.clear()

# --- OTHER COMMANDS ---
@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    user = await get_user(message.from_user.id)
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_kb(get_premium_status(user) if user else False)
    )

@dp.message(Command("delete"))
async def delete_profile(message: Message):
    await message.answer(
        "⚠️ Ты уверен, что хочешь удалить свою анкету? Это действие нельзя отменить!",
        reply_markup=confirm_delete_kb()
    )

@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery):
    await update_user(callback.from_user.id, is_active=0)
    await callback.message.answer(
        "😢 Твоя анкета удалена. Нажми /start если захочешь вернуться!"
    )

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    await callback.answer("Анкета сохранена!")
    user = await get_user(callback.from_user.id)
    await callback.message.answer(
        "Рад, что ты остаешься с нами!",
        reply_markup=main_menu_kb(get_premium_status(user) if user else False)
    )

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu_kb(get_premium_status(user) if user else False)
    )

@dp.callback_query(F.data.startswith("view_"))
async def view_profile(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    profile = await get_user(profile_id)
    if profile:
        await callback.message.answer_photo(
            photo=profile["photo"],
            caption=format_profile(profile),
            parse_mode=ParseMode.HTML
        )

@dp.callback_query(F.data.startswith("message_"))
async def message_profile(callback: CallbackQuery):
    profile_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)
    profile = await get_user(profile_id)
    if not user or not profile:
        await callback.answer("Ошибка")
        return
    match = await get_match(callback.from_user.id, profile_id)
    if not match:
        await callback.answer("Сначала нужен мэтч! Поставь лайк и дождись взаимности.")
        return
    await start_chat(callback, state)

# ==================== SCHEDULED TASKS ====================
async def reset_limits():
    while True:
        now = datetime.datetime.now()
        next_reset = now.replace(hour=0, minute=0, second=0) + datetime.timedelta(days=1)
        sleep_seconds = (next_reset - now).total_seconds()
        await asyncio.sleep(sleep_seconds)
        await reset_daily_limits()
        logger.info("Daily limits reset")

# ==================== MAIN ====================
async def main():
    await init_db()
    logger.info("Database initialized")
    asyncio.create_task(reset_limits())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
