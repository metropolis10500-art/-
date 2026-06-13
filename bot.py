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
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
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
REFERRAL_BONUS_LIKES = 5
REFERRAL_BONUS_MSGS = 5
DAILY_BONUS_LIKES = 3
DAILY_BONUS_MSGS = 2

PREMIUM_TARIFFS = {
    "week": {"name": "⚡ Премиум на 7 дней", "price": 149, "days": 7, "description": "Пробный период с полным доступом"},
    "month": {"name": "💎 Премиум на 30 дней", "price": 399, "days": 30, "description": "Оптимальный вариант для знакомств"},
    "quarter": {"name": "👑 Премиум на 90 дней", "price": 999, "days": 90, "description": "Экономия 25%"},
    "year": {"name": "🏆 Премиум на 365 дней", "price": 2999, "days": 365, "description": "Экономия 50%"}
}

CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград",
    "Краснодар", "Саратов", "Тюмень", "Тольятти", "Ижевск",
    "Барнаул", "Иркутск", "Хабаровск", "Ярославль", "Владивосток",
    "Махачкала", "Томск", "Оренбург", "Кемерово", "Новокузнецк"
]

BOT_NAME = "LoveSpark"
BOT_DESCRIPTION = "Бот знакомств для всех городов России"
DB_NAME = "lovespark.db"
YOOMONEY_API_URL = "https://yoomoney.ru/api"

# Registration visual constants
REG_EMOJIS = {
    "start": "💘", "name": "✨", "age": "🎂", "city": "🏙️",
    "gender": "👤", "looking": "👀", "goal": "🎯", "interests": "🎨",
    "photo": "📸", "bio": "📝", "confirm": "🔥", "done": "🎉"
}

GOALS_MAP = {
    "relationship": "❤️ Серьёзные отношения",
    "friendship": "🤝 Дружба и общение",
    "fun": "😏 Флирт и веселье",
    "unsure": "🤷 Пока не знаю"
}

INTERESTS_MAP = {
    "music": "🎵 Музыка", "sport": "⚽ Спорт", "travel": "✈️ Путешествия",
    "games": "🎮 Игры", "movies": "🎬 Кино", "books": "📚 Книги",
    "cooking": "🍳 Готовка", "photo": "📸 Фото", "dance": "💃 Танцы",
    "auto": "🚗 Авто", "it": "💻 IT", "art": "🎨 Искусство"
}

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
    goal = State()
    interests = State()
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
    ban_user = State()
    unban_user = State()

class CityInput(StatesGroup):
    waiting_city = State()

