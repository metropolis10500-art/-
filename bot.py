#!/usr/bin/env python3
"""
LoveSpark Enterprise Edition
Production-ready Telegram dating bot with:
- Connection pooling & WAL-mode SQLite
- TTL cache layer
- Batch statistics & notification queues
- Smart matching algorithm
- Rate limiting & anti-spam
- Graceful shutdown
"""

import asyncio
import logging
import datetime
import random
import html
import uuid
import time
import signal
import sys
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set, Tuple, Any
from collections import deque
from functools import lru_cache

import aiosqlite
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

# ==================== CONFIGURATION ====================
@dataclass(frozen=True)
class Config:
    BOT_TOKEN: str = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
    ADMIN_IDS: Tuple[int, ...] = (5494544187,)

    YOOMONEY_TOKEN: str = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
    YOOMONEY_WALLET: str = "4100118935779591"

    DB_NAME: str = "lovespark.db"
    YOOMONEY_API_URL: str = "https://yoomoney.ru/api"

    FREE_LIKES: int = 10
    FREE_MESSAGES: int = 5
    REFERRAL_BONUS_LIKES: int = 5
    REFERRAL_BONUS_MSGS: int = 5
    DAILY_BONUS_LIKES: int = 3
    DAILY_BONUS_MSGS: int = 2

    CACHE_TTL_SECONDS: int = 300
    STAT_FLUSH_INTERVAL: int = 60
    NOTIFICATION_WORKERS: int = 3
    BROADCAST_BATCH_SIZE: int = 25
    BROADCAST_DELAY: float = 0.04
    RATE_LIMIT_SECONDS: float = 0.8

    MATCH_LIMIT: int = 1
    PREMIUM_MATCH_BOOST: float = 3.0

    CITIES: Tuple[str, ...] = (
        "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
        "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
        "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград",
        "Краснодар", "Саратов", "Тюмень", "Тольятти", "Ижевск",
        "Барнаул", "Иркутск", "Хабаровск", "Ярославль", "Владивосток",
        "Махачкала", "Томск", "Оренбург", "Кемерово", "Новокузнецк"
    )

    PREMIUM_TARIFFS: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "week": {"name": "⚡ 7 дней", "price": 149, "days": 7, "desc": "Пробный период"},
        "month": {"name": "💎 30 дней", "price": 399, "days": 30, "desc": "Оптимальный"},
        "quarter": {"name": "👑 90 дней", "price": 999, "days": 90, "desc": "Экономия 25%"},
        "year": {"name": "🏆 365 дней", "price": 2999, "days": 365, "desc": "Экономия 50%"}
    })

    GOALS: Dict[str, str] = field(default_factory=lambda: {
        "relationship": "❤️ Серьёзные отношения",
        "friendship": "🤝 Дружба",
        "fun": "😏 Флирт",
        "unsure": "🤷 Пока не знаю"
    })

    INTERESTS: Dict[str, str] = field(default_factory=lambda: {
        "music": "🎵 Музыка", "sport": "⚽ Спорт", "travel": "✈️ Путешествия",
        "games": "🎮 Игры", "movies": "🎬 Кино", "books": "📚 Книги",
        "cooking": "🍳 Готовка", "photo": "📸 Фото", "dance": "💃 Танцы",
        "auto": "🚗 Авто", "it": "💻 IT", "art": "🎨 Искусство"
    })

CONFIG = Config()

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("lovespark.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("LoveSpark")

# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    """High-performance SQLite manager with WAL mode and connection reuse."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        await self._connection.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA temp_store = MEMORY;
            PRAGMA foreign_keys = ON;
            PRAGMA mmap_size = 268435456;
            PRAGMA page_size = 4096;
        """)
        await self._init_schema()
        logger.info("Database connected with WAL mode")

    async def _init_schema(self):
        schema = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                city TEXT NOT NULL,
                gender TEXT NOT NULL,
                looking_for TEXT NOT NULL,
                goal TEXT DEFAULT 'unsure',
                interests TEXT DEFAULT '',
                photo TEXT,
                bio TEXT,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                likes_today INTEGER DEFAULT 0,
                messages_today INTEGER DEFAULT 0,
                bonus_likes INTEGER DEFAULT 0,
                bonus_messages INTEGER DEFAULT 0,
                last_bonus_date TEXT,
                last_activity TEXT,
                is_active INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                profile_views INTEGER DEFAULT 0,
                boost_priority REAL DEFAULT 0
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
            CREATE INDEX IF NOT EXISTS idx_users_gender ON users(gender);
            CREATE INDEX IF NOT EXISTS idx_users_looking ON users(looking_for);
            CREATE INDEX IF NOT EXISTS idx_users_boost ON users(boost_priority DESC);
            CREATE INDEX IF NOT EXISTS idx_likes_from ON likes(from_user);
            CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_user);
            CREATE INDEX IF NOT EXISTS idx_matches_user1 ON matches(user1);
            CREATE INDEX IF NOT EXISTS idx_matches_user2 ON matches(user2);
            CREATE INDEX IF NOT EXISTS idx_messages_match ON messages(match_id);
            CREATE INDEX IF NOT EXISTS idx_payments_label ON payments(label);
        """
        await self._connection.executescript(schema)
        await self._connection.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict]:
        async with self._lock:
            cursor = await self._connection.execute(query, params)
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    async def fetchall(self, query: str, params: tuple = ()) -> List[Dict]:
        async with self._lock:
            cursor = await self._connection.execute(query, params)
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    async def execute(self, query: str, params: tuple = ()) -> int:
        async with self._write_lock:
            cursor = await self._connection.execute(query, params)
            await self._connection.commit()
            return cursor.lastrowid

    async def executemany(self, query: str, params_list: List[tuple]):
        async with self._write_lock:
            await self._connection.executemany(query, params_list)
            await self._connection.commit()

    async def close(self):
        if self._connection:
            await self._connection.close()

# ==================== CACHE LAYER ====================
class TTLCache:
    """Simple in-memory TTL cache for user data."""

    def __init__(self, ttl: int = 300):
        self._cache: Dict[int, Tuple[Dict, float]] = {}
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get(self, key: int) -> Optional[Dict]:
        async with self._lock:
            if key in self._cache:
                data, timestamp = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key: int, value: Dict):
        async with self._lock:
            self._cache[key] = (value, time.time())

    async def delete(self, key: int):
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self):
        async with self._lock:
            self._cache.clear()

