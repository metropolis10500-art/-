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
    "Махачкала", "Томск", "Оренбург", "Кемерово", "Новокузнецк",
    "Рязань", "Астрахань", "Набережные Челны", "Пенза", "Липецк",
    "Донецк", "Луганск", "Макеевка", "Горловка", "Мариуполь", "Алчевск",
    "Сочи", "Сургут", "Симферополь", "Севастополь"
]

BOT_NAME = "LoveSpark"
BOT_DESCRIPTION = "Бот знакомств для всех городов России"

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
    name, age, city, gender, looking_for, photo, bio, confirm = State(), State(), State(), State(), State(), State(), State(), State()

class EditProfile(StatesGroup):
    choosing_field, new_value = State(), State()

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
                id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT, name TEXT NOT NULL, age INTEGER NOT NULL, city TEXT NOT NULL,
                gender TEXT NOT NULL, looking_for TEXT NOT NULL, photo TEXT, bio TEXT,
                is_premium INTEGER DEFAULT 0, premium_until TEXT, likes_today INTEGER DEFAULT 0,
                messages_today INTEGER DEFAULT 0, last_activity TEXT, is_active INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE, referred_by INTEGER, profile_views INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL, is_mutual INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(from_user, to_user)
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user1 INTEGER NOT NULL,
                user2 INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user1, user2)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL, content_type TEXT NOT NULL,
                content TEXT NOT NULL, file_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL, amount INTEGER NOT NULL, label TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT "pending", created_at TEXT DEFAULT CURRENT_TIMESTAMP, paid_at TEXT
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(referred_id)
            );
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT UNIQUE DEFAULT CURRENT_DATE,
                new_users INTEGER DEFAULT 0, active_users INTEGER DEFAULT 0, likes_count INTEGER DEFAULT 0,
                matches_count INTEGER DEFAULT 0, payments_count INTEGER DEFAULT 0, revenue INTEGER DEFAULT 0
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
            INSERT INTO users (telegram_id, username, name, age, city, gender, looking_for, photo, bio, referral_code, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_id, username, name, age, city, gender, looking_for, photo, bio, referral_code, datetime.datetime.now().isoformat()))
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
            SELECT * FROM users WHERE telegram_id != ? AND is_active = 1 AND is_banned = 0
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

async def add_message(match_id: int, from_user: int, content_type: str, content: str, file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO messages (match_id, from_user, content_type, content, file_id) VALUES (?, ?, ?, ?, ?)",
            (match_id, from_user, content_type, content, file_id))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) as total_users, SUM(CASE WHEN is_premium = 1 THEN 1 ELSE 0 END) as premium_users, SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_users FROM users") as cursor:
            return dict(await cursor.fetchone())

async def reset_daily_limits():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET likes_today = 0, messages_today = 0")
        await db.commit()

async def increment_stat(field: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"INSERT INTO stats (date, {field}) VALUES (CURRENT_DATE, 1) ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1")
        await db.commit()

# ==================== YOOMONEY ====================
async def create_payment_ym(amount: int, label: str, description: str = "LoveSpark Premium"):
    return f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YOOMONEY_WALLET}&quickpay-form=shop&targets={description}&paymentType=AC&sum={amount}&label={label}&successURL=https://t.me/LoveSparkBot"