class ReportState(StatesGroup):
    entering_reason = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

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
                profile_views INTEGER DEFAULT 0,
                last_bonus_date TEXT,
                bonus_likes INTEGER DEFAULT 0,
                bonus_messages INTEGER DEFAULT 0,
                interests TEXT,
                goal TEXT DEFAULT 'unsure'
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
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
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
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active, is_banned);
            CREATE INDEX IF NOT EXISTS idx_users_city ON users(city);
            CREATE INDEX IF NOT EXISTS idx_likes_from ON likes(from_user);
            CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_user);
            CREATE INDEX IF NOT EXISTS idx_matches_user1 ON matches(user1);
            CREATE INDEX IF NOT EXISTS idx_matches_user2 ON matches(user2);
        """)
        await db.commit()

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_user(telegram_id: int, username: str, name: str, age: int, city: str,
                     gender: str, looking_for: str, photo: str, bio: str, referral_code: str,
                     referred_by: int = None, interests: str = "", goal: str = "unsure"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, name, age, city, gender, looking_for, 
                             photo, bio, referral_code, referred_by, last_activity, interests, goal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_id, username, name, age, city, gender, looking_for, photo, bio, 
              referral_code, referred_by, datetime.datetime.now().isoformat(), interests, goal))
        await db.commit()

async def update_user(telegram_id: int, **kwargs):
    async with aiosqlite.connect(DB_NAME) as db:
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]
        await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
        await db.commit()

async def update_activity(telegram_id: int):
    await update_user(telegram_id, last_activity=datetime.datetime.now().isoformat())

async def get_random_profile(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        user = await get_user(telegram_id)
        if not user: 
            return None

        query = """
            SELECT * FROM users 
            WHERE telegram_id != ? AND is_active = 1 AND is_banned = 0
            AND telegram_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
            AND telegram_id NOT IN (
                SELECT user2 FROM matches WHERE user1 = ? 
                UNION 
                SELECT user1 FROM matches WHERE user2 = ?
            )
        """
        params = [telegram_id, telegram_id, telegram_id, telegram_id]

        if user["looking_for"] == "both":
            query += " AND gender IN ('male', 'female')"
        else:
            query += " AND gender = ?"
            params.append(user["looking_for"])

        query += " AND (looking_for = ? OR looking_for = 'both')"
        params.append(user["gender"])

        if not get_premium_status(user):
            query += " AND city = ?"
            params.append(user["city"])

        query += " ORDER BY RANDOM() LIMIT 1"
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def add_like(from_user: int, to_user: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM likes WHERE from_user = ? AND to_user = ?", (to_user, from_user)) as cursor:
            mutual = await cursor.fetchone()

        await db.execute(
            "INSERT OR IGNORE INTO likes (from_user, to_user, is_mutual) VALUES (?, ?, ?)",
            (from_user, to_user, 1 if mutual else 0)
        )

        match_id = None
        if mutual:
            u1, u2 = min(from_user, to_user), max(from_user, to_user)
            await db.execute("INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)", (u1, u2))
            await db.execute(
                "UPDATE likes SET is_mutual = 1 WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)",
                (from_user, to_user, to_user, from_user)
            )
            async with db.execute("SELECT id FROM matches WHERE user1 = ? AND user2 = ?", (u1, u2)) as cursor:
                row = await cursor.fetchone()
                match_id = row[0] if row else None
        await db.commit()
        return mutual is not None, match_id

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
            SELECT m.*, u.name, u.photo, u.age, u.city, u.telegram_id as partner_id
            FROM matches m 
            JOIN users u ON u.telegram_id = CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END
            WHERE m.user1 = ? OR m.user2 = ? 
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def add_message(match_id: int, from_user: int, content_type: str, content: str, file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO messages (match_id, from_user, content_type, content, file_id) VALUES (?, ?, ?, ?, ?)",
            (match_id, from_user, content_type, content, file_id)
        )
        await db.commit()

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
        async with db.execute(
            "SELECT city, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY city ORDER BY count DESC LIMIT 10"
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def reset_daily_limits():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET likes_today = 0, messages_today = 0, bonus_likes = 0, bonus_messages = 0")
        await db.commit()

async def increment_stat(field: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"""
            INSERT INTO stats (date, {field}) VALUES (CURRENT_DATE, 1) 
            ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1
        """)
        await db.commit()

async def get_likes_to_me_count(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM likes WHERE to_user = ? AND is_mutual = 0", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_payment(user_id: int, tariff: str, amount: int, label: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO payments (user_id, tariff, amount, label) VALUES (?, ?, ?, ?)",
            (user_id, tariff, amount, label)
        )
        await db.commit()

async def get_payment(label: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM payments WHERE label = ?", (label,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_payment(label: str, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE payments SET status = ?, paid_at = ? WHERE label = ?",
            (status, datetime.datetime.now().isoformat(), label)
        )
        await db.commit()

async def add_report(from_user: int, to_user: int, reason: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO reports (from_user, to_user, reason) VALUES (?, ?, ?)",
            (from_user, to_user, reason)
        )
        await db.commit()

async def get_user_by_ref_code(code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT telegram_id FROM users WHERE referral_code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# ==================== GEOCODING ====================
async def get_city_by_location(lat: float, lon: float):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=ru"
            async with session.get(url, headers={"User-Agent": "LoveSparkBot/1.0"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    address = data.get("address", {})
                    city = (address.get("city") or address.get("town") or 
                            address.get("village") or address.get("county") or 
                            address.get("state"))
                    return city
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None

# ==================== YOOMONEY ====================
async def create_payment_ym(amount: int, label: str, description: str = "LoveSpark Premium"):
    desc = html.escape(description)
    return f"https://yoomoney.ru/quickpay/confirm?receiver={YOOMONEY_WALLET}&quickpay-form=shop&targets={desc}&paymentType=AC&sum={amount}&label={label}&successURL=https://t.me/LoveSparkBot"

async def check_payment_ym(label: str):
    headers = {
        "Authorization": f"Bearer {YOOMONEY_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"type": "deposition", "label": label, "details": "true"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{YOOMONEY_API_URL}/operation-history", 
                headers=headers, 
                data=data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    for op in result.get("operations", []):
                        if op.get("label") == label and op.get("status") == "success":
                            return True
                else:
                    logger.warning(f"YooMoney API returned status {response.status}")
    except Exception as e:
        logger.error(f"YooMoney Error: {e}")
    return False

def generate_payment_label(user_id: int, tariff: str) -> str:
    return f"LS_{user_id}_{tariff}_{uuid.uuid4().hex[:8]}"

# ==================== KEYBOARDS ====================
def main_menu_kb(is_premium: bool = False, likes_to_me: int = 0):
    kb = [
        [KeyboardButton(text="❤️ Найти пару")],
        [KeyboardButton(text="📋 Моя анкета"), KeyboardButton(text="✏️ Редактировать")],
        [KeyboardButton(text="💕 Мои мэтчи"), KeyboardButton(text="📊 Статистика")],
    ]
    if likes_to_me > 0:
        kb.insert(1, [KeyboardButton(text=f"🔥 Меня лайкнули ({likes_to_me})")])
    if is_premium:
        kb.append([KeyboardButton(text="👑 Мой Премиум"), KeyboardButton(text="⬆️ Поднять анкету")])
    else:
        kb.append([KeyboardButton(text="💎 Получить Премиум")])
    kb.append([KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="❓ Помощь")])
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
    kb = [[KeyboardButton(text=city) for city in CITIES[i:i+3]] for i in range(0, len(CITIES), 3)]
    kb.append([KeyboardButton(text="📝 Ввести свой город")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def profile_actions_kb(profile_id: int, is_premium: bool = False):
    buttons = [
        [InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{profile_id}")],
        [InlineKeyboardButton(text="💬 Написать", callback_data=f"message_{profile_id}")],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{profile_id}")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_{profile_id}")],
        [InlineKeyboardButton(text="🛡️ Пожаловаться", callback_data=f"report_{profile_id}")],
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
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_premium")],
    ])

def edit_profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo"), InlineKeyboardButton(text="📝 Имя", callback_data="edit_name")],
        [InlineKeyboardButton(text="🔢 Возраст", callback_data="edit_age"), InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio"), InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking")],
        [InlineKeyboardButton(text="🎯 Цель", callback_data="edit_goal"), InlineKeyboardButton(text="🎨 Интересы", callback_data="edit_interests")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_menu")],
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="admin_ban"), InlineKeyboardButton(text="✅ Разбанить", callback_data="admin_unban")],
    ])

def confirm_delete_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete"), InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_delete")],
    ])

# ==================== REGISTRATION KEYBOARDS ====================
def reg_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💘 Начать знакомство", callback_data="reg_start")],
        [InlineKeyboardButton(text="❓ Что это?", callback_data="reg_whatis")]
    ])

def reg_name_kb(first_name: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✨ Использовать «{first_name[:20]}»", callback_data="reg_use_name")],
        [InlineKeyboardButton(text="📝 Ввести другое имя", callback_data="reg_custom_name")]
    ])

def reg_age_kb():
    ages = ["18-20", "21-23", "24-26", "27-30", "31-35", "36-40", "40+"]
    buttons = [[InlineKeyboardButton(text=f"🎂 {a}", callback_data=f"reg_age_{a}")] for a in ages]
    buttons.append([InlineKeyboardButton(text="🔢 Ввести точный возраст", callback_data="reg_age_custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def reg_city_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Определить по геолокации", request_location=True)],
            [KeyboardButton(text="📝 Ввести город вручную")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def reg_gender_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Я парень", callback_data="reg_gender_male"), 
         InlineKeyboardButton(text="👩 Я девушка", callback_data="reg_gender_female")]
    ])

def reg_looking_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Парней", callback_data="reg_look_male"), 
         InlineKeyboardButton(text="👩 Девушек", callback_data="reg_look_female")],
        [InlineKeyboardButton(text="👫 Всех без разницы", callback_data="reg_look_both")]
    ])

def reg_goal_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Серьёзные отношения", callback_data="reg_goal_relationship")],
        [InlineKeyboardButton(text="🤝 Дружба и общение", callback_data="reg_goal_friendship")],
        [InlineKeyboardButton(text="😏 Флирт и веселье", callback_data="reg_goal_fun")],
        [InlineKeyboardButton(text="🤷 Пока не знаю", callback_data="reg_goal_unsure")]
    ])

def reg_interests_kb(selected: set = None):
    if selected is None: 
        selected = set()
    buttons = []
    row = []
    for key, label in INTERESTS_MAP.items():
        icon = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(text=f"{icon}{label}", callback_data=f"reg_int_{key}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row: 
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✨ Готово! Продолжить →", callback_data="reg_int_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def reg_bio_kb():
    bios = [
        ("🎸 Люблю музыку, концерты и атмосферу", "music"),
        ("✈️ Обожаю путешествовать и открывать новое", "travel"),
        ("🍳 Готовлю лучшие блюда на свете", "cooking"),
        ("🎮 Игры, кино и уютные вечера дома", "home"),
        ("🏋️ Спорт и активный образ жизни", "sport"),
        ("📝 Напишу сам(а)", "custom")
    ]
    buttons = [[InlineKeyboardButton(text=text, callback_data=f"reg_bio_{val}")] for text, val in bios]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def reg_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё идеально! Создать анкету", callback_data="reg_confirm_yes")],
        [InlineKeyboardButton(text="✏️ Что-то изменить", callback_data="reg_confirm_edit")],
        [InlineKeyboardButton(text="❌ Начать заново", callback_data="reg_confirm_restart")]
    ])

# ==================== UTILITIES ====================
def get_premium_status(user):
    if not user or not user.get("is_premium"): 
        return False
    if user.get("premium_until"):
        try:
            return datetime.datetime.fromisoformat(user["premium_until"]) > datetime.datetime.now()
        except:
            return False
    return False

def format_profile(user):
    gender_emoji = "👨" if user.get("gender") == "male" else "👩"
    prem_badge = "💎" if get_premium_status(user) else ""
    online_status = "🟢" if user.get("last_activity") and \
        (datetime.datetime.now() - datetime.datetime.fromisoformat(user["last_activity"])).total_seconds() < 300 else "⚪"

    name = html.escape(str(user.get('name', 'Неизвестно')))
    city = html.escape(str(user.get('city', 'Не указан')))
    bio = html.escape(str(user.get('bio', 'Нет описания')))
    age = user.get('age', '?')
    views = user.get('profile_views', 0)

    goal = GOALS_MAP.get(user.get('goal', 'unsure'), '')
    interests_str = user.get('interests', '')
    interests_display = ""
    if interests_str:
        ints = [INTERESTS_MAP.get(i.strip(), i.strip()) for i in interests_str.split(",") if i.strip()]
        if ints:
            interests_display = "\n🎨 " + ", ".join(ints)

    return (
        f"{gender_emoji} <b>{name}</b>, {age} {prem_badge} {online_status}\n"
        f"🏙️ {city}\n"
        f"🎯 {goal}{interests_display}\n"
        f"👁️ Просмотров: {views}\n\n"
        f"📝 {bio}"
    )

def get_remaining_likes(user):
    if get_premium_status(user): 
        return "∞"
    total = FREE_LIKES_PER_DAY + user.get("bonus_likes", 0)
    return max(0, total - user.get("likes_today", 0))

def get_remaining_messages(user):
    if get_premium_status(user): 
        return "∞"
    total = FREE_MESSAGES_PER_DAY + user.get("bonus_messages", 0)
    return max(0, total - user.get("messages_today", 0))

async def safe_send_message(chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return None

async def check_user_banned(message: Message):
    user = await get_user(message.from_user.id)
    if user and user.get("is_banned"):
        await message.answer("🚫 Ваш аккаунт заблокирован. Обратитесь в поддержку.")
        return True
    return False

# ==================== REGISTRATION HANDLERS ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    ref_code = None
    if message.text and len(message.text.split()) > 1:
        arg = message.text.split()[1]
        if arg.startswith("ref_"):
            ref_code = arg.replace("ref_", "")

    user = await get_user(message.from_user.id)
    if user and user.get("is_active"):
        if ref_code and not user.get("referred_by"):
            referrer = await get_user_by_ref_code(ref_code)
            if referrer and referrer['telegram_id'] != message.from_user.id:
                await update_user(message.from_user.id, referred_by=referrer['telegram_id'])
                ref_user = await get_user(referrer['telegram_id'])
                await update_user(
                    referrer['telegram_id'],
                    bonus_likes=ref_user.get('bonus_likes', 0) + REFERRAL_BONUS_LIKES,
                    bonus_messages=ref_user.get('bonus_messages', 0) + REFERRAL_BONUS_MSGS
                )
                await update_user(
                    message.from_user.id,
                    bonus_likes=user.get('bonus_likes', 0) + REFERRAL_BONUS_LIKES,
                    bonus_messages=user.get('bonus_messages', 0) + REFERRAL_BONUS_MSGS
                )
                await safe_send_message(
                    referrer['telegram_id'],
                    f"🎉 По твоей ссылке зарегистрировался пользователь!\n"
                    f"Тебе начислено +{REFERRAL_BONUS_LIKES} лайков и +{REFERRAL_BONUS_MSGS} сообщений!"
                )
                await message.answer(
                    f"🎉 Ты получил +{REFERRAL_BONUS_LIKES} лайков и +{REFERRAL_BONUS_MSGS} сообщений за регистрацию по реферальной ссылке!"
                )

        likes_to_me = await get_likes_to_me_count(message.from_user.id)
        await message.answer(
            f"💘 <b>С возвращением в LoveSpark!</b>\n\n"
            f"Твоя идеальная пара уже ждёт тебя.\n"
            f"❤️ Лайков сегодня: {get_remaining_likes(user)}\n"
            f"💬 Сообщений сегодня: {get_remaining_messages(user)}",
            reply_markup=main_menu_kb(get_premium_status(user), likes_to_me),
            parse_mode=ParseMode.HTML
        )
        return

    welcome_text = (
        f"{REG_EMOJIS['start']} <b>Привет, {html.escape(message.from_user.first_name or 'красавчик')}!</b>\n\n"
        f"Я — <b>LoveSpark</b>, твой личный помощник в мире знакомств. "
        f"Здесь ты найдёшь людей, которые ищут то же, что и ты.\n\n"
        f"✨ <b>Что тебя ждёт:</b>\n"
        f"• Умный подбор по интересам и городу\n"
        f"• Мгновенные мэтчи и чаты\n"
        f"• Безопасность и удобство\n\n"
        f"Готов найти свою искру? 🔥"
    )
    await message.answer(welcome_text, reply_markup=reg_start_kb(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "reg_whatis")
async def reg_whatis_cb(callback: CallbackQuery):
    await callback.message.edit_text(
        "💡 <b>LoveSpark</b> — это бот для знакомств по всей России.\n\n"
        "Мы подбираем людей по твоему городу, возрасту и интересам. "
        "Взаимный лайк = мэтч = возможность общаться!\n\n"
        "Всё просто, безопасно и увлекательно ✨",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💘 Поехали!", callback_data="reg_start")]
        ]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "reg_start")
async def reg_start_cb(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"{REG_EMOJIS['name']} <b>Как к тебе обращаться?</b>\n\n"
        f"Можешь использовать своё имя из Telegram или ввести другое.",
        reply_markup=reg_name_kb(callback.from_user.first_name or "Друг"),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.name)

@dp.callback_query(F.data == "reg_use_name", Registration.name)
async def reg_use_name_cb(callback: CallbackQuery, state: FSMContext):
    name = callback.from_user.first_name or "Пользователь"
    await state.update_data(name=name)
    await callback.message.edit_text(
        f"{REG_EMOJIS['age']} <b>Отлично, {html.escape(name)}!</b>\n\n"
        f"Теперь выбери свой возраст:",
        reply_markup=reg_age_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.age)

@dp.callback_query(F.data == "reg_custom_name", Registration.name)
async def reg_custom_name_cb(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"{REG_EMOJIS['name']} <b>Как тебя зовут?</b>\n\n"
        f"Напиши своё имя (от 2 до 30 символов):",
        parse_mode=ParseMode.HTML
    )

@dp.message(Registration.name)
async def process_name_text(message: Message, state: FSMContext):
    name = message.text.strip()
    if not (2 <= len(name) <= 30):
        return await message.answer(
            f"{REG_EMOJIS['name']} Имя должно быть от 2 до 30 символов. Попробуй ещё раз:"
        )
    await state.update_data(name=name)
    await message.answer(
        f"{REG_EMOJIS['age']} <b>Отлично, {html.escape(name)}!</b>\n\n"
        f"Теперь выбери свой возраст:",
        reply_markup=reg_age_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.age)

@dp.callback_query(F.data.startswith("reg_age_"), Registration.age)
async def reg_age_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_age_", "")
    if data == "custom":
        await callback.message.edit_text(
            f"{REG_EMOJIS['age']} Напиши свой точный возраст цифрами (16-100):",
            parse_mode=ParseMode.HTML
        )
        return

    age = None
    if data == "40+":
        age = random.randint(40, 55)
        await state.update_data(age=age, age_range="40+")
    else:
        parts = data.split("-")
        if len(parts) == 2:
            age = random.randint(int(parts[0]), int(parts[1]))
            await state.update_data(age=age, age_range=data)
        else:
            return await callback.answer("Ошибка")

    await callback.message.edit_text(
        f"{REG_EMOJIS['city']} <b>Круто, {age}!</b> 🎉\n\n"
        f"Теперь скажи, откуда ты?",
        parse_mode=ParseMode.HTML
    )
    await callback.message.answer(
        f"🏙️ Выбери способ указания города:",
        reply_markup=reg_city_reply_kb()
    )
    await state.set_state(Registration.city)

@dp.message(Registration.age)
async def process_age_text(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not (16 <= age <= 100):
            raise ValueError
    except ValueError:
        return await message.answer(
            f"{REG_EMOJIS['age']} Введи корректный возраст цифрами (16-100):"
        )
    await state.update_data(age=age)
    await message.answer(
        f"{REG_EMOJIS['city']} <b>Круто!</b>\n\n"
        f"Теперь скажи, откуда ты?",
        reply_markup=reg_city_reply_kb()
    )
    await state.set_state(Registration.city)

@dp.message(Registration.city, F.location)
async def process_city_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await bot.send_chat_action(message.chat.id, "find_location")
    city = await get_city_by_location(lat, lon)

    if city:
        await state.update_data(city=city)
        await message.answer(
            f"{REG_EMOJIS['city']} <b>Нашёл!</b> 📍\n\n"
            f"Твой город: <b>{html.escape(city)}</b>",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            f"{REG_EMOJIS['gender']} Теперь определимся с полом:",
            reply_markup=reg_gender_kb(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(Registration.gender)
    else:
        await message.answer(
            "😕 Не удалось определить город по геолокации.\n"
            "Попробуй ввести вручную:",
            reply_markup=reg_city_reply_kb()
        )

@dp.message(Registration.city)
async def process_city_text(message: Message, state: FSMContext):
    if message.text == "📍 Определить по геолокации":
        return await message.answer(
            "Отправь свою геолокацию через скрепку 📎 → Геолокация",
            reply_markup=reg_city_reply_kb()
        )
    if message.text == "📝 Ввести город вручную":
        return await message.answer(
            f"{REG_EMOJIS['city']} Напиши название своего города:",
            reply_markup=ReplyKeyboardRemove()
        )

    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        return await message.answer(
            f"{REG_EMOJIS['city']} Название города должно быть от 2 до 50 символов:"
        )

    await state.update_data(city=city)
    await message.answer(
        f"{REG_EMOJIS['gender']} <b>Отлично, {html.escape(city)}!</b>\n\n"
        f"Теперь определимся с полом:",
        reply_markup=reg_gender_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.gender)

@dp.callback_query(F.data.startswith("reg_gender_"), Registration.gender)
async def reg_gender_cb(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("reg_gender_", "")
    await state.update_data(gender=gender)
    await callback.message.edit_text(
        f"{REG_EMOJIS['looking']} <b>Кого ты ищешь?</b>\n\n"
        f"Выбирай смело — здесь нет неправильных ответов 😉",
        reply_markup=reg_looking_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.looking_for)

@dp.callback_query(F.data.startswith("reg_look_"), Registration.looking_for)
async def reg_looking_cb(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.replace("reg_look_", "")
    await state.update_data(looking_for=looking)
    await callback.message.edit_text(
        f"{REG_EMOJIS['goal']} <b>Какая цель знакомства?</b>\n\n"
        f"Это поможет найти людей с похожими намерениями ✨",
        reply_markup=reg_goal_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.goal)

@dp.callback_query(F.data.startswith("reg_goal_"), Registration.goal)
async def reg_goal_cb(callback: CallbackQuery, state: FSMContext):
    goal = callback.data.replace("reg_goal_", "")
    await state.update_data(goal=goal)
    await callback.message.edit_text(
        f"{REG_EMOJIS['interests']} <b>Выбери свои интересы!</b>\n\n"
        f"Можно выбрать несколько — нажимай на каждый, а потом «Готово» 👇",
        reply_markup=reg_interests_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.interests)

@dp.callback_query(F.data.startswith("reg_int_"), Registration.interests)
async def reg_interest_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_int_", "")
    if data == "done":
        interests_data = await state.get_data()
        selected = interests_data.get("interests", set())
        if not selected:
            return await callback.answer("Выбери хотя бы один интерес!", show_alert=True)

        await state.update_data(interests=",".join(selected))
        await callback.message.edit_text(
            f"{REG_EMOJIS['photo']} <b>Время для фото!</b> 📸\n\n"
            f"Отправь своё лучшее фото — именно так тебя увидят другие.\n\n"
            f"💡 <i>Совет:</i> улыбнись, хорошее освещение — и успех обеспечен!",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(Registration.photo)
        return

    current = await state.get_data()
    selected = set(current.get("interests", []))

    if data in selected:
        selected.remove(data)
    else:
        selected.add(data)

    await state.update_data(interests=selected)
    await callback.message.edit_reply_markup(reply_markup=reg_interests_kb(selected))
    await callback.answer()

@dp.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer(
        f"{REG_EMOJIS['bio']} <b>Расскажи о себе!</b>\n\n"
        f"Это твой шанс произвести впечатление ✨\n"
        f"Можешь выбрать готовый вариант или написать своё:",
        reply_markup=reg_bio_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.bio)

@dp.message(Registration.photo)
async def process_photo_error(message: Message):
    await message.answer(
        f"{REG_EMOJIS['photo']} Это не похоже на фото 😕\n"
        f"Отправь именно фото, а не файл:"
    )

@dp.callback_query(F.data.startswith("reg_bio_"), Registration.bio)
async def reg_bio_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_bio_", "")
    bios = {
        "music": "🎸 Люблю живую музыку, концерты и атмосферные вечера. Ищу того, с кем можно танцевать до утра!",
        "travel": "✈️ Обожаю путешествия! Посетил(а) 10+ стран. Ищу компаньона для новых приключений.",
        "cooking": "🍳 Готовлю лучшие блюда на свете. Давай устроим ужин при свечах — я готовлю, ты приносишь вино 😉",
        "home": "🎮 Кино, игры и уютные вечера дома — моё всё. Но иногда хочется кого-то рядом для объятий.",
        "sport": "🏋️ Спорт и активный образ жизни. Бегаю по утрам, ищу мотивацию и вдохновение рядом."
    }

    if data == "custom":
        await callback.message.edit_text(
            f"{REG_EMOJIS['bio']} <b>Напиши о себе:</b>\n\n"
            f"Хобби, интересы, что ищешь — всё, что считаешь важным (5-500 символов):",
            parse_mode=ParseMode.HTML
        )
        return

    bio = bios.get(data, "Привет! Ищу интересных людей.")
    await state.update_data(bio=bio)
    await show_preview(callback.message, state)

@dp.message(Registration.bio)
async def process_bio_text(message: Message, state: FSMContext):
    if len(message.text) < 5:
        return await message.answer(
            f"{REG_EMOJIS['bio']} Описание слишком короткое. Расскажи чуть больше о себе:"
        )
    await state.update_data(bio=message.text[:500])
    await show_preview(message, state)

async def show_preview(target: Message, state: FSMContext):
    data = await state.get_data()

    gender_emoji = "👨" if data.get('gender') == "male" else "👩"
    goal_text = GOALS_MAP.get(data.get('goal', 'unsure'), '')
    interests = data.get('interests', '')
    if isinstance(interests, str):
        interest_list = [INTERESTS_MAP.get(i, i) for i in interests.split(",") if i]
    else:
        interest_list = [INTERESTS_MAP.get(i, i) for i in interests]

    preview = (
        f"{gender_emoji} <b>{html.escape(data.get('name', 'Неизвестно'))}</b>, {data.get('age', '?')}\n"
        f"🏙️ {html.escape(data.get('city', 'Не указан'))}\n"
        f"🎯 {goal_text}\n"
        f"🎨 {', '.join(interest_list)}\n\n"
        f"📝 {html.escape(data.get('bio', 'Нет описания'))}"
    )

    await target.answer_photo(
        photo=data['photo'],
        caption=f"📋 <b>Предпросмотр твоей анкеты:</b>\n\n{preview}\n\n"
                f"Всё выглядит шикарно? 🔥",
        reply_markup=reg_confirm_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.confirm)

@dp.callback_query(F.data == "reg_confirm_yes", Registration.confirm)
async def confirm_reg_cb(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    code = f"LS{uuid.uuid4().hex[:6].upper()}"

    interests_str = data.get('interests', '')
    if isinstance(interests_str, set):
        interests_str = ",".join(interests_str)

    await create_user(
        callback.from_user.id,
        callback.from_user.username,
        data['name'],
        data['age'],
        data['city'],
        data['gender'],
        data['looking_for'],
        data['photo'],
        data['bio'],
        code,
        interests=interests_str,
        goal=data.get('goal', 'unsure')
    )
    await increment_stat("new_users")

    await callback.message.delete()
    await callback.message.answer(
        f"{REG_EMOJIS['done']} <b>Анкета создана!</b> 🎉\n\n"
        f"Добро пожаловать в LoveSpark, {html.escape(data['name'])}!\n\n"
        f"✨ <b>Твой реферальный код:</b> <code>{code}</code>\n"
        f"Поделись с друзьями — оба получите бонусы!\n\n"
        f"💘 Начни поиск прямо сейчас!",
        reply_markup=main_menu_kb(False),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.callback_query(F.data == "reg_confirm_edit", Registration.confirm)
async def edit_reg_cb(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ <b>Что хочешь изменить?</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name"), InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
            [InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city"), InlineKeyboardButton(text="👤 Пол", callback_data="edit_gender")],
            [InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking"), InlineKeyboardButton(text="🎯 Цель", callback_data="edit_goal")],
            [InlineKeyboardButton(text="🎨 Интересы", callback_data="edit_interests"), InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo")],
            [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio")],
            [InlineKeyboardButton(text="🔙 Назад к предпросмотру", callback_data="reg_back_preview")]
        ]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "reg_back_preview")
async def back_preview_cb(callback: CallbackQuery, state: FSMContext):
    await show_preview(callback.message, state)

@dp.callback_query(F.data == "reg_confirm_restart", Registration.confirm)
async def restart_reg_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🔄 <b>Начинаем заново!</b>",
        parse_mode=ParseMode.HTML
    )
    await reg_start_cb(callback, state)

# ==================== MAIN MENU HANDLERS ====================

@dp.message(F.text == "❤️ Найти пару")
async def find_pair(message: Message):
    if await check_user_banned(message):
        return

    user = await get_user(message.from_user.id)
    if not user: 
        return await message.answer("Создай анкету через /start")

    await update_activity(message.from_user.id)

    total_likes = get_remaining_likes(user)
    if total_likes == 0:
        return await message.answer(
            "😔 Лимит лайков на сегодня исчерпан!\n\n"
            "💎 Купи Премиум для безлимита!\n"
            "🎁 Или забирай ежедневный бонус!",
            reply_markup=main_menu_kb(False)
        )

    await bot.send_chat_action(message.chat.id, "typing")
    profile = await get_random_profile(user['telegram_id'])
    if not profile:
        text = (
            "😕 Пока нет подходящих анкет.\n\n"
            "💡 Советы:\n"
        )
        if not get_premium_status(user):
            text += "• Купи Премиум для поиска по всей России\n"
        text += "• Пригласи друзей по реферальной ссылке\n• Загляни попозже!"
        return await message.answer(text, reply_markup=main_menu_kb(get_premium_status(user)))

    await update_user(profile['telegram_id'], profile_views=profile.get('profile_views', 0) + 1)

    await message.answer_photo(
        photo=profile['photo'], 
        caption=format_profile(profile), 
        reply_markup=profile_actions_kb(profile['telegram_id'], get_premium_status(user)), 
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📋 Моя анкета")
async def my_profile(message: Message):
    if await check_user_banned(message):
        return
    user = await get_user(message.from_user.id)
    if not user: 
        return await message.answer("Создай анкету через /start")

    await update_activity(message.from_user.id)
    status = "💎 Премиум" if get_premium_status(user) else "⭐ Бесплатный"
    likes_to_me = await get_likes_to_me_count(message.from_user.id)

    caption = (
        f"{format_profile(user)}\n\n"
        f"📊 Статус: {status}\n"
        f"❤️ Лайков сегодня: {get_remaining_likes(user)}\n"
        f"💬 Сообщений сегодня: {get_remaining_messages(user)}\n"
        f"🔥 Тебя лайкнули: {likes_to_me} чел."
    )
    await message.answer_photo(photo=user['photo'], caption=caption, parse_mode=ParseMode.HTML)

@dp.message(F.text == "✏️ Редактировать")
async def edit_profile_cmd(message: Message):
    if await check_user_banned(message):
        return
    await message.answer("Что хочешь изменить?", reply_markup=edit_profile_kb())

@dp.message(F.text == "💕 Мои мэтчи")
async def my_matches_cmd(message: Message):
    if await check_user_banned(message):
        return
    await update_activity(message.from_user.id)
    matches = await get_matches(message.from_user.id)
    if not matches: 
        return await message.answer(
            "💔 У тебя пока нет мэтчей.\n"
            "Ставь лайки понравившимся людям!"
        )

    await message.answer(f"💕 <b>Твои мэтчи ({len(matches)}):</b>", parse_mode=ParseMode.HTML)
    for m in matches[:10]:
        p_id = m.get('partner_id')
        name_safe = html.escape(str(m['name']))
        city_safe = html.escape(str(m['city']))
        await message.answer_photo(
            photo=m['photo'], 
            caption=f"💕 <b>{name_safe}</b>, {m['age']}\n🏙️ {city_safe}", 
            reply_markup=match_actions_kb(m['id'], p_id), 
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "📊 Статистика")
async def show_stats_cmd(message: Message):
    if await check_user_banned(message):
        return
    stats = await get_stats()
    top_cities = await get_top_cities()
    cities_text = "\n".join([f"{i+1}. {html.escape(c['city'])} - {c['count']} чел." for i, c in enumerate(top_cities[:5])])

    text = (
        f"📊 <b>Статистика LoveSpark</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"💎 Премиум пользователей: {stats['premium_users']}\n"
        f"🔥 Активных: {stats['active_users']}\n\n"
        f"🏙️ <b>Топ городов:</b>\n{cities_text}"
    )
    user = await get_user(message.from_user.id)
    likes_to_me = await get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))

@dp.message(F.text == "💎 Получить Премиум")
async def get_premium_cmd(message: Message):
    if await check_user_banned(message):
        return
    await message.answer(
        f"💎 <b>Премиум подписка LoveSpark</b>\n\n"
        f"✅ Безлимит лайков\n"
        f"✅ Безлимит сообщений\n"
        f"✅ Поиск по всей России\n"
        f"✅ Супер-лайки\n"
        f"✅ Приоритет в поиске\n"
        f"✅ Просмотр кто тебя лайкнул\n\n"
        f"Выбери тариф:", 
        reply_markup=premium_kb(), 
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👑 Мой Премиум")
async def my_premium_cmd(message: Message):
    if await check_user_banned(message):
        return
    user = await get_user(message.from_user.id)
    if not get_premium_status(user): 
        return await message.answer("У тебя нет Премиум подписки.", reply_markup=main_menu_kb(False))

    until_str = user.get("premium_until")
    if not until_str:
        return await message.answer("Ошибка данных премиума. Обратись в поддержку.")

    try:
        until = datetime.datetime.fromisoformat(until_str)
        days_left = (until - datetime.datetime.now()).days
        await message.answer(
            f"👑 <b>Твой Премиум</b>\n\n"
            f"📅 Действует до: {until.strftime('%d.%m.%Y')}\n"
            f"⏳ Осталось: {days_left} дней", 
            parse_mode=ParseMode.HTML
        )
    except:
        await message.answer("Ошибка данных премиума. Обратись в поддержку.")

@dp.message(F.text.startswith("🔥 Меня лайкнули"))
async def who_liked_me_cmd(message: Message):
    if await check_user_banned(message):
        return
    user = await get_user(message.from_user.id)
    count = await get_likes_to_me_count(message.from_user.id)

    if count == 0:
        return await message.answer(
            "😕 Пока никто тебя не лайкнул.\n"
            "Активнее ставь лайки другим, чтобы тебя заметили!",
            reply_markup=main_menu_kb(get_premium_status(user))
        )

    if get_premium_status(user):
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT u.* FROM likes l 
                JOIN users u ON l.from_user = u.telegram_id 
                WHERE l.to_user = ? AND l.is_mutual = 0
                ORDER BY l.created_at DESC LIMIT 10
            """, (message.from_user.id,)) as cursor:
                likers = [dict(row) for row in await cursor.fetchall()]

        await message.answer(f"🔥 <b>Тебя лайкнули ({count}):</b>", parse_mode=ParseMode.HTML)
        for liker in likers:
            await message.answer_photo(
                photo=liker['photo'],
                caption=format_profile(liker),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❤️ Лайк в ответ", callback_data=f"like_{liker['telegram_id']}")],
                    [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{liker['telegram_id']}")],
                ]),
                parse_mode=ParseMode.HTML
            )
    else:
        await message.answer(
            f"🔥 <b>Тебя лайкнули {count} человек!</b>\n\n"
            f"💡 Хочешь узнать кто? Купи Премиум и увидишь всех!\n"
            f"Они уже ждут твоего ответа... 💘",
            reply_markup=main_menu_kb(False),
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus_cmd(message: Message):
    if await check_user_banned(message):
        return
    user = await get_user(message.from_user.id)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    last_bonus = user.get("last_bonus_date")

    if last_bonus == today:
        return await message.answer(
            "🎁 Ты уже получил бонус сегодня!\n"
            "Приходи завтра за новым!",
            reply_markup=main_menu_kb(get_premium_status(user))
        )

    await update_user(
        message.from_user.id,
        last_bonus_date=today,
        bonus_likes=user.get("bonus_likes", 0) + DAILY_BONUS_LIKES,
        bonus_messages=user.get("bonus_messages", 0) + DAILY_BONUS_MSGS
    )

    await message.answer(
        f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
        f"❤️ +{DAILY_BONUS_LIKES} лайка\n"
        f"💬 +{DAILY_BONUS_MSGS} сообщения\n\n"
        f"Заходи каждый день за новыми бонусами!",
        reply_markup=main_menu_kb(get_premium_status(user)),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "⬆️ Поднять анкету")
async def boost_profile_cmd(message: Message):
    if await check_user_banned(message):
        return
    user = await get_user(message.from_user.id)
    if not get_premium_status(user):
        return await message.answer(
            "⬆️ Поднятие анкеты доступно только для Премиум пользователей.",
            reply_markup=main_menu_kb(False)
        )

    await update_activity(message.from_user.id)
    await message.answer(
        "🔥 <b>Анкета поднята!</b>\n\n"
        "Теперь тебя будут видеть чаще в поиске.\n"
        "Можно поднимать раз в час.",
        reply_markup=main_menu_kb(True),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: Message):
    user = await get_user(message.from_user.id)
    likes_to_me = await get_likes_to_me_count(message.from_user.id) if user else 0
    text = (
        f"❓ <b>Помощь</b>\n\n"
        f"1. Нажимай «❤️ Найти пару»\n"
        f"2. Ставь лайки\n"
        f"3. При взаимном лайке вы сможете общаться\n\n"
        f"<b>Команды:</b>\n"
        f"/start - Перезапуск\n"
        f"/delete - Удалить профиль\n"
        f"/report [id] [причина] - Пожаловаться\n\n"
        f"Лимиты бесплатно: {FREE_LIKES_PER_DAY} лайков, {FREE_MESSAGES_PER_DAY} сообщений.\n"
        f"🎁 Ежедневный бонус: +{DAILY_BONUS_LIKES} лайка, +{DAILY_BONUS_MSGS} сообщения!"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))