# ==================== BATCH STAT COLLECTOR ====================
class BatchStatCollector:
    """Accumulates stats in memory and flushes to DB periodically."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._buffer: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    def start(self):
        self._task = asyncio.create_task(self._flush_loop())

    async def increment(self, field: str):
        async with self._lock:
            self._buffer[field] = self._buffer.get(field, 0) + 1

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(CONFIG.STAT_FLUSH_INTERVAL)
            await self._flush()

    async def _flush(self):
        async with self._lock:
            if not self._buffer:
                return
            buffer_copy = self._buffer.copy()
            self._buffer.clear()

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        for field, count in buffer_copy.items():
            try:
                await self.db.execute(f"""
                    INSERT INTO stats (date, {field}) VALUES (?, ?)
                    ON CONFLICT(date) DO UPDATE SET {field} = {field} + ?
                """, (today, count, count))
            except Exception as e:
                logger.error(f"Stat flush error: {e}")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush()

# ==================== NOTIFICATION QUEUE ====================
class NotificationService:
    """Background queue for non-blocking notifications."""

    def __init__(self, bot: Bot, workers: int = 3):
        self.bot = bot
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers = workers
        self._tasks: List[asyncio.Task] = []

    def start(self):
        for i in range(self._workers):
            task = asyncio.create_task(self._worker(i))
            self._tasks.append(task)

    async def _worker(self, worker_id: int):
        while True:
            try:
                chat_id, text, kwargs = await self._queue.get()
                await self.bot.send_message(chat_id, text, **kwargs)
                await asyncio.sleep(0.03)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification worker {worker_id} error: {e}")

    async def notify(self, chat_id: int, text: str, **kwargs):
        await self._queue.put((chat_id, text, kwargs))

    async def stop(self):
        for _ in range(self._workers):
            await self._queue.put(None)
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

# ==================== SERVICES ====================
class UserService:
    def __init__(self, db: DatabaseManager, cache: TTLCache):
        self.db = db
        self.cache = cache

    async def get(self, telegram_id: int) -> Optional[Dict]:
        cached = await self.cache.get(telegram_id)
        if cached:
            return cached

        user = await self.db.fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        if user:
            await self.cache.set(telegram_id, user)
        return user

    async def create(self, **kwargs) -> int:
        fields = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        values = tuple(kwargs.values())

        user_id = await self.db.execute(
            f"INSERT INTO users ({fields}) VALUES ({placeholders})", values
        )
        await self.cache.set(kwargs["telegram_id"], kwargs)
        return user_id

    async def update(self, telegram_id: int, **kwargs):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]
        await self.db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
        await self.cache.delete(telegram_id)

    async def is_premium(self, user: Optional[Dict]) -> bool:
        if not user or not user.get("is_premium"):
            return False
        until = user.get("premium_until")
        if until:
            try:
                return datetime.datetime.fromisoformat(until) > datetime.datetime.now()
            except:
                return False
        return False

    async def get_remaining(self, user: Dict, field: str, free_limit: int) -> int:
        if await self.is_premium(user):
            return 999999
        total = free_limit + user.get(f"bonus_{field}", 0)
        return max(0, total - user.get(f"{field}_today", 0))

    async def get_likes_to_me_count(self, user_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) as c FROM likes WHERE to_user = ? AND is_mutual = 0", (user_id,)
        )
        return row["c"] if row else 0

    async def get_by_ref_code(self, code: str) -> Optional[Dict]:
        return await self.db.fetchone(
            "SELECT telegram_id FROM users WHERE referral_code = ?", (code,)
        )

    async def update_activity(self, telegram_id: int):
        await self.update(telegram_id, last_activity=datetime.datetime.now().isoformat())

class MatchService:
    def __init__(self, db: DatabaseManager, user_service: UserService):
        self.db = db
        self.users = user_service

    async def get_random_profile(self, telegram_id: int) -> Optional[Dict]:
        user = await self.users.get(telegram_id)
        if not user:
            return None

        is_premium = await self.users.is_premium(user)

        query = """
            SELECT *, 
                CASE WHEN interests != '' AND interests = ? THEN 100 ELSE 0 END +
                CASE WHEN last_activity > datetime('now', '-5 minutes') THEN 50 ELSE 0 END +
                boost_priority * 10 +
                CASE WHEN is_premium = 1 THEN 30 ELSE 0 END as score
            FROM users 
            WHERE telegram_id != ? AND is_active = 1 AND is_banned = 0
            AND telegram_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
            AND telegram_id NOT IN (
                SELECT user2 FROM matches WHERE user1 = ? 
                UNION 
                SELECT user1 FROM matches WHERE user2 = ?
            )
        """
        params = [user.get("interests", ""), telegram_id, telegram_id, telegram_id, telegram_id]

        if user["looking_for"] == "both":
            query += " AND gender IN ('male', 'female')"
        else:
            query += " AND gender = ?"
            params.append(user["looking_for"])

        query += " AND (looking_for = ? OR looking_for = 'both')"
        params.append(user["gender"])

        if not is_premium:
            query += " AND city = ?"
            params.append(user["city"])

        query += " ORDER BY score DESC, RANDOM() LIMIT 1"

        return await self.db.fetchone(query, tuple(params))

    async def add_like(self, from_user: int, to_user: int) -> Tuple[bool, Optional[int]]:
        mutual = await self.db.fetchone(
            "SELECT * FROM likes WHERE from_user = ? AND to_user = ?", (to_user, from_user)
        )

        await self.db.execute(
            "INSERT OR IGNORE INTO likes (from_user, to_user, is_mutual) VALUES (?, ?, ?)",
            (from_user, to_user, 1 if mutual else 0)
        )

        match_id = None
        if mutual:
            u1, u2 = min(from_user, to_user), max(from_user, to_user)
            await self.db.execute(
                "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)", (u1, u2)
            )
            await self.db.execute(
                """UPDATE likes SET is_mutual = 1 
                   WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)""",
                (from_user, to_user, to_user, from_user)
            )
            row = await self.db.fetchone(
                "SELECT id FROM matches WHERE user1 = ? AND user2 = ?", (u1, u2)
            )
            match_id = row["id"] if row else None

        return mutual is not None, match_id

    async def get_match(self, user1: int, user2: int) -> Optional[Dict]:
        return await self.db.fetchone(
            "SELECT * FROM matches WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)",
            (user1, user2, user2, user1)
        )

    async def get_matches(self, user_id: int) -> List[Dict]:
        return await self.db.fetchall("""
            SELECT m.*, u.name, u.photo, u.age, u.city, u.telegram_id as partner_id
            FROM matches m 
            JOIN users u ON u.telegram_id = CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END
            WHERE m.user1 = ? OR m.user2 = ? 
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id))

class PaymentService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def create(self, user_id: int, tariff: str, amount: int, label: str):
        await self.db.execute(
            "INSERT INTO payments (user_id, tariff, amount, label) VALUES (?, ?, ?, ?)",
            (user_id, tariff, amount, label)
        )

    async def get(self, label: str) -> Optional[Dict]:
        return await self.db.fetchone("SELECT * FROM payments WHERE label = ?", (label,))

    async def update_status(self, label: str, status: str):
        await self.db.execute(
            "UPDATE payments SET status = ?, paid_at = ? WHERE label = ?",
            (status, datetime.datetime.now().isoformat(), label)
        )

    async def create_url(self, amount: int, label: str, description: str = "LoveSpark Premium") -> str:
        desc = html.escape(description)
        return f"https://yoomoney.ru/quickpay/confirm?receiver={CONFIG.YOOMONEY_WALLET}&quickpay-form=shop&targets={desc}&paymentType=AC&sum={amount}&label={label}&successURL=https://t.me/LoveSparkBot"

    async def check_yoomoney(self, label: str) -> bool:
        headers = {
            "Authorization": f"Bearer {CONFIG.YOOMONEY_TOKEN}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"type": "deposition", "label": label, "details": "true"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CONFIG.YOOMONEY_API_URL}/operation-history",
                    headers=headers, data=data, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        for op in result.get("operations", []):
                            if op.get("label") == label and op.get("status") == "success":
                                return True
        except Exception as e:
            logger.error(f"YooMoney check error: {e}")
        return False

# ==================== GEOCODING ====================
class GeoService:
    @staticmethod
    async def get_city_by_location(lat: float, lon: float) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=ru"
                async with session.get(url, headers={"User-Agent": "LoveSparkBot/1.0"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        address = data.get("address", {})
                        return (address.get("city") or address.get("town") or 
                                address.get("village") or address.get("county") or 
                                address.get("state"))
        except Exception as e:
            logger.error(f"Geocoding error: {e}")
        return None

# ==================== KEYBOARD FACTORY ====================
class KeyboardFactory:
    @staticmethod
    def main_menu(is_premium: bool = False, likes_to_me: int = 0):
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

    @staticmethod
    def reg_start():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💘 Начать знакомство", callback_data="reg_start")],
            [InlineKeyboardButton(text="❓ Что это?", callback_data="reg_whatis")]
        ])

    @staticmethod
    def reg_name(first_name: str):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✨ Использовать «{first_name[:20]}»", callback_data="reg_use_name")],
            [InlineKeyboardButton(text="📝 Ввести другое имя", callback_data="reg_custom_name")]
        ])

    @staticmethod
    def reg_age():
        ages = ["18-20", "21-23", "24-26", "27-30", "31-35", "36-40", "40+"]
        buttons = [[InlineKeyboardButton(text=f"🎂 {a}", callback_data=f"reg_age_{a}")] for a in ages]
        buttons.append([InlineKeyboardButton(text="🔢 Ввести точный возраст", callback_data="reg_age_custom")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def reg_city():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Определить по геолокации", request_location=True)],
                [KeyboardButton(text="📝 Ввести город вручную")]
            ],
            resize_keyboard=True, one_time_keyboard=True
        )

    @staticmethod
    def reg_gender():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨 Я парень", callback_data="reg_gender_male"),
             InlineKeyboardButton(text="👩 Я девушка", callback_data="reg_gender_female")]
        ])

    @staticmethod
    def reg_looking():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨 Парней", callback_data="reg_look_male"),
             InlineKeyboardButton(text="👩 Девушек", callback_data="reg_look_female")],
            [InlineKeyboardButton(text="👫 Всех без разницы", callback_data="reg_look_both")]
        ])

    @staticmethod
    def reg_goal():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Серьёзные отношения", callback_data="reg_goal_relationship")],
            [InlineKeyboardButton(text="🤝 Дружба и общение", callback_data="reg_goal_friendship")],
            [InlineKeyboardButton(text="😏 Флирт и веселье", callback_data="reg_goal_fun")],
            [InlineKeyboardButton(text="🤷 Пока не знаю", callback_data="reg_goal_unsure")]
        ])

    @staticmethod
    def reg_interests(selected: Set[str] = None):
        if selected is None:
            selected = set()
        buttons = []
        row = []
        for key, label in CONFIG.INTERESTS.items():
            icon = "✅ " if key in selected else ""
            row.append(InlineKeyboardButton(text=f"{icon}{label}", callback_data=f"reg_int_{key}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="✨ Готово! Продолжить →", callback_data="reg_int_done")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def reg_bio():
        bios = [
            ("🎸 Люблю музыку, концерты и атмосферу", "music"),
            ("✈️ Обожаю путешествовать и открывать новое", "travel"),
            ("🍳 Готовлю лучшие блюда на свете", "cooking"),
            ("🎮 Игры, кино и уютные вечера дома", "home"),
            ("🏋️ Спорт и активный образ жизни", "sport"),
            ("📝 Напишу сам(а)", "custom")
        ]
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"reg_bio_{val}")] for text, val in bios
        ])

    @staticmethod
    def reg_confirm():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Всё идеально! Создать анкету", callback_data="reg_confirm_yes")],
            [InlineKeyboardButton(text="✏️ Что-то изменить", callback_data="reg_confirm_edit")],
            [InlineKeyboardButton(text="❌ Начать заново", callback_data="reg_confirm_restart")]
        ])

    @staticmethod
    def profile_actions(profile_id: int, is_premium: bool = False):
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

    @staticmethod
    def match_actions(match_id: int, partner_id: int):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Начать чат", callback_data=f"chat_{match_id}_{partner_id}")],
            [InlineKeyboardButton(text="👤 Посмотреть анкету", callback_data=f"view_{partner_id}")],
        ])

    @staticmethod
    def chat_actions(match_id: int):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📎 Фото", callback_data="hint_photo"),
             InlineKeyboardButton(text="🎙️ Голосовое", callback_data="hint_voice")],
            [InlineKeyboardButton(text="🎭 Стикер", callback_data="hint_sticker")],
            [InlineKeyboardButton(text="🔙 Вернуться к мэтчам", callback_data="back_to_matches")],
        ])

    @staticmethod
    def premium():
        buttons = [[InlineKeyboardButton(text=f"{v['name']} - {v['price']}₽", callback_data=f"premium_{k}")]
                   for k, v in CONFIG.PREMIUM_TARIFFS.items()]
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def payment(url: str, label: str):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{label}")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_premium")],
        ])

    @staticmethod
    def edit_profile():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo"),
             InlineKeyboardButton(text="📝 Имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="🔢 Возраст", callback_data="edit_age"),
             InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city")],
            [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio"),
             InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking")],
            [InlineKeyboardButton(text="🎯 Цель", callback_data="edit_goal"),
             InlineKeyboardButton(text="🎨 Интересы", callback_data="edit_interests")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_menu")],
        ])

    @staticmethod
    def admin():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
             InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🚫 Забанить", callback_data="admin_ban"),
             InlineKeyboardButton(text="✅ Разбанить", callback_data="admin_unban")],
        ])

    @staticmethod
    def confirm_delete():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete"),
             InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_delete")],
        ])

    @staticmethod
    def city_list():
        kb = [[KeyboardButton(text=city) for city in CONFIG.CITIES[i:i+3]]
              for i in range(0, len(CONFIG.CITIES), 3)]
        kb.append([KeyboardButton(text="📝 Ввести свой город")])
        return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    @staticmethod
    def looking_for():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👨 Мужчин"), KeyboardButton(text="👩 Женщин")],
                [KeyboardButton(text="👫 Всех")]
            ], resize_keyboard=True
        )