async def check_payment_ym(label: str):
    headers = {"Authorization": f"Bearer {YOOMONEY_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"type": "deposition", "label": label, "details": "true"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{YOOMONEY_API_URL}/operation-history", headers=headers, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    for op in result.get("operations", []):
                        if op.get("label") == label and op.get("status") == "success":
                            return True
    except Exception as e:
        logger.error(f"YooMoney API Check Failed: {e}")
    return False

def generate_payment_label(user_id: int, tariff: str) -> str:
    return f"LS_{user_id}_{tariff}_{uuid.uuid4().hex[:8]}"

# ==================== KEYBOARDS ====================
def main_menu_kb(is_premium: bool = False):
    kb = [
        [KeyboardButton(text="💘 Найти пару")],
        [KeyboardButton(text="📋 Моя анкета"), KeyboardButton(text="✏️ Редактировать")],
        [KeyboardButton(text="💕 Мои мэтчи"), KeyboardButton(text="📊 Статистика")],
    ]
    kb.append([KeyboardButton(text="👑 Мой Премиум")] if is_premium else [KeyboardButton(text="💎 Получить Премиум")])
    kb.append([KeyboardButton(text="❓ Помощь")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def gender_kb(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]], resize_keyboard=True)
def looking_for_kb(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👨 Мужчин"), KeyboardButton(text="👩 Женщин")], [KeyboardButton(text="👫 Всех")]], resize_keyboard=True)

def city_kb():
    kb = [[KeyboardButton(text=city) for city in CITIES[i:i+3]] for i in range(0, len(CITIES[:30]), 3)]
    kb.append([KeyboardButton(text="📝 Ввести свой город")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def profile_actions_kb(profile_id: int, is_premium: bool = False):
    buttons = [
        [InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{profile_id}")],
        [InlineKeyboardButton(text="💬 Написать", callback_data=f"message_{profile_id}")],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip_{profile_id}")],
    ]
    if is_premium: buttons.insert(2, [InlineKeyboardButton(text="⭐ Супер-лайк", callback_data=f"superlike_{profile_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def match_actions_kb(match_id: int, partner_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Начать чат", callback_data=f"chat_{match_id}_{partner_id}")],
        [InlineKeyboardButton(text="👤 Смотреть анкету", callback_data=f"view_{partner_id}")]
    ])

def chat_actions_kb(match_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Фото", callback_data="hint_photo"), InlineKeyboardButton(text="🎙️ Голосовое", callback_data="hint_voice")],
        [InlineKeyboardButton(text="🔙 К мэтчам", callback_data="back_to_matches")]
    ])

def premium_kb():
    buttons = [[InlineKeyboardButton(text=f"{v['name']} - {v['price']}₽", callback_data=f"premium_{k}")] for k, v in PREMIUM_TARIFFS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def payment_kb(payment_url: str, label: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_payment_{label}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_premium")]
    ])

# ==================== UTILITIES ====================
def get_premium_status(user):
    if not user or not user.get("is_premium"): return False
    if user.get("premium_until"):
        return datetime.datetime.fromisoformat(user["premium_until"]) > datetime.datetime.now()
    return False

def format_profile(user, show_contact=False):
    gender_emoji = "👨" if user.get("gender") == "male" else "👩"
    prem_badge = "💎" if get_premium_status(user) else ""
    return f"{gender_emoji} <b>{user.get('name', 'Неизвестно')}</b>, {user.get('age', '?')} {prem_badge}\n🏙️ {user.get('city', 'Не указан')}\n\n📝 {user.get('bio', 'Нет описания')}"

# ==================== HANDLERS (REGISTRATION) ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user and user.get("is_active"):
        return await message.answer(f"💘 <b>С возвращением в LoveSpark!</b>\n\nПродолжай поиск второй половинки!", reply_markup=main_menu_kb(get_premium_status(user)), parse_mode=ParseMode.HTML)
    
    await message.answer(f"💘 <b>Добро пожаловать в LoveSpark!</b> 💘\n\nИдеальный бот знакомств по всей России.\n\nКак тебя зовут?")
    await state.set_state(Registration.name)

@dp.message(Registration.name)
async def process_name(message: Message, state: FSMContext):
    if not (2 <= len(message.text) <= 30): return await message.answer("Имя должно быть от 2 до 30 символов:")
    await state.update_data(name=message.text.strip())
    await message.answer("Сколько тебе лет?")
    await state.set_state(Registration.age)

@dp.message(Registration.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not (16 <= age <= 100): raise ValueError
    except ValueError: return await message.answer("Введи корректный возраст (от 16 до 100):")
    await state.update_data(age=age)
    await message.answer("Выбери свой город:", reply_markup=city_kb())
    await state.set_state(Registration.city)

@dp.message(Registration.city)
async def process_city(message: Message, state: FSMContext):
    if message.text == "📝 Ввести свой город":
        await message.answer("Напиши свой город вручную:")
        return await state.set_state(CityInput.waiting_city)
    await state.update_data(city=message.text.strip())
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(CityInput.waiting_city)
async def process_custom_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await message.answer("Твой пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(Registration.gender)
async def process_gender(message: Message, state: FSMContext):
    genders = {"👨 Мужчина": "male", "👩 Женщина": "female"}
    if message.text not in genders: return await message.answer("Выбери из кнопок:", reply_markup=gender_kb())
    await state.update_data(gender=genders[message.text])
    await message.answer("Кого ты ищешь?", reply_markup=looking_for_kb())
    await state.set_state(Registration.looking_for)

@dp.message(Registration.looking_for)
async def process_looking_for(message: Message, state: FSMContext):
    looks = {"👨 Мужчин": "male", "👩 Женщин": "female", "👫 Всех": "both"}
    if message.text not in looks: return await message.answer("Выбери из кнопок:", reply_markup=looking_for_kb())
    await state.update_data(looking_for=looks[message.text])
    await message.answer("Отправь свое лучшее фото! 📸")
    await state.set_state(Registration.photo)

@dp.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Расскажи о себе (хобби, интересы):")
    await state.set_state(Registration.bio)

@dp.message(Registration.bio)
async def process_bio(message: Message, state: FSMContext):
    if len(message.text) < 10: return await message.answer("Напиши чуть подробнее (минимум 10 символов):")
    await state.update_data(bio=message.text[:500])
    data = await state.get_data()
    await message.answer_photo(photo=data['photo'], caption=f"📋 <b>Твоя анкета:</b>\n\n{format_profile(data)}\n\nВсё верно? Нажми /confirm", parse_mode=ParseMode.HTML)
    await state.set_state(Registration.confirm)

@dp.message(Command("confirm"), Registration.confirm)
async def confirm_reg(message: Message, state: FSMContext):
    data = await state.get_data()
    code = f"LS{uuid.uuid4().hex[:6].upper()}"
    await create_user(message.from_user.id, message.from_user.username, data['name'], data['age'], data['city'], data['gender'], data['looking_for'], data['photo'], data['bio'], code)
    await message.answer("🎉 <b>Анкета успешно создана!</b>", reply_markup=main_menu_kb(False), parse_mode=ParseMode.HTML)
    await state.clear()

# ==================== MAIN MENU HANDLERS ====================

@dp.message(F.text == "💘 Найти пару")
async def find_pair(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return await message.answer("Создай анкету через /start")
    if not get_premium_status(user) and user.get("likes_today", 0) >= FREE_LIKES_PER_DAY:
        return await message.answer("😔 Лимит лайков исчерпан! Получи 💎 Премиум для безлимита.", reply_markup=main_menu_kb(False))

    profile = await get_random_profile(user['telegram_id'], user['looking_for'], user['city'])
    if not profile: return await message.answer("Пока нет новых анкет. Загляни позже!")
    await message.answer_photo(photo=profile['photo'], caption=format_profile(profile), reply_markup=profile_actions_kb(profile['telegram_id'], get_premium_status(user)), parse_mode=ParseMode.HTML)

@dp.message(F.text == "📋 Моя анкета")
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return
    status = "💎 Премиум" if get_premium_status(user) else "⭐ Бесплатный"
    await message.answer_photo(photo=user['photo'], caption=f"{format_profile(user)}\n\n📊 Статус: {status}", parse_mode=ParseMode.HTML)

@dp.message(F.text == "💕 Мои мэтчи")
async def my_matches(message: Message):
    matches = await get_matches(message.from_user.id)
    if not matches: return await message.answer("💔 Пока нет мэтчей. Ставь лайки и они появятся!")
    await message.answer(f"💕 <b>Твои мэтчи ({len(matches)}):</b>", parse_mode=ParseMode.HTML)
    for m in matches[:10]: # Ограничиваем вывод 10 последними чтобы не спамить
        p_id = m['user2'] if m['user1'] == message.from_user.id else m['user1']
        await message.answer_photo(photo=m['photo'], caption=f"💕 <b>{m['name']}</b>, {m['age']}\n🏙️ {m['city']}", reply_markup=match_actions_kb(m['id'], p_id), parse_mode=ParseMode.HTML)

@dp.message(F.text.in_(["💎 Получить Премиум", "👑 Мой Премиум"]))
async def premium_menu(message: Message):
    user = await get_user(message.from_user.id)
    if get_premium_status(user):
        until = datetime.datetime.fromisoformat(user['premium_until']).strftime('%d.%m.%Y')
        return await message.answer(f"👑 <b>Твой Премиум активен!</b>\n📅 До: {until}", parse_mode=ParseMode.HTML)
    await message.answer("💎 <b>Премиум LoveSpark</b>\n\n✅ Безлимит лайков и чатов\n✅ Поиск по всей РФ\n✅ Супер-лайки\n\nВыбери тариф:", reply_markup=premium_kb(), parse_mode=ParseMode.HTML)

# ==================== ACTIONS / CALLBACKS ====================

@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = await get_user(callback.from_user.id)
    
    if not get_premium_status(user) and user.get("likes_today", 0) >= FREE_LIKES_PER_DAY:
        return await callback.answer("Лимит лайков исчерпан!", show_alert=True)

    await update_user(user['telegram_id'], likes_today=user.get("likes_today", 0) + 1)
    is_mutual = await add_like(user['telegram_id'], target_id)
    
    if is_mutual:
        partner = await get_user(target_id)
        await callback.message.answer(f"💕 <b>Взаимный мэтч!</b>\nВы и {partner['name']} понравились друг другу!", reply_markup=match_actions_kb(0, target_id), parse_mode=ParseMode.HTML)
        try: await bot.send_message(target_id, f"💕 <b>Новый мэтч!</b>\n{user['name']} лайкнул(а) тебя взаимно!", reply_markup=match_actions_kb(0, user['telegram_id']), parse_mode=ParseMode.HTML)
        except Exception: pass
    else:
        await callback.answer("❤️ Лайк отправлен!")
    
    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("skip_") | F.data.startswith("block_"))
async def skip_profile(callback: CallbackQuery):
    await callback.answer("Анкета пропущена")
    await callback.message.delete()
    await find_pair(callback.message)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat_cb(callback: CallbackQuery, state: FSMContext):
    _, match_id, p_id = callback.data.split("_")
    partner = await get_user(int(p_id))
    await state.set_state(ChatState.chatting)
    await state.update_data(partner_id=int(p_id))
    await callback.message.answer(f"💬 <b>Чат с {partner['name']}</b>\nПросто отправь текст, фото или стикер сюда.\nДля выхода нажми /exit", reply_markup=chat_actions_kb(match_id), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("message_"))
async def write_message_from_profile(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    match = await get_match(callback.from_user.id, target_id)
    if not match: return await callback.answer("Сначала нужен взаимный мэтч!", show_alert=True)
    callback.data = f"chat_{match['id']}_{target_id}" # Rewrite callback data
    await start_chat_cb(callback, state)

@dp.callback_query(F.data.startswith("hint_"))
async def hints_cb(callback: CallbackQuery):
    await callback.answer("Просто отправь это медиа прямо сюда в чат!", show_alert=True)

@dp.callback_query(F.data == "back_to_matches")
async def back_to_matches(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await my_matches(callback.message)

# ==================== CHAT LOGIC ====================

@dp.message(ChatState.chatting)
async def process_chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data.get("partner_id")
    if not partner_id: return await state.clear()
    
    user = await get_user(message.from_user.id)
    if not get_premium_status(user) and user.get("messages_today", 0) >= FREE_MESSAGES_PER_DAY:
        return await message.answer("😔 Лимит сообщений на сегодня исчерпан!")

    if not get_premium_status(user): await update_user(user['telegram_id'], messages_today=user.get("messages_today", 0) + 1)
    
    try:
        if message.text: await bot.send_message(partner_id, f"💬 <b>{user['name']}:</b>\n{message.text}", parse_mode=ParseMode.HTML)
        elif message.photo: await bot.send_photo(partner_id, message.photo[-1].file_id, caption=f"📸 <b>{user['name']}</b>", parse_mode=ParseMode.HTML)
        elif message.voice: await bot.send_voice(partner_id, message.voice.file_id, caption=f"🎙️ <b>{user['name']}</b>", parse_mode=ParseMode.HTML)
        elif message.sticker: await bot.send_sticker(partner_id, message.sticker.file_id)
    except Exception:
        await message.answer("🚫 Пользователь ограничил доступ к боту.")

@dp.message(Command("exit"), ChatState.chatting)
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔙 Вы вышли из чата.", reply_markup=main_menu_kb(True))

# ==================== PREMIUM PAYMENTS ====================

@dp.callback_query(F.data.startswith("premium_"))
async def select_premium(callback: CallbackQuery):
    tariff = PREMIUM_TARIFFS[callback.data.split("_")[1]]
    label = generate_payment_label(callback.from_user.id, callback.data.split("_")[1])
    
    # Симуляция добавления в БД
    import sqlite3
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT INTO payments (user_id, tariff, amount, label) VALUES (?, ?, ?, ?)", (callback.from_user.id, callback.data.split("_")[1], tariff['price'], label))
        
    url = await create_payment_ym(tariff['price'], label, f"LoveSpark Premium {tariff['name']}")
    await callback.message.edit_text(f"💎 <b>{tariff['name']}</b>\n💰 К оплате: {tariff['price']}₽", reply_markup=payment_kb(url, label), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_pay(callback: CallbackQuery):
    label = callback.data.replace("check_payment_", "")
    if await check_payment_ym(label):
        # Активация
        import sqlite3
        with sqlite3.connect(DB_NAME) as db:
            db.row_factory = sqlite3.Row
            payment = db.execute("SELECT * FROM payments WHERE label=?", (label,)).fetchone()
            if payment and payment['status'] != 'paid':
                db.execute("UPDATE payments SET status='paid' WHERE label=?", (label,))
                days = PREMIUM_TARIFFS[payment['tariff']]['days']
                until = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
                db.execute("UPDATE users SET is_premium=1, premium_until=? WHERE telegram_id=?", (until, payment['user_id']))
                await callback.message.answer("🎉 <b>Оплата прошла успешно! Премиум активирован!</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(True))
    else:
        await callback.answer("⏳ Платеж пока не найден. Подождите 1-2 минуты.", show_alert=True)

# ==================== ADMIN PANEL ====================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🔧 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Введите текст для рассылки всем пользователям:")
        await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_active = 1") as cursor:
            users = await cursor.fetchall()
            
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    success = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 <b>Сообщение от администрации:</b>\n\n{message.text}", parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05) # Защита от лимитов Telegram (20 сообщений в секунду)
        except Exception: pass
        
    await message.answer(f"✅ Рассылка завершена! Успешно доставлено: {success}")
    await state.clear()

# ==================== RUNNER ====================
async def main():
    await init_db()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