# ==================== ACTIONS / CALLBACKS ====================

@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)

    if not user:
        return await callback.answer("Сначала создай анкету!", show_alert=True)

    total_likes = get_remaining_likes(user)
    if total_likes == 0:
        return await callback.answer("Лимит лайков исчерпан! Купи Премиум или возьми бонус.", show_alert=True)

    await update_user(user['telegram_id'], likes_today=user.get("likes_today", 0) + 1)
    is_mutual, match_id = await add_like(user['telegram_id'], target_id)
    await increment_stat("likes_count")

    if is_mutual:
        await increment_stat("matches_count")
        partner = await get_user(target_id)
        if not partner:
            return await callback.answer("Ошибка: пользователь не найден.")

        partner_name = html.escape(partner['name'])
        my_name = html.escape(user['name'])

        await callback.message.answer(
            f"💕 <b>Взаимный мэтч!</b>\n"
            f"Вы и {partner_name} понравились друг другу!\n\n"
            f"Скорее начинай общаться! 💬",
            reply_markup=match_actions_kb(match_id, target_id), 
            parse_mode=ParseMode.HTML
        )
        try:
            await bot.send_message(
                target_id, 
                f"💕 <b>Новый мэтч!</b>\n"
                f"{my_name} лайкнул(а) тебя взаимно!\n\n"
                f"Скорее начинай общаться! 💬",
                reply_markup=match_actions_kb(match_id, user['telegram_id']), 
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    else:
        try:
            await bot.send_message(
                target_id,
                f"💘 <b>Кто-то тебя лайкнул!</b>\n\n"
                f"Открой LoveSpark, чтобы узнать кто... 😉\n"
                f"Возможно, это твоя судьба!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❤️ Открыть LoveSpark", url="https://t.me/LoveSparkBot")]
                ]),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await callback.answer("❤️ Лайк отправлен!")

    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("superlike_"))