# ==================== FORMATTER ====================
class ProfileFormatter:
    @staticmethod
    def format(user: Dict) -> str:
        gender_emoji = "👨" if user.get("gender") == "male" else "👩"
        prem = "💎" if user.get("is_premium") else ""

        last_act = user.get("last_activity")
        online = "🟢"
        if last_act:
            try:
                delta = (datetime.datetime.now() - datetime.datetime.fromisoformat(last_act)).total_seconds()
                online = "🟢" if delta < 300 else "⚪"
            except:
                online = "⚪"

        name = html.escape(str(user.get('name', 'Неизвестно')))
        city = html.escape(str(user.get('city', 'Не указан')))
        bio = html.escape(str(user.get('bio', 'Нет описания')))
        age = user.get('age', '?')
        views = user.get('profile_views', 0)
        goal = CONFIG.GOALS.get(user.get('goal', 'unsure'), '')

        interests_str = user.get('interests', '')
        interests_display = ""
        if interests_str:
            ints = [CONFIG.INTERESTS.get(i.strip(), i.strip()) for i in interests_str.split(",") if i.strip()]
            if ints:
                interests_display = "\n🎨 " + ", ".join(ints)

        return (
            f"{gender_emoji} <b>{name}</b>, {age} {prem} {online}\n"
            f"🏙️ {city}\n"
            f"🎯 {goal}{interests_display}\n"
            f"👁️ Просмотров: {views}\n\n"
            f"📝 {bio}"
        )

    @staticmethod
    def status_line(user: Dict) -> str:
        likes = "∞" if user.get("is_premium") else max(0, CONFIG.FREE_LIKES + user.get("bonus_likes", 0) - user.get("likes_today", 0))
        msgs = "∞" if user.get("is_premium") else max(0, CONFIG.FREE_MESSAGES + user.get("bonus_messages", 0) - user.get("messages_today", 0))
        return f"❤️ Лайков: {likes} | 💬 Сообщений: {msgs}"

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
    choosing = State()
    new_value = State()

class ChatState(StatesGroup):
    chatting = State()

class AdminState(StatesGroup):
    broadcast = State()
    ban = State()
    unban = State()

class ReportState(StatesGroup):
    reason = State()

# ==================== MIDDLEWARES ====================
class ThrottlingMiddleware:
    """Rate limiting per user."""
    def __init__(self, rate_limit: float = 0.8):
        self.rate_limit = rate_limit
        self._last_update: Dict[int, float] = {}

    async def __call__(self, handler, event, data):
        user_id = getattr(getattr(event, "from_user", None), "id", 0)
        if user_id:
            now = time.time()
            last = self._last_update.get(user_id, 0)
            if now - last < self.rate_limit:
                if isinstance(event, Message):
                    await event.answer("⏳ Слишком быстро! Подожди секунду...")
                return None
            self._last_update[user_id] = now
        return await handler(event, data)

class BanMiddleware:
    """Check if user is banned."""
    def __init__(self, user_service: UserService):
        self.users = user_service

    async def __call__(self, handler, event, data):
        user_id = getattr(getattr(event, "from_user", None), "id", 0)
        if user_id:
            user = await self.users.get(user_id)
            if user and user.get("is_banned"):
                if isinstance(event, Message):
                    await event.answer("🚫 Аккаунт заблокирован.")
                return None
        return await handler(event, data)

class ActivityMiddleware:
    """Auto-update last activity."""
    def __init__(self, user_service: UserService):
        self.users = user_service

    async def __call__(self, handler, event, data):
        user_id = getattr(getattr(event, "from_user", None), "id", 0)
        if user_id:
            asyncio.create_task(self.users.update_activity(user_id))
        return await handler(event, data)

# ==================== BOT & DISPATCHER ====================
bot = Bot(token=CONFIG.BOT_TOKEN)
dp = Dispatcher()

# Global services (initialized in main)
db: Optional[DatabaseManager] = None
users: Optional[UserService] = None
matches: Optional[MatchService] = None
payments: Optional[PaymentService] = None
geo = GeoService()
notifier: Optional[NotificationService] = None
stats_collector: Optional[BatchStatCollector] = None
kb = KeyboardFactory()
fmt = ProfileFormatter()

# ==================== REGISTRATION HANDLERS ====================
reg_router = Router()