async def process_superlike(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)
    if not get_premium_status(user): 
        return await callback.answer("Супер-лайки только для Премиум!", show_alert=True)

    is_mutual, match_id = await add_like(user['telegram_id'], target_id)
    if is_mutual:
        partner = await get_user(target_id)
        await callback.message.answer(
            f"⭐ <b>Супер-мэтч!</b>\n"
            f"Вы и {html.escape(partner['name'])} - мэтч!", 
            reply_markup=match_actions_kb(match_id, target_id), 
            parse_mode=ParseMode.HTML
        )
        try:
            await bot.send_message(
                target_id,
                f"⭐ <b>Супер-мэтч!</b>\n"
                f"Кто-то использовал супер-лайк на тебе! Это {html.escape(user['name'])}!",
                reply_markup=match_actions_kb(match_id, user['telegram_id']),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    else:
        try:
            await bot.send_message(
                target_id,
                f"⭐ <b>Супер-лайк!</b>\n\n"
                f"Кто-то особенно сильно тебя лайкнул! 💘\n"
                f"Открой, чтобы узнать кто...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❤️ Открыть LoveSpark", url="https://t.me/LoveSparkBot")]
                ]),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await callback.answer("⭐ Супер-лайк отправлен!")

    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("skip_") | F.data.startswith("block_"))