@reg_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    ref_code = None
    if message.text and len(message.text.split()) > 1:
        arg = message.text.split()[1]
        if arg.startswith("ref_"):
            ref_code = arg.replace("ref_", "")

    user = await users.get(message.from_user.id)
    if user and user.get("is_active"):
        if ref_code and not user.get("referred_by"):
            referrer = await users.get_by_ref_code(ref_code)
            if referrer and referrer['telegram_id'] != message.from_user.id:
                await users.update(message.from_user.id, referred_by=referrer['telegram_id'])
                ref_user = await users.get(referrer['telegram_id'])
                await users.update(
                    referrer['telegram_id'],
                    bonus_likes=ref_user.get('bonus_likes', 0) + CONFIG.REFERRAL_BONUS_LIKES,
                    bonus_messages=ref_user.get('bonus_messages', 0) + CONFIG.REFERRAL_BONUS_MSGS
                )
                await users.update(
                    message.from_user.id,
                    bonus_likes=user.get('bonus_likes', 0) + CONFIG.REFERRAL_BONUS_LIKES,
                    bonus_messages=user.get('bonus_messages', 0) + CONFIG.REFERRAL_BONUS_MSGS
                )
                await notifier.notify(
                    referrer['telegram_id'],
                    f"🎉 По твоей ссылке зарегистрировался пользователь!\n"
                    f"+{CONFIG.REFERRAL_BONUS_LIKES} лайков и +{CONFIG.REFERRAL_BONUS_MSGS} сообщений!"
                )
                await message.answer(
                    f"🎉 +{CONFIG.REFERRAL_BONUS_LIKES} лайков и +{CONFIG.REFERRAL_BONUS_MSGS} сообщений за реферальную ссылку!"
                )

        likes_to_me = await users.get_likes_to_me_count(message.from_user.id)
        await message.answer(
            f"💘 <b>С возвращением в LoveSpark!</b>\n\n"
            f"{fmt.status_line(user)}\n"
            f"🔥 Тебя лайкнули: {likes_to_me} чел.",
            reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me),
            parse_mode=ParseMode.HTML
        )
        return

    welcome = (
        f"💘 <b>Привет, {html.escape(message.from_user.first_name or 'друг')}!</b>\n\n"
        f"Я — <b>LoveSpark</b>, твой личный помощник в мире знакомств.\n\n"
        f"✨ <b>Что тебя ждёт:</b>\n"
        f"• Умный подбор по интересам и городу\n"
        f"• Мгновенные мэтчи и чаты\n"
        f"• Безопасность и удобство\n\n"
        f"Готов найти свою искру? 🔥"
    )
    await message.answer(welcome, reply_markup=kb.reg_start(), parse_mode=ParseMode.HTML)

@reg_router.callback_query(F.data == "reg_whatis")
async def reg_whatis(callback: CallbackQuery):
    await callback.message.edit_text(
        "💡 <b>LoveSpark</b> — бот для знакомств по всей России.\n\n"
        "Мы подбираем людей по твоему городу, возрасту и интересам. "
        "Взаимный лайк = мэтч = возможность общаться!\n\n"
        "Всё просто, безопасно и увлекательно ✨",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💘 Поехали!", callback_data="reg_start")]
        ]),
        parse_mode=ParseMode.HTML
    )

@reg_router.callback_query(F.data == "reg_start")
async def reg_start_cb(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"✨ <b>Как к тебе обращаться?</b>\n\n"
        f"Можешь использовать своё имя из Telegram или ввести другое.",
        reply_markup=kb.reg_name(callback.from_user.first_name or "Друг"),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.name)