async def skip_profile(callback: CallbackQuery):
    action = "Пропущено" if "skip" in callback.data else "Заблокировано"
    await callback.answer(action)
    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("report_"))
async def report_profile_cb(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target=target_id)
    await state.set_state(ReportState.entering_reason)
    await callback.message.answer("🛡️ Опиши причину жалобы на этого пользователя:")
    await callback.answer()

@dp.message(ReportState.entering_reason)
async def process_report(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("report_target")
    if not target_id:
        return await state.clear()

    reason = message.text[:500]
    await add_report(message.from_user.id, target_id, reason)
    user = await get_user(message.from_user.id)
    likes_to_me = await get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer(
        "🛡️ Жалоба отправлена администрации.\n"
        "Спасибо, что помогаешь делать LoveSpark безопаснее!",
        reply_markup=main_menu_kb(get_premium_status(user), likes_to_me)
    )
    await state.clear()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"🚨 <b>Новая жалоба!</b>\n\n"
            f"От: {message.from_user.id}\n"
            f"На: {target_id}\n"
            f"Причина: {html.escape(reason)}",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

# ==================== CHAT LOGIC ====================

async def open_chat(message_or_callback, state: FSMContext, match_id: int, partner_id: int):
    partner = await get_user(int(partner_id))
    if not partner:
        return await message_or_callback.answer("Пользователь не найден.")

    await state.set_state(ChatState.chatting)
    await state.update_data(match_id=int(match_id), partner_id=int(partner_id))

    text = (
        f"💬 <b>Чат с {html.escape(partner['name'])}</b>\n"
        f"Отправляй текст, фото, видео, голосовые или стикеры.\n"
        f"Выход: /exit"
    )
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(text, reply_markup=chat_actions_kb(match_id), parse_mode=ParseMode.HTML)
    else:
        await message_or_callback.answer(text, reply_markup=chat_actions_kb(match_id), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat_cb(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return await callback.answer("Ошибка данных.")
    match_id = parts[1]
    p_id = parts[2]
    await open_chat(callback, state, match_id, p_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("message_"))
async def write_message_from_profile(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    match = await get_match(callback.from_user.id, target_id)
    if not match: 
        return await callback.answer("Сначала нужен взаимный мэтч!", show_alert=True)
    await open_chat(callback, state, match['id'], target_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("hint_"))
async def hints_cb(callback: CallbackQuery):
    await callback.answer("Просто отправь это в чат!", show_alert=True)

@dp.callback_query(F.data == "back_to_matches")
async def back_to_matches(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await my_matches_cmd(callback.message)

@dp.callback_query(F.data.startswith("view_"))
async def view_profile_cb(callback: CallbackQuery):
    p_id = int(callback.data.split("_")[1])
    p = await get_user(p_id)
    if p and p.get("is_active") and not p.get("is_banned"):
        await callback.message.answer_photo(photo=p['photo'], caption=format_profile(p), parse_mode=ParseMode.HTML)
    else:
        await callback.answer("Анкета недоступна.")
    await callback.answer()

@dp.message(ChatState.chatting)
async def process_chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data.get("partner_id")
    if not partner_id: 
        return await state.clear()

    user = await get_user(message.from_user.id)
    if not user:
        return await state.clear()

    total_msgs = get_remaining_messages(user)
    if total_msgs == 0:
        return await message.answer(
            "😔 Лимит сообщений исчерпан! Купи Премиум или возьми бонус.",
            reply_markup=main_menu_kb(False)
        )

    content = message.text or message.caption or "[Вложение]"
    content_type, file_id = "text", None

    if message.photo: 
        content_type, file_id = "photo", message.photo[-1].file_id
    elif message.voice: 
        content_type, file_id = "voice", message.voice.file_id
    elif message.sticker: 
        content_type, file_id = "sticker", message.sticker.file_id
    elif message.video: 
        content_type, file_id = "video", message.video.file_id
    elif message.video_note: 
        content_type, file_id = "video_note", message.video_note.file_id
    elif message.document:
        content_type, file_id = "document", message.document.file_id

    await add_message(data["match_id"], message.from_user.id, content_type, content, file_id)
    if not get_premium_status(user): 
        await update_user(user['telegram_id'], messages_today=user.get("messages_today", 0) + 1)

    name_safe = html.escape(user['name'])
    content_safe = html.escape(content)

    try:
        if content_type == "text": 
            await bot.send_message(
                partner_id, 
                f"💬 <b>{name_safe}:</b>\n{content_safe}", 
                parse_mode=ParseMode.HTML
            )
        elif content_type == "photo": 
            caption = f"📸 <b>{name_safe}</b>" + (f"\n{content_safe}" if message.caption else "")
            await bot.send_photo(partner_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "voice": 
            await bot.send_voice(partner_id, file_id, caption=f"🎙️ <b>{name_safe}</b>", parse_mode=ParseMode.HTML)
        elif content_type == "sticker": 
            await bot.send_sticker(partner_id, file_id)
        elif content_type == "video": 
            caption = f"🎬 <b>{name_safe}</b>" + (f"\n{content_safe}" if message.caption else "")
            await bot.send_video(partner_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "video_note": 
            await bot.send_video_note(partner_id, file_id)
        elif content_type == "document":
            await bot.send_document(
                partner_id, 
                file_id, 
                caption=f"📎 <b>{name_safe}</b>\n{content_safe}", 
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"Chat forward error: {e}")
        await message.answer("🚫 Пользователь ограничил доступ к боту или заблокировал.")

@dp.message(Command("exit"), ChatState.chatting)
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    likes_to_me = await get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer("🔙 Вы вышли из чата.", reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))

# ==================== PREMIUM PAYMENTS ====================

@dp.callback_query(F.data.startswith("premium_"))
async def select_premium(callback: CallbackQuery):
    tariff_key = callback.data.split("_")[1]
    if tariff_key not in PREMIUM_TARIFFS:
        return await callback.answer("Ошибка тарифа.")
    tariff = PREMIUM_TARIFFS[tariff_key]
    label = generate_payment_label(callback.from_user.id, tariff_key)

    await add_payment(callback.from_user.id, tariff_key, tariff['price'], label)
    url = await create_payment_ym(tariff['price'], label, f"LoveSpark Premium {tariff['name']}")

    await callback.message.edit_text(
        f"💎 <b>{tariff['name']}</b>\n"
        f"💰 К оплате: {tariff['price']}₽\n"
        f"📝 {tariff['description']}", 
        reply_markup=payment_kb(url, label), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_pay(callback: CallbackQuery):
    label = callback.data.replace("check_payment_", "")
    if await check_payment_ym(label):
        payment = await get_payment(label)
        if payment and payment['status'] != 'paid':
            await update_payment(label, "paid")
            days = PREMIUM_TARIFFS[payment['tariff']]['days']
            until = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
            await update_user(payment['user_id'], is_premium=1, premium_until=until)
            await callback.message.answer(
                f"🎉 <b>Оплата прошла успешно! Премиум активирован!</b>\n\n"
                f"Дней премиума: {days}\n"
                f"Действует до: {datetime.datetime.fromisoformat(until).strftime('%d.%m.%Y')}", 
                parse_mode=ParseMode.HTML, 
                reply_markup=main_menu_kb(True)
            )
            await increment_stat("payments_count")
            await increment_stat("revenue")
    else:
        await callback.answer("⏳ Платеж пока не найден. Подождите 1-2 минуты и проверьте снова.", show_alert=True)

@dp.callback_query(F.data == "back_premium")
async def back_to_premium(callback: CallbackQuery):
    await callback.message.delete()
    await get_premium_cmd(callback.message)

# ==================== EDIT PROFILE ====================

@dp.callback_query(F.data.startswith("edit_"))
async def edit_process(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    prompts = {
        "photo": "📸 Отправь новое фото:", 
        "name": "📝 Введи новое имя:", 
        "age": "🔢 Введи возраст:", 
        "city": "🏙️ Выбери город:", 
        "bio": "📝 О себе:", 
        "looking": "👀 Кого ищешь?",
        "goal": "🎯 Выбери цель знакомства:",
        "interests": "🎨 Выбери интересы:"
    }
    if field not in prompts:
        return await callback.answer("Ошибка.")

    await state.update_data(edit_field=field)
    await state.set_state(EditProfile.new_value)

    if field == "city": 
        await callback.message.answer(prompts[field], reply_markup=city_kb())
    elif field == "looking": 
        await callback.message.answer(prompts[field], reply_markup=looking_for_kb())
    elif field == "goal":
        await callback.message.answer(prompts[field], reply_markup=reg_goal_kb())
    elif field == "interests":
        await state.update_data(edit_interests=set())
        await callback.message.answer(prompts[field], reply_markup=reg_interests_kb())
    else: 
        await callback.message.answer(prompts[field])
    await callback.answer()

@dp.message(EditProfile.new_value)
async def save_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    if not field:
        return await state.clear()

    user = await get_user(message.from_user.id)
    if not user:
        return await state.clear()

    if field == "photo":
        if not message.photo: 
            return await message.answer("Нужно отправить фото:")
        await update_user(user['telegram_id'], photo=message.photo[-1].file_id)
    elif field == "name":
        name = message.text.strip()
        if not (2 <= len(name) <= 30):
            return await message.answer("Имя должно быть от 2 до 30 символов:")
        await update_user(user['telegram_id'], name=name)
    elif field == "age":
        if not message.text.strip().isdigit(): 
            return await message.answer("Нужно число:")
        age = int(message.text.strip())
        if not (16 <= age <= 100):
            return await message.answer("Возраст от 16 до 100:")
        await update_user(user['telegram_id'], age=age)
    elif field == "city":
        city = message.text.strip()
        if len(city) < 2:
            return await message.answer("Название города слишком короткое:")
        await update_user(user['telegram_id'], city=city[:50])
    elif field == "bio":
        await update_user(user['telegram_id'], bio=message.text[:500])
    elif field == "looking":
        looks = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
        if message.text not in looks: 
            return await message.answer("Используй кнопки:", reply_markup=looking_for_kb())
        await update_user(user['telegram_id'], looking_for=looks[message.text])
    elif field == "goal":
        reverse_goals = {v: k for k, v in GOALS_MAP.items()}
        found = None
        for key, val in GOALS_MAP.items():
            if val == message.text:
                found = key
                break
        if not found:
            return await message.answer("Используй кнопки:", reply_markup=reg_goal_kb())
        await update_user(user['telegram_id'], goal=found)
    elif field == "interests":
        return await message.answer("Используй кнопки для выбора интересов.", reply_markup=reg_interests_kb())

    likes_to_me = await get_likes_to_me_count(message.from_user.id)
    await message.answer("✅ Сохранено!", reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))
    await state.clear()

@dp.callback_query(F.data.startswith("reg_int_"), EditProfile.new_value)
async def edit_interests_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_int_", "")
    if data == "done":
        current = await state.get_data()
        selected = current.get("edit_interests", set())
        if not selected:
            return await callback.answer("Выбери хотя бы один!", show_alert=True)
        user = await get_user(callback.from_user.id)
        await update_user(user['telegram_id'], interests=",".join(selected))
        likes_to_me = await get_likes_to_me_count(callback.from_user.id)
        await callback.message.edit_text("✅ Интересы обновлены!")
        await callback.message.answer("Главное меню", reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))
        await state.clear()
        return

    current = await state.get_data()
    selected = set(current.get("edit_interests", []))
    if data in selected:
        selected.remove(data)
    else:
        selected.add(data)
    await state.update_data(edit_interests=selected)
    await callback.message.edit_reply_markup(reply_markup=reg_interests_kb(selected))
    await callback.answer()

@dp.callback_query(F.data == "back_menu")
async def back_menu_cb(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    likes_to_me = await get_likes_to_me_count(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("Главное меню", reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))

# ==================== ADMIN PANEL & DELETE ====================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🔧 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_cb(callback: CallbackQuery):
    if callback.from_user.id == ADMIN_ID:
        await show_stats_cmd(callback.message)

@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Введите текст рассылки для всех пользователей:")
        await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: 
        return await state.clear()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_active = 1") as cursor:
            users = await cursor.fetchall()

    await message.answer(f"⏳ Рассылка для {len(users)} пользователей...")
    success = 0
    for u in users:
        try:
            await bot.send_message(
                u[0], 
                f"📢 <b>Сообщение от администрации LoveSpark:</b>\n\n{message.text}", 
                parse_mode=ParseMode.HTML
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception: 
            pass

    await message.answer(f"✅ Успешно доставлено: {success}/{len(users)}")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа.")
    await callback.message.answer("Введи ID пользователя для бана:")
    await state.set_state(AdminState.ban_user)

@dp.message(AdminState.ban_user)
async def admin_ban_exec(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return await state.clear()
    try:
        user_id = int(message.text.strip())
        await update_user(user_id, is_banned=1, is_active=0)
        await message.answer(f"🚫 Пользователь {user_id} забанен.")
        await bot.send_message(user_id, "🚫 Твой аккаунт заблокирован администрацией.")
    except:
        await message.answer("Ошибка. Введи числовой ID.")
    await state.clear()

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа.")
    await callback.message.answer("Введи ID пользователя для разбана:")
    await state.set_state(AdminState.unban_user)

@dp.message(AdminState.unban_user)
async def admin_unban_exec(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return await state.clear()
    try:
        user_id = int(message.text.strip())
        await update_user(user_id, is_banned=0, is_active=1)
        await message.answer(f"✅ Пользователь {user_id} разбанен.")
        await bot.send_message(user_id, "✅ Твой аккаунт разблокирован! С возвращением в LoveSpark!")
    except:
        await message.answer("Ошибка. Введи числовой ID.")
    await state.clear()

@dp.message(Command("delete"))
async def delete_cmd(message: Message):
    await message.answer("⚠️ Точно удалить анкету? Все данные будут безвозвратно удалены.", reply_markup=confirm_delete_kb())

@dp.callback_query(F.data == "confirm_delete")
async def confirm_del_cb(callback: CallbackQuery):
    await update_user(callback.from_user.id, is_active=0)
    await callback.message.answer(
        "😢 Анкета удалена. Жаль терять такого классного пользователя!\n\n"
        "Если передумаешь — просто нажми /start", 
        reply_markup=ReplyKeyboardRemove()
    )

@dp.callback_query(F.data == "cancel_delete")
async def cancel_del_cb(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    likes_to_me = await get_likes_to_me_count(callback.from_user.id)
    await callback.message.answer("Отлично! Продолжай знакомиться ❤️", reply_markup=main_menu_kb(get_premium_status(user), likes_to_me))

# ==================== RUNNER ====================
async def reset_limits():
    while True:
        now = datetime.datetime.now()
        next_reset = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = (next_reset - now).total_seconds()
        logger.info(f"Daily limits reset in {sleep_seconds/3600:.1f} hours")
        await asyncio.sleep(sleep_seconds)
        await reset_daily_limits()
        logger.info("Daily limits reset completed")

async def main():
    await init_db()
    asyncio.create_task(reset_limits())
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