@reg_router.callback_query(F.data == "reg_use_name", Registration.name)
async def reg_use_name(callback: CallbackQuery, state: FSMContext):
    name = callback.from_user.first_name or "Пользователь"
    await state.update_data(name=name)
    await callback.message.edit_text(
        f"🎂 <b>Отлично, {html.escape(name)}!</b>\n\n"
        f"Теперь выбери свой возраст:",
        reply_markup=kb.reg_age(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.age)

@reg_router.callback_query(F.data == "reg_custom_name", Registration.name)
async def reg_custom_name(callback: CallbackQuery):
    await callback.message.edit_text(
        f"✨ <b>Как тебя зовут?</b>\n\n"
        f"Напиши своё имя (от 2 до 30 символов):",
        parse_mode=ParseMode.HTML
    )

@reg_router.message(Registration.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not (2 <= len(name) <= 30):
        return await message.answer("✨ Имя должно быть от 2 до 30 символов. Попробуй ещё раз:")
    await state.update_data(name=name)
    await message.answer(
        f"🎂 <b>Отлично, {html.escape(name)}!</b>\n\n"
        f"Теперь выбери свой возраст:",
        reply_markup=kb.reg_age(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.age)

@reg_router.callback_query(F.data.startswith("reg_age_"), Registration.age)
async def reg_age_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_age_", "")
    if data == "custom":
        await callback.message.edit_text(
            f"🎂 Напиши свой точный возраст цифрами (16-100):",
            parse_mode=ParseMode.HTML
        )
        return

    age = None
    if data == "40+":
        age = random.randint(40, 55)
    else:
        parts = data.split("-")
        if len(parts) == 2:
            age = random.randint(int(parts[0]), int(parts[1]))

    if age:
        await state.update_data(age=age, age_range=data)
        await callback.message.edit_text(
            f"🏙️ <b>Круто, {age}!</b> 🎉\n\n"
            f"Теперь скажи, откуда ты?",
            parse_mode=ParseMode.HTML
        )
        await callback.message.answer(
            f"📍 Выбери способ указания города:",
            reply_markup=kb.reg_city()
        )
        await state.set_state(Registration.city)

@reg_router.message(Registration.age)
async def process_age_text(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not (16 <= age <= 100):
            raise ValueError
    except ValueError:
        return await message.answer("🎂 Введи корректный возраст цифрами (16-100):")
    await state.update_data(age=age)
    await message.answer(
        f"🏙️ <b>Круто!</b>\n\n"
        f"Теперь скажи, откуда ты?",
        reply_markup=kb.reg_city()
    )
    await state.set_state(Registration.city)

@reg_router.message(Registration.city, F.location)
async def process_city_location(message: Message, state: FSMContext):
    await bot.send_chat_action(message.chat.id, "find_location")
    city = await geo.get_city_by_location(message.location.latitude, message.location.longitude)

    if city:
        await state.update_data(city=city)
        await message.answer(
            f"🏙️ <b>Нашёл!</b> 📍\n\n"
            f"Твой город: <b>{html.escape(city)}</b>",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            f"👤 Теперь определимся с полом:",
            reply_markup=kb.reg_gender(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(Registration.gender)
    else:
        await message.answer(
            "😕 Не удалось определить город. Попробуй ввести вручную:",
            reply_markup=kb.reg_city()
        )

@reg_router.message(Registration.city)
async def process_city_text(message: Message, state: FSMContext):
    if message.text == "📍 Определить по геолокации":
        return await message.answer(
            "Отправь свою геолокацию через скрепку 📎 → Геолокация",
            reply_markup=kb.reg_city()
        )
    if message.text == "📝 Ввести город вручную":
        return await message.answer(
            f"🏙️ Напиши название своего города:",
            reply_markup=ReplyKeyboardRemove()
        )

    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        return await message.answer("🏙️ Название города должно быть от 2 до 50 символов:")

    await state.update_data(city=city)
    await message.answer(
        f"👤 <b>Отлично, {html.escape(city)}!</b>\n\n"
        f"Теперь определимся с полом:",
        reply_markup=kb.reg_gender(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.gender)

@reg_router.callback_query(F.data.startswith("reg_gender_"), Registration.gender)
async def reg_gender_cb(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("reg_gender_", "")
    await state.update_data(gender=gender)
    await callback.message.edit_text(
        f"👀 <b>Кого ты ищешь?</b>\n\n"
        f"Выбирай смело — здесь нет неправильных ответов 😉",
        reply_markup=kb.reg_looking(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.looking_for)

@reg_router.callback_query(F.data.startswith("reg_look_"), Registration.looking_for)
async def reg_looking_cb(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.replace("reg_look_", "")
    await state.update_data(looking_for=looking)
    await callback.message.edit_text(
        f"🎯 <b>Какая цель знакомства?</b>\n\n"
        f"Это поможет найти людей с похожими намерениями ✨",
        reply_markup=kb.reg_goal(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.goal)

@reg_router.callback_query(F.data.startswith("reg_goal_"), Registration.goal)
async def reg_goal_cb(callback: CallbackQuery, state: FSMContext):
    goal = callback.data.replace("reg_goal_", "")
    await state.update_data(goal=goal)
    await callback.message.edit_text(
        f"🎨 <b>Выбери свои интересы!</b>\n\n"
        f"Можно выбрать несколько — нажимай на каждый, а потом «Готово» 👇",
        reply_markup=kb.reg_interests(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.interests)

@reg_router.callback_query(F.data.startswith("reg_int_"), Registration.interests)
async def reg_interest_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_int_", "")
    if data == "done":
        interests_data = await state.get_data()
        selected = interests_data.get("interests", set())
        if not selected:
            return await callback.answer("Выбери хотя бы один интерес!", show_alert=True)

        await state.update_data(interests=",".join(selected))
        await callback.message.edit_text(
            f"📸 <b>Время для фото!</b> 📸\n\n"
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
    await callback.message.edit_reply_markup(reply_markup=kb.reg_interests(selected))
    await callback.answer()

@reg_router.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer(
        f"📝 <b>Расскажи о себе!</b>\n\n"
        f"Это твой шанс произвести впечатление ✨\n"
        f"Можешь выбрать готовый вариант или написать своё:",
        reply_markup=kb.reg_bio(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.bio)

@reg_router.message(Registration.photo)
async def process_photo_error(message: Message):
    await message.answer("📸 Это не похоже на фото 😕 Отправь именно фото:")

@reg_router.callback_query(F.data.startswith("reg_bio_"), Registration.bio)
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
            f"📝 <b>Напиши о себе:</b>\n\n"
            f"Хобби, интересы, что ищешь — всё, что считаешь важным (5-500 символов):",
            parse_mode=ParseMode.HTML
        )
        return

    bio = bios.get(data, "Привет! Ищу интересных людей.")
    await state.update_data(bio=bio)
    await show_preview(callback.message, state)

@reg_router.message(Registration.bio)
async def process_bio_text(message: Message, state: FSMContext):
    if len(message.text) < 5:
        return await message.answer("📝 Описание слишком короткое. Расскажи чуть больше:")
    await state.update_data(bio=message.text[:500])
    await show_preview(message, state)

async def show_preview(target: Message, state: FSMContext):
    data = await state.get_data()
    preview = fmt.format(data)
    await target.answer_photo(
        photo=data['photo'],
        caption=f"📋 <b>Предпросмотр твоей анкеты:</b>\n\n{preview}\n\n"
                f"Всё выглядит шикарно? 🔥",
        reply_markup=kb.reg_confirm(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Registration.confirm)

@reg_router.callback_query(F.data == "reg_confirm_yes", Registration.confirm)
async def confirm_reg(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    code = f"LS{uuid.uuid4().hex[:6].upper()}"

    interests_str = data.get('interests', '')
    if isinstance(interests_str, set):
        interests_str = ",".join(interests_str)

    await users.create(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        name=data['name'],
        age=data['age'],
        city=data['city'],
        gender=data['gender'],
        looking_for=data['looking_for'],
        photo=data['photo'],
        bio=data['bio'],
        referral_code=code,
        interests=interests_str,
        goal=data.get('goal', 'unsure')
    )
    await stats_collector.increment("new_users")

    await callback.message.delete()
    await callback.message.answer(
        f"🎉 <b>Анкета создана!</b> 🎉\n\n"
        f"Добро пожаловать в LoveSpark, {html.escape(data['name'])}!\n\n"
        f"✨ <b>Твой реферальный код:</b> <code>{code}</code>\n"
        f"Поделись с друзьями — оба получите бонусы!\n\n"
        f"💘 Начни поиск прямо сейчас!",
        reply_markup=kb.main_menu(False),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@reg_router.callback_query(F.data == "reg_confirm_edit", Registration.confirm)
async def edit_reg(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ <b>Что хочешь изменить?</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name"),
             InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
            [InlineKeyboardButton(text="🏙️ Город", callback_data="edit_city"),
             InlineKeyboardButton(text="👤 Пол", callback_data="edit_gender")],
            [InlineKeyboardButton(text="👀 Кого ищу", callback_data="edit_looking"),
             InlineKeyboardButton(text="🎯 Цель", callback_data="edit_goal")],
            [InlineKeyboardButton(text="🎨 Интересы", callback_data="edit_interests"),
             InlineKeyboardButton(text="📸 Фото", callback_data="edit_photo")],
            [InlineKeyboardButton(text="📝 О себе", callback_data="edit_bio")],
            [InlineKeyboardButton(text="🔙 Назад к предпросмотру", callback_data="reg_back_preview")]
        ]),
        parse_mode=ParseMode.HTML
    )

@reg_router.callback_query(F.data == "reg_back_preview")
async def back_preview(callback: CallbackQuery, state: FSMContext):
    await show_preview(callback.message, state)

@reg_router.callback_query(F.data == "reg_confirm_restart", Registration.confirm)
async def restart_reg(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔄 <b>Начинаем заново!</b>", parse_mode=ParseMode.HTML)
    await reg_start_cb(callback, state)

# ==================== MAIN MENU HANDLERS ====================
menu_router = Router()

@menu_router.message(F.text == "❤️ Найти пару")
async def find_pair(message: Message):
    user = await users.get(message.from_user.id)
    if not user:
        return await message.answer("Создай анкету через /start")

    remaining = await users.get_remaining(user, "likes", CONFIG.FREE_LIKES)
    if remaining == 0:
        return await message.answer(
            "😔 Лимит лайков на сегодня исчерпан!\n\n"
            "💎 Купи Премиум для безлимита!\n"
            "🎁 Или забирай ежедневный бонус!",
            reply_markup=kb.main_menu(False)
        )

    await bot.send_chat_action(message.chat.id, "typing")
    profile = await matches.get_random_profile(user['telegram_id'])

    if not profile:
        text = "😕 Пока нет подходящих анкет.\n\n💡 Советы:\n"
        if not await users.is_premium(user):
            text += "• Купи Премиум для поиска по всей России\n"
        text += "• Пригласи друзей по реферальной ссылке\n• Загляни попозже!"
        return await message.answer(text, reply_markup=kb.main_menu(await users.is_premium(user)))

    await users.update(profile['telegram_id'], profile_views=profile.get('profile_views', 0) + 1)
    await message.answer_photo(
        photo=profile['photo'],
        caption=fmt.format(profile),
        reply_markup=kb.profile_actions(profile['telegram_id'], await users.is_premium(user)),
        parse_mode=ParseMode.HTML
    )

@menu_router.message(F.text == "📋 Моя анкета")
async def my_profile(message: Message):
    user = await users.get(message.from_user.id)
    if not user:
        return await message.answer("Создай анкету через /start")

    status = "💎 Премиум" if await users.is_premium(user) else "⭐ Бесплатный"
    likes_to_me = await users.get_likes_to_me_count(message.from_user.id)

    caption = (
        f"{fmt.format(user)}\n\n"
        f"📊 Статус: {status}\n"
        f"{fmt.status_line(user)}\n"
        f"🔥 Тебя лайкнули: {likes_to_me} чел."
    )
    await message.answer_photo(photo=user['photo'], caption=caption, parse_mode=ParseMode.HTML)

@menu_router.message(F.text == "✏️ Редактировать")
async def edit_profile_cmd(message: Message):
    await message.answer("Что хочешь изменить?", reply_markup=kb.edit_profile())

@menu_router.message(F.text == "💕 Мои мэтчи")
async def my_matches_cmd(message: Message):
    matches_list = await matches.get_matches(message.from_user.id)
    if not matches_list:
        return await message.answer(
            "💔 У тебя пока нет мэтчей.\n"
            "Ставь лайки понравившимся людям!"
        )

    await message.answer(f"💕 <b>Твои мэтчи ({len(matches_list)}):</b>", parse_mode=ParseMode.HTML)
    for m in matches_list[:10]:
        p_id = m.get('partner_id')
        await message.answer_photo(
            photo=m['photo'],
            caption=f"💕 <b>{html.escape(str(m['name']))}</b>, {m['age']}\n🏙️ {html.escape(str(m['city']))}",
            reply_markup=kb.match_actions(m['id'], p_id),
            parse_mode=ParseMode.HTML
        )

@menu_router.message(F.text == "📊 Статистика")
async def show_stats(message: Message):
    stats = await db.fetchone("""
        SELECT COUNT(*) as total, SUM(CASE WHEN is_premium=1 THEN 1 ELSE 0 END) as premium,
               SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active FROM users
    """)
    top_cities = await db.fetchall(
        "SELECT city, COUNT(*) as count FROM users WHERE is_active=1 GROUP BY city ORDER BY count DESC LIMIT 10"
    )
    cities_text = "\n".join([f"{i+1}. {html.escape(c['city'])} - {c['count']} чел." for i, c in enumerate(top_cities[:5])])

    text = (
        f"📊 <b>Статистика LoveSpark</b>\n\n"
        f"👥 Всего: {stats['total']}\n"
        f"💎 Премиум: {stats['premium']}\n"
        f"🔥 Активных: {stats['active']}\n\n"
        f"🏙️ <b>Топ городов:</b>\n{cities_text}"
    )
    user = await users.get(message.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me))

@menu_router.message(F.text == "💎 Получить Премиум")
async def get_premium(message: Message):
    await message.answer(
        f"💎 <b>Премиум подписка LoveSpark</b>\n\n"
        f"✅ Безлимит лайков и сообщений\n"
        f"✅ Поиск по всей России\n"
        f"✅ Супер-лайки и приоритет\n"
        f"✅ Просмотр кто тебя лайкнул\n\n"
        f"Выбери тариф:",
        reply_markup=kb.premium(),
        parse_mode=ParseMode.HTML
    )

@menu_router.message(F.text == "👑 Мой Премиум")
async def my_premium(message: Message):
    user = await users.get(message.from_user.id)
    if not await users.is_premium(user):
        return await message.answer("У тебя нет Премиума.", reply_markup=kb.main_menu(False))

    until = user.get("premium_until")
    if not until:
        return await message.answer("Ошибка данных. Обратись в поддержку.")

    try:
        until_dt = datetime.datetime.fromisoformat(until)
        days = (until_dt - datetime.datetime.now()).days
        await message.answer(
            f"👑 <b>Твой Премиум</b>\n\n"
            f"📅 До: {until_dt.strftime('%d.%m.%Y')}\n"
            f"⏳ Осталось: {days} дней",
            parse_mode=ParseMode.HTML
        )
    except:
        await message.answer("Ошибка данных. Обратись в поддержку.")

@menu_router.message(F.text.startswith("🔥 Меня лайкнули"))
async def who_liked_me(message: Message):
    user = await users.get(message.from_user.id)
    count = await users.get_likes_to_me_count(message.from_user.id)

    if count == 0:
        return await message.answer(
            "😕 Пока никто тебя не лайкнул.\n"
            "Активнее ставь лайки другим!",
            reply_markup=kb.main_menu(await users.is_premium(user))
        )

    if await users.is_premium(user):
        likers = await db.fetchall("""
            SELECT u.* FROM likes l 
            JOIN users u ON l.from_user = u.telegram_id 
            WHERE l.to_user = ? AND l.is_mutual = 0
            ORDER BY l.created_at DESC LIMIT 10
        """, (message.from_user.id,))

        await message.answer(f"🔥 <b>Тебя лайкнули ({count}):</b>", parse_mode=ParseMode.HTML)
        for liker in likers:
            await message.answer_photo(
                photo=liker['photo'],
                caption=fmt.format(liker),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❤️ Лайк в ответ", callback_data=f"like_{liker['telegram_id']}")],
                    [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{liker['telegram_id']}")],
                ]),
                parse_mode=ParseMode.HTML
            )
    else:
        await message.answer(
            f"🔥 <b>Тебя лайкнули {count} человек!</b>\n\n"
            f"💡 Хочешь узнать кто? Купи Премиум!",
            reply_markup=kb.main_menu(False),
            parse_mode=ParseMode.HTML
        )

@menu_router.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message):
    user = await users.get(message.from_user.id)
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    if user.get("last_bonus_date") == today:
        return await message.answer(
            "🎁 Ты уже получил бонус сегодня! Приходи завтра!",
            reply_markup=kb.main_menu(await users.is_premium(user))
        )

    await users.update(
        message.from_user.id,
        last_bonus_date=today,
        bonus_likes=user.get("bonus_likes", 0) + CONFIG.DAILY_BONUS_LIKES,
        bonus_messages=user.get("bonus_messages", 0) + CONFIG.DAILY_BONUS_MSGS
    )
    await message.answer(
        f"🎁 <b>Бонус получен!</b>\n\n"
        f"❤️ +{CONFIG.DAILY_BONUS_LIKES} лайка\n"
        f"💬 +{CONFIG.DAILY_BONUS_MSGS} сообщения\n\n"
        f"Заходи каждый день!",
        reply_markup=kb.main_menu(await users.is_premium(user)),
        parse_mode=ParseMode.HTML
    )

@menu_router.message(F.text == "⬆️ Поднять анкету")
async def boost_profile(message: Message):
    user = await users.get(message.from_user.id)
    if not await users.is_premium(user):
        return await message.answer(
            "⬆️ Только для Премиум.",
            reply_markup=kb.main_menu(False)
        )

    await users.update(message.from_user.id, boost_priority=time.time())
    await message.answer(
        "🔥 <b>Анкета поднята!</b>\n\n"
        "Теперь тебя будут видеть чаще в поиске.",
        reply_markup=kb.main_menu(True),
        parse_mode=ParseMode.HTML
    )

@menu_router.message(F.text == "❓ Помощь")
async def help_cmd(message: Message):
    user = await users.get(message.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(message.from_user.id) if user else 0
    text = (
        f"❓ <b>Помощь</b>\n\n"
        f"1. Нажимай «❤️ Найти пару»\n"
        f"2. Ставь лайки\n"
        f"3. При взаимном лайке — общайся!\n\n"
        f"<b>Команды:</b>\n"
        f"/start — Перезапуск\n"
        f"/delete — Удалить профиль\n\n"
        f"Лимиты: {CONFIG.FREE_LIKES} лайков, {CONFIG.FREE_MESSAGES} сообщений.\n"
        f"🎁 Бонус: +{CONFIG.DAILY_BONUS_LIKES} лайка, +{CONFIG.DAILY_BONUS_MSGS} сообщения!"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me))

# ==================== ACTIONS CALLBACKS ====================
action_router = Router()

@action_router.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await users.get(callback.from_user.id)

    if not user:
        return await callback.answer("Сначала создай анкету!", show_alert=True)

    remaining = await users.get_remaining(user, "likes", CONFIG.FREE_LIKES)
    if remaining == 0:
        return await callback.answer("Лимит исчерпан! Купи Премиум.", show_alert=True)

    await users.update(user['telegram_id'], likes_today=user.get("likes_today", 0) + 1)
    is_mutual, match_id = await matches.add_like(user['telegram_id'], target_id)
    await stats_collector.increment("likes_count")

    if is_mutual:
        await stats_collector.increment("matches_count")
        partner = await users.get(target_id)
        if partner:
            await callback.message.answer(
                f"💕 <b>Взаимный мэтч!</b>\n"
                f"Вы и {html.escape(partner['name'])} понравились друг другу! 💬",
                reply_markup=kb.match_actions(match_id, target_id),
                parse_mode=ParseMode.HTML
            )
            await notifier.notify(
                target_id,
                f"💕 <b>Новый мэтч!</b>\n"
                f"{html.escape(user['name'])} лайкнул(а) тебя взаимно! 💬",
                reply_markup=kb.match_actions(match_id, user['telegram_id']),
                parse_mode=ParseMode.HTML
            )
    else:
        await notifier.notify(
            target_id,
            f"💘 <b>Кто-то тебя лайкнул!</b>\n\n"
            f"Открой LoveSpark, чтобы узнать кто... 😉",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Открыть LoveSpark", url="https://t.me/LoveSparkBot")]
            ]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer("❤️ Лайк отправлен!")

    await callback.message.delete()
    await find_pair(callback.message)

@action_router.callback_query(F.data.startswith("superlike_"))
async def process_superlike(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await users.get(callback.from_user.id)
    if not await users.is_premium(user):
        return await callback.answer("Супер-лайки только для Премиум!", show_alert=True)

    is_mutual, match_id = await matches.add_like(user['telegram_id'], target_id)
    if is_mutual:
        partner = await users.get(target_id)
        await callback.message.answer(
            f"⭐ <b>Супер-мэтч!</b>\n"
            f"Вы и {html.escape(partner['name'])} — мэтч!",
            reply_markup=kb.match_actions(match_id, target_id),
            parse_mode=ParseMode.HTML
        )
        await notifier.notify(
            target_id,
            f"⭐ <b>Супер-мэтч!</b>\n"
            f"Кто-то использовал супер-лайк на тебе!",
            reply_markup=kb.match_actions(match_id, user['telegram_id']),
            parse_mode=ParseMode.HTML
        )
    else:
        await notifier.notify(
            target_id,
            f"⭐ <b>Супер-лайк!</b>\n\n"
            f"Кто-то особенно сильно тебя лайкнул! 💘",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Открыть LoveSpark", url="https://t.me/LoveSparkBot")]
            ]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer("⭐ Супер-лайк отправлен!")

    await callback.message.delete()
    await find_pair(callback.message)

@action_router.callback_query(F.data.startswith("skip_") | F.data.startswith("block_"))
async def skip_or_block(callback: CallbackQuery):
    action = "Пропущено" if "skip" in callback.data else "Заблокировано"
    await callback.answer(action)
    await callback.message.delete()
    await find_pair(callback.message)

@action_router.callback_query(F.data.startswith("report_"))
async def report_profile(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target=target_id)
    await state.set_state(ReportState.reason)
    await callback.message.answer("🛡️ Опиши причину жалобы:")
    await callback.answer()

@action_router.message(ReportState.reason)
async def process_report(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("report_target")
    if not target_id:
        return await state.clear()

    await db.execute(
        "INSERT INTO reports (from_user, to_user, reason) VALUES (?, ?, ?)",
        (message.from_user.id, target_id, message.text[:500])
    )

    user = await users.get(message.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer(
        "🛡️ Жалоба отправлена администрации. Спасибо!",
        reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me)
    )
    await state.clear()

    for admin_id in CONFIG.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚨 <b>Жалоба!</b>\n\n"
                f"От: {message.from_user.id}\n"
                f"На: {target_id}\n"
                f"Причина: {html.escape(message.text[:500])}",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# ==================== CHAT HANDLERS ====================
chat_router = Router()

async def open_chat(target, state: FSMContext, match_id: int, partner_id: int):
    partner = await users.get(int(partner_id))
    if not partner:
        return await target.answer("Пользователь не найден.")

    await state.set_state(ChatState.chatting)
    await state.update_data(match_id=int(match_id), partner_id=int(partner_id))

    text = (
        f"💬 <b>Чат с {html.escape(partner['name'])}</b>\n"
        f"Отправляй текст, фото, видео, голосовые или стикеры.\n"
        f"Выход: /exit"
    )
    if isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=kb.chat_actions(match_id), parse_mode=ParseMode.HTML)
    else:
        await target.answer(text, reply_markup=kb.chat_actions(match_id), parse_mode=ParseMode.HTML)

@chat_router.callback_query(F.data.startswith("chat_"))
async def start_chat(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return await callback.answer("Ошибка.")
    await open_chat(callback, state, parts[1], parts[2])
    await callback.answer()

@chat_router.callback_query(F.data.startswith("message_"))
async def message_from_profile(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    match = await matches.get_match(callback.from_user.id, target_id)
    if not match:
        return await callback.answer("Сначала нужен мэтч!", show_alert=True)
    await open_chat(callback, state, match['id'], target_id)
    await callback.answer()

@chat_router.callback_query(F.data.startswith("hint_"))
async def hints(callback: CallbackQuery):
    await callback.answer("Просто отправь это в чат!", show_alert=True)

@chat_router.callback_query(F.data == "back_to_matches")
async def back_to_matches(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await my_matches_cmd(callback.message)

@chat_router.callback_query(F.data.startswith("view_"))
async def view_profile(callback: CallbackQuery):
    p_id = int(callback.data.split("_")[1])
    p = await users.get(p_id)
    if p and p.get("is_active") and not p.get("is_banned"):
        await callback.message.answer_photo(photo=p['photo'], caption=fmt.format(p), parse_mode=ParseMode.HTML)
    else:
        await callback.answer("Анкета недоступна.")
    await callback.answer()

@chat_router.message(ChatState.chatting)
async def chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data.get("partner_id")
    if not partner_id:
        return await state.clear()

    user = await users.get(message.from_user.id)
    if not user:
        return await state.clear()

    remaining = await users.get_remaining(user, "messages", CONFIG.FREE_MESSAGES)
    if remaining == 0:
        return await message.answer(
            "😔 Лимит сообщений исчерпан! Купи Премиум или возьми бонус.",
            reply_markup=kb.main_menu(False)
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

    await db.execute(
        "INSERT INTO messages (match_id, from_user, content_type, content, file_id) VALUES (?, ?, ?, ?, ?)",
        (data["match_id"], message.from_user.id, content_type, content, file_id)
    )

    if not await users.is_premium(user):
        await users.update(user['telegram_id'], messages_today=user.get("messages_today", 0) + 1)

    name_safe = html.escape(user['name'])
    content_safe = html.escape(content)

    try:
        if content_type == "text":
            await bot.send_message(partner_id, f"💬 <b>{name_safe}:</b>\n{content_safe}", parse_mode=ParseMode.HTML)
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
            await bot.send_document(partner_id, file_id, caption=f"📎 <b>{name_safe}</b>\n{content_safe}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Chat forward error: {e}")
        await message.answer("🚫 Пользователь ограничил доступ.")

@chat_router.message(Command("exit"), ChatState.chatting)
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await users.get(message.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(message.from_user.id) if user else 0
    await message.answer("🔙 Вы вышли из чата.", reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me))

# ==================== PAYMENT HANDLERS ====================
payment_router = Router()

@payment_router.callback_query(F.data.startswith("premium_"))
async def select_premium(callback: CallbackQuery):
    tariff_key = callback.data.split("_")[1]
    if tariff_key not in CONFIG.PREMIUM_TARIFFS:
        return await callback.answer("Ошибка тарифа.")
    tariff = CONFIG.PREMIUM_TARIFFS[tariff_key]
    label = f"LS_{callback.from_user.id}_{tariff_key}_{uuid.uuid4().hex[:8]}"

    await payments.create(callback.from_user.id, tariff_key, tariff['price'], label)
    url = await payments.create_url(tariff['price'], label, f"LoveSpark Premium {tariff['name']}")

    await callback.message.edit_text(
        f"💎 <b>{tariff['name']}</b>\n"
        f"💰 К оплате: {tariff['price']}₽\n"
        f"📝 {tariff['desc']}",
        reply_markup=kb.payment(url, label),
        parse_mode=ParseMode.HTML
    )

@payment_router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    label = callback.data.replace("check_payment_", "")
    if await payments.check_yoomoney(label):
        payment = await payments.get(label)
        if payment and payment['status'] != 'paid':
            await payments.update_status(label, "paid")
            days = CONFIG.PREMIUM_TARIFFS[payment['tariff']]['days']
            until = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
            await users.update(payment['user_id'], is_premium=1, premium_until=until)
            await callback.message.answer(
                f"🎉 <b>Оплата успешна! Премиум активирован!</b>\n\n"
                f"Дней: {days}\n"
                f"До: {datetime.datetime.fromisoformat(until).strftime('%d.%m.%Y')}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb.main_menu(True)
            )
            await stats_collector.increment("payments_count")
            await stats_collector.increment("revenue")
    else:
        await callback.answer("⏳ Платеж не найден. Подождите 1-2 минуты.", show_alert=True)

@payment_router.callback_query(F.data == "back_premium")
async def back_premium(callback: CallbackQuery):
    await callback.message.delete()
    await get_premium(callback.message)

# ==================== EDIT PROFILE ====================
edit_router = Router()

@edit_router.callback_query(F.data.startswith("edit_"))
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    prompts = {
        "photo": "📸 Отправь новое фото:",
        "name": "📝 Введи новое имя:",
        "age": "🔢 Введи возраст:",
        "city": "🏙️ Напиши город:",
        "bio": "📝 О себе:",
        "looking": "👀 Кого ищешь?",
        "goal": "🎯 Выбери цель:",
        "interests": "🎨 Выбери интересы:"
    }
    if field not in prompts:
        return await callback.answer("Ошибка.")

    await state.update_data(edit_field=field)
    await state.set_state(EditProfile.new_value)

    if field == "city":
        await callback.message.answer(prompts[field], reply_markup=kb.city_list())
    elif field == "looking":
        await callback.message.answer(prompts[field], reply_markup=kb.looking_for())
    elif field == "goal":
        await callback.message.answer(prompts[field], reply_markup=kb.reg_goal())
    elif field == "interests":
        await state.update_data(edit_interests=set())
        await callback.message.answer(prompts[field], reply_markup=kb.reg_interests())
    else:
        await callback.message.answer(prompts[field])
    await callback.answer()

@edit_router.message(EditProfile.new_value)
async def save_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    if not field:
        return await state.clear()

    user = await users.get(message.from_user.id)
    if not user:
        return await state.clear()

    if field == "photo":
        if not message.photo:
            return await message.answer("Нужно фото:")
        await users.update(user['telegram_id'], photo=message.photo[-1].file_id)
    elif field == "name":
        name = message.text.strip()
        if not (2 <= len(name) <= 30):
            return await message.answer("Имя от 2 до 30 символов:")
        await users.update(user['telegram_id'], name=name)
    elif field == "age":
        if not message.text.strip().isdigit():
            return await message.answer("Нужно число:")
        age = int(message.text.strip())
        if not (16 <= age <= 100):
            return await message.answer("Возраст 16-100:")
        await users.update(user['telegram_id'], age=age)
    elif field == "city":
        city = message.text.strip()
        if len(city) < 2:
            return await message.answer("Слишком коротко:")
        await users.update(user['telegram_id'], city=city[:50])
    elif field == "bio":
        await users.update(user['telegram_id'], bio=message.text[:500])
    elif field == "looking":
        looks = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
        if message.text not in looks:
            return await message.answer("Используй кнопки:", reply_markup=kb.looking_for())
        await users.update(user['telegram_id'], looking_for=looks[message.text])
    elif field == "goal":
        for key, val in CONFIG.GOALS.items():
            if val == message.text:
                await users.update(user['telegram_id'], goal=key)
                break
        else:
            return await message.answer("Используй кнопки:", reply_markup=kb.reg_goal())
    elif field == "interests":
        return await message.answer("Используй кнопки:", reply_markup=kb.reg_interests())

    likes_to_me = await users.get_likes_to_me_count(message.from_user.id)
    await message.answer("✅ Сохранено!", reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me))
    await state.clear()

@edit_router.callback_query(F.data.startswith("reg_int_"), EditProfile.new_value)
async def edit_interests_cb(callback: CallbackQuery, state: FSMContext):
    data = callback.data.replace("reg_int_", "")
    if data == "done":
        current = await state.get_data()
        selected = current.get("edit_interests", set())
        if not selected:
            return await callback.answer("Выбери хотя бы один!", show_alert=True)
        await users.update(callback.from_user.id, interests=",".join(selected))
        likes_to_me = await users.get_likes_to_me_count(callback.from_user.id)
        await callback.message.edit_text("✅ Интересы обновлены!")
        await callback.message.answer("Главное меню", reply_markup=kb.main_menu(await users.is_premium(await users.get(callback.from_user.id)), likes_to_me))
        await state.clear()
        return

    current = await state.get_data()
    selected = set(current.get("edit_interests", []))
    if data in selected:
        selected.remove(data)
    else:
        selected.add(data)
    await state.update_data(edit_interests=selected)
    await callback.message.edit_reply_markup(reply_markup=kb.reg_interests(selected))
    await callback.answer()

@edit_router.callback_query(F.data == "back_menu")
async def back_menu(callback: CallbackQuery):
    user = await users.get(callback.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("Главное меню", reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me))

# ==================== ADMIN HANDLERS ====================
admin_router = Router()

@admin_router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id in CONFIG.ADMIN_IDS:
        await message.answer("🔧 <b>Админ-панель</b>", reply_markup=kb.admin(), parse_mode=ParseMode.HTML)

@admin_router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id in CONFIG.ADMIN_IDS:
        await show_stats(callback.message)

@admin_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id in CONFIG.ADMIN_IDS:
        await callback.message.answer("Введите текст рассылки:")
        await state.set_state(AdminState.broadcast)

@admin_router.message(AdminState.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in CONFIG.ADMIN_IDS:
        return await state.clear()

    rows = await db.fetchall("SELECT telegram_id FROM users WHERE is_active = 1")
    user_ids = [r['telegram_id'] for r in rows]

    await message.answer(f"⏳ Рассылка для {len(user_ids)} пользователей...")

    semaphore = asyncio.Semaphore(CONFIG.BROADCAST_BATCH_SIZE)
    success = 0

    async def send_one(uid: int):
        nonlocal success
        async with semaphore:
            try:
                await bot.send_message(
                    uid,
                    f"📢 <b>Сообщение от администрации:</b>\n\n{message.text}",
                    parse_mode=ParseMode.HTML
                )
                success += 1
                await asyncio.sleep(CONFIG.BROADCAST_DELAY)
            except:
                pass

    await asyncio.gather(*[send_one(uid) for uid in user_ids])
    await message.answer(f"✅ Доставлено: {success}/{len(user_ids)}")
    await state.clear()

@admin_router.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in CONFIG.ADMIN_IDS:
        return await callback.answer("Нет доступа.")
    await callback.message.answer("Введи ID для бана:")
    await state.set_state(AdminState.ban)

@admin_router.message(AdminState.ban)
async def admin_ban_exec(message: Message, state: FSMContext):
    if message.from_user.id not in CONFIG.ADMIN_IDS:
        return await state.clear()
    try:
        uid = int(message.text.strip())
        await users.update(uid, is_banned=1, is_active=0)
        await message.answer(f"🚫 {uid} забанен.")
        await notifier.notify(uid, "🚫 Аккаунт заблокирован администрацией.")
    except:
        await message.answer("Ошибка. Введи числовой ID.")
    await state.clear()

@admin_router.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in CONFIG.ADMIN_IDS:
        return await callback.answer("Нет доступа.")
    await callback.message.answer("Введи ID для разбана:")
    await state.set_state(AdminState.unban)

@admin_router.message(AdminState.unban)
async def admin_unban_exec(message: Message, state: FSMContext):
    if message.from_user.id not in CONFIG.ADMIN_IDS:
        return await state.clear()
    try:
        uid = int(message.text.strip())
        await users.update(uid, is_banned=0, is_active=1)
        await message.answer(f"✅ {uid} разбанен.")
        await notifier.notify(uid, "✅ Аккаунт разблокирован! С возвращением!")
    except:
        await message.answer("Ошибка. Введи числовой ID.")
    await state.clear()

# ==================== DELETE PROFILE ====================
@dp.message(Command("delete"))
async def delete_cmd(message: Message):
    await message.answer(
        "⚠️ Точно удалить анкету? Все данные будут удалены.",
        reply_markup=kb.confirm_delete()
    )

@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery):
    await users.update(callback.from_user.id, is_active=0)
    await callback.message.answer(
        "😢 Анкета удалена. Жаль терять такого классного пользователя!\n\n"
        "Если передумаешь — /start",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    user = await users.get(callback.from_user.id)
    likes_to_me = await users.get_likes_to_me_count(callback.from_user.id)
    await callback.message.answer(
        "Отлично! Продолжай знакомиться ❤️",
        reply_markup=kb.main_menu(await users.is_premium(user), likes_to_me)
    )

# ==================== BACKGROUND TASKS ====================
async def reset_limits_task():
    while True:
        now = datetime.datetime.now()
        next_reset = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = (next_reset - now).total_seconds()
        logger.info(f"Daily reset in {sleep_seconds/3600:.1f}h")
        await asyncio.sleep(sleep_seconds)
        await db.execute("UPDATE users SET likes_today = 0, messages_today = 0, bonus_likes = 0, bonus_messages = 0")
        logger.info("Daily limits reset")

async def cleanup_task():
    """Remove old inactive users and messages periodically."""
    while True:
        await asyncio.sleep(86400)  # Daily
        try:
            await db.execute("DELETE FROM messages WHERE created_at < datetime('now', '-90 days')")
            await db.execute("DELETE FROM likes WHERE created_at < datetime('now', '-30 days') AND is_mutual = 0")
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ==================== MAIN ====================
async def on_startup():
    global db, users, matches, payments, notifier, stats_collector

    db = DatabaseManager(CONFIG.DB_NAME)
    await db.connect()

    cache = TTLCache(CONFIG.CACHE_TTL_SECONDS)
    users = UserService(db, cache)
    matches = MatchService(db, users)
    payments = PaymentService(db)

    notifier = NotificationService(bot, CONFIG.NOTIFICATION_WORKERS)
    notifier.start()

    stats_collector = BatchStatCollector(db)
    stats_collector.start()

    # Register routers
    dp.include_router(reg_router)
    dp.include_router(menu_router)
    dp.include_router(action_router)
    dp.include_router(chat_router)
    dp.include_router(payment_router)
    dp.include_router(edit_router)
    dp.include_router(admin_router)

    # Register middlewares
    dp.message.middleware(ThrottlingMiddleware(CONFIG.RATE_LIMIT_SECONDS))
    dp.message.middleware(BanMiddleware(users))
    dp.message.middleware(ActivityMiddleware(users))
    dp.callback_query.middleware(BanMiddleware(users))

    logger.info("LoveSpark Enterprise started successfully")

async def on_shutdown():
    logger.info("Shutting down...")
    if stats_collector:
        await stats_collector.stop()
    if notifier:
        await notifier.stop()
    if db:
        await db.close()
    await bot.session.close()
    logger.info("Shutdown complete")

async def main():
    await on_startup()

    # Register background tasks
    asyncio.create_task(reset_limits_task())
    asyncio.create_task(cleanup_task())

    # Signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))

    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
