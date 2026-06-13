import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputMediaPhoto,
    LabeledPrice, PreCheckoutQuery, SuccessfulPayment, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
ADMIN_ID = 5494544187
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"

# Премиум тарифы
PREMIUM_PRICES = {
    "week": {"price": 199, "days": 7, "label": "1 неделя"},
    "month": {"price": 499, "days": 30, "label": "1 месяц"},
    "quarter": {"price": 1299, "days": 90, "label": "3 месяца"},
    "year": {"price": 3999, "days": 365, "label": "1 год"}
}

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name="lovespark.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                gender TEXT,
                age INTEGER,
                city TEXT,
                bio TEXT,
                photo_id TEXT,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                likes_left INTEGER DEFAULT 10,
                superlikes_left INTEGER DEFAULT 1,
                created_at TEXT,
                is_active INTEGER DEFAULT 1,
                last_active TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER,
                to_user INTEGER,
                is_superlike INTEGER DEFAULT 0,
                created_at TEXT,
                is_mutual INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                blocked_id INTEGER,
                created_at TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reported_id INTEGER,
                reason TEXT,
                created_at TEXT
            )
        ''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name):
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, created_at, last_active) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now().isoformat(), datetime.now().isoformat())
        )
        self.conn.commit()
    
    def update_profile(self, user_id, **kwargs):
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(user_id)
        query = f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?"
        self.cursor.execute(query, values)
        self.conn.commit()
    
    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def get_user_dict(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        columns = [description[0] for description in self.cursor.description]
        return dict(zip(columns, row))
    
    def get_random_profiles(self, user_id, limit=10):
        user = self.get_user_dict(user_id)
        if not user or not user.get('gender'):
            return []
        
        opposite = 'female' if user['gender'] == 'male' else 'male'
        
        self.cursor.execute("""
            SELECT * FROM users 
            WHERE user_id != ? AND gender = ? AND is_active = 1 
            AND user_id NOT IN (SELECT blocked_id FROM blocks WHERE user_id = ?)
            AND user_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
            AND photo_id IS NOT NULL
            ORDER BY RANDOM() LIMIT ?
        """, (user_id, opposite, user_id, user_id, limit))
        
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def add_like(self, from_user, to_user, is_superlike=0):
        self.cursor.execute(
            "INSERT INTO likes (from_user, to_user, is_superlike, created_at) VALUES (?, ?, ?, ?)",
            (from_user, to_user, is_superlike, datetime.now().isoformat())
        )
        self.conn.commit()
        
        # Проверка взаимности
        self.cursor.execute(
            "SELECT * FROM likes WHERE from_user = ? AND to_user = ?",
            (to_user, from_user)
        )
        if self.cursor.fetchone():
            self.cursor.execute(
                "UPDATE likes SET is_mutual = 1 WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)",
                (from_user, to_user, to_user, from_user)
            )
            self.conn.commit()
            return True
        return False
    
    def get_mutual_likes(self, user_id):
        self.cursor.execute("""
            SELECT u.* FROM users u
            JOIN likes l ON (u.user_id = l.from_user OR u.user_id = l.to_user)
            WHERE l.is_mutual = 1 AND (l.from_user = ? OR l.to_user = ?)
            AND u.user_id != ?
        """, (user_id, user_id, user_id))
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def get_likes_received(self, user_id):
        self.cursor.execute("""
            SELECT u.*, l.is_superlike, l.created_at as like_date FROM users u
            JOIN likes l ON u.user_id = l.from_user
            WHERE l.to_user = ? AND l.is_mutual = 0
            ORDER BY l.created_at DESC
        """, (user_id,))
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def decrement_likes(self, user_id):
        self.cursor.execute(
            "UPDATE users SET likes_left = likes_left - 1 WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()
    
    def decrement_superlikes(self, user_id):
        self.cursor.execute(
            "UPDATE users SET superlikes_left = superlikes_left - 1 WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()
    
    def reset_daily_limits(self, user_id):
        self.cursor.execute(
            "UPDATE users SET likes_left = 10, superlikes_left = 1 WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()
    
    def activate_premium(self, user_id, days):
        until = datetime.now() + timedelta(days=days)
        self.cursor.execute(
            "UPDATE users SET is_premium = 1, premium_until = ?, likes_left = 999, superlikes_left = 5 WHERE user_id = ?",
            (until.isoformat(), user_id)
        )
        self.conn.commit()
    
    def is_premium(self, user_id):
        user = self.get_user_dict(user_id)
        if not user:
            return False
        if user.get('is_premium') and user.get('premium_until'):
            until = datetime.fromisoformat(user['premium_until'])
            if until > datetime.now():
                return True
            else:
                self.cursor.execute(
                    "UPDATE users SET is_premium = 0, premium_until = NULL, likes_left = 10, superlikes_left = 1 WHERE user_id = ?",
                    (user_id,)
                )
                self.conn.commit()
        return False
    
    def add_block(self, user_id, blocked_id):
        self.cursor.execute(
            "INSERT INTO blocks (user_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (user_id, blocked_id, datetime.now().isoformat())
        )
        self.conn.commit()
    
    def add_report(self, user_id, reported_id, reason):
        self.cursor.execute(
            "INSERT INTO reports (user_id, reported_id, reason, created_at) VALUES (?, ?, ?, ?)",
            (user_id, reported_id, reason, datetime.now().isoformat())
        )
        self.conn.commit()
    
    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        total = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM likes")
        likes = self.cursor.fetchone()[0]
        return {"total": total, "premium": premium, "likes": likes}

db = Database()

# ==================== СОСТОЯНИЯ FSM ====================
class Registration(StatesGroup):
    gender = State()
    age = State()
    city = State()
    bio = State()
    photo = State()

class EditProfile(StatesGroup):
    field = State()
    value = State()

class ReportState(StatesGroup):
    reason = State()

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ==================== КЛАВИАТУРЫ ====================
def main_menu_kb(is_premium=False):
    kb = InlineKeyboardBuilder()
    kb.button(text="💖 Смотреть анкеты", callback_data="browse")
    kb.button(text="👤 Моя анкета", callback_data="my_profile")
    kb.button(text="❤️ Мои лайки", callback_data="my_likes")
    kb.button(text="💎 Премиум", callback_data="premium")
    kb.button(text="⚙️ Настройки", callback_data="settings")
    if is_premium:
        kb.button(text="👑 Мои мэтчи", callback_data="matches")
    kb.adjust(2)
    return kb.as_markup()

def gender_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Мужчина", callback_data="gender_male")
    kb.button(text="👩 Женщина", callback_data="gender_female")
    return kb.as_markup()

def profile_actions_kb(user_id, is_premium=False):
    kb = InlineKeyboardBuilder()
    kb.button(text="❤️ Лайк", callback_data=f"like_{user_id}")
    kb.button(text="🔥 Суперлайк", callback_data=f"superlike_{user_id}")
    kb.button(text="💬 Написать", callback_data=f"message_{user_id}")
    kb.button(text="🚫 Пожаловаться", callback_data=f"report_{user_id}")
    kb.button(text="➡️ Далее", callback_data="next_profile")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    return kb.as_markup()

def premium_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 1 неделя - 199₽", callback_data="premium_week")
    kb.button(text="📅 1 месяц - 499₽", callback_data="premium_month")
    kb.button(text="📅 3 месяца - 1299₽", callback_data="premium_quarter")
    kb.button(text="📅 1 год - 3999₽", callback_data="premium_year")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    return kb.as_markup()

def settings_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить анкету", callback_data="edit_profile")
    kb.button(text="🖼 Сменить фото", callback_data="change_photo")
    kb.button(text="📝 Сменить описание", callback_data="change_bio")
    kb.button(text="🔕 Удалить анкету", callback_data="delete_profile")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    return kb.as_markup()

def admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📢 Рассылка", callback_data="admin_broadcast")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="main_menu")
    return kb.as_markup()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def format_profile(user: dict) -> str:
    gender_emoji = "👨" if user['gender'] == 'male' else "👩"
    premium_badge = "👑 PREMIUM" if user['is_premium'] else ""
    age = user['age'] or "?"
    city = user['city'] or "Не указан"
    bio = user['bio'] or "Нет описания"
    
    text = f"{gender_emoji} <b>{user['first_name']}</b>, {age} лет\n"
    text += f"📍 {city}\n"
    if premium_badge:
        text += f"{premium_badge}\n"
    text += f"\n📝 {bio}\n"
    return text

def get_premium_features():
    return (
        "👑 <b>Премиум возможности LoveSpark:</b>\n\n"
        "✨ <b>Безлимитные лайки</b> - ставьте лайки без ограничений\n"
        "🔥 <b>5 суперлайков в день</b> - выделитесь среди других\n"
        "💬 <b>Прямые сообщения</b> - пишите понравившимся людям\n"
        "👀 <b>Кто лайкнул вас</b> - видите всех, кто проявил интерес\n"
        "💎 <b>Значок премиум</b> - ваша анкета выделяется\n"
        "🚀 <b>Приоритет в поиске</b> - вас видят первыми\n"
        "🚫 <b>Без рекламы</b> - чистый интерфейс\n\n"
        "💰 Выберите подходящий тариф:"
    )

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    db.add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    user = db.get_user_dict(user_id)
    
    if user and user.get('gender'):
        # Уже зарегистрирован
        is_premium = db.is_premium(user_id)
        welcome_text = (
            f"💖 <b>Добро пожаловать в LoveSpark!</b> 💖\n\n"
            f"Привет, {message.from_user.first_name}! Рады тебя видеть снова!\n\n"
            f"{'👑 У вас активна премиум подписка!' if is_premium else '💎 Оформите премиум для полного доступа'}\n\n"
            f"❤️ Лайков сегодня: {user['likes_left']}\n"
            f"🔥 Суперлайков: {user['superlikes_left']}\n\n"
            f"Выберите действие:"
        )
        await message.answer(welcome_text, reply_markup=main_menu_kb(is_premium))
    else:
        # Новый пользователь - регистрация
        welcome_text = (
            f"💖 <b>Добро пожаловать в LoveSpark!</b> 💖\n\n"
            f"Привет, {message.from_user.first_name}! \n"
            f"Я бот для знакомств, который поможет тебе найти свою вторую половинку! 💘\n\n"
            f"🌟 <b>Что умеет LoveSpark:</b>\n"
            f"• Просматривать анкеты людей по всей России\n"
            f"• Ставить лайки и находить взаимную симпатию\n"
            f"• Общаться с мэтчами\n"
            f"• Премиум функции для максимального результата\n\n"
            f"📍 Работаем во всех городах России, включая ДНР и ЛНР\n\n"
            f"Давай создадим твою анкету! Выбери свой пол:"
        )
        await message.answer(welcome_text, reply_markup=gender_kb())
        await state.set_state(Registration.gender)

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = db.get_stats()
    text = (
        f"🔐 <b>Панель администратора</b>\n\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"💎 Премиум пользователей: {stats['premium']}\n"
        f"❤️ Всего лайков: {stats['likes']}\n"
    )
    await message.answer(text, reply_markup=admin_kb())

# ==================== РЕГИСТРАЦИЯ ====================
@router.callback_query(F.data.startswith("gender_"), Registration.gender)
async def process_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split("_")[1]
    await state.update_data(gender=gender)
    
    await callback.message.edit_text(
        "🎂 <b>Сколько тебе лет?</b>\n\nВведите ваш возраст (от 18 до 99):"
    )
    await state.set_state(Registration.age)

@router.message(Registration.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text)
        if age < 18 or age > 99:
            await message.answer("⚠️ Введите корректный возраст от 18 до 99 лет:")
            return
    except ValueError:
        await message.answer("⚠️ Введите число:")
        return
    
    await state.update_data(age=age)
    await message.answer(
        "📍 <b>Из какого ты города?</b>\n\nВведите название вашего города:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.city)

@router.message(Registration.city)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer(
        "📝 <b>Расскажи о себе</b>\n\nНапиши короткое описание о себе (до 500 символов):"
    )
    await state.set_state(Registration.bio)

@router.message(Registration.bio)
async def process_bio(message: Message, state: FSMContext):
    bio = message.text[:500]
    await state.update_data(bio=bio)
    await message.answer(
        "📸 <b>Загрузи свое фото</b>\n\nПришли мне свою лучшую фотографию для анкеты:"
    )
    await state.set_state(Registration.photo)

@router.message(Registration.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    photo_id = message.photo[-1].file_id
    
    db.update_profile(
        user_id=user_id,
        gender=data['gender'],
        age=data['age'],
        city=data['city'],
        bio=data['bio'],
        photo_id=photo_id,
        is_active=1
    )
    
    await state.clear()
    
    # Показываем созданную анкету
    user = db.get_user_dict(user_id)
    is_premium = db.is_premium(user_id)
    
    await message.answer("✅ <b>Анкета создана!</b>\n\nВот так выглядит твоя анкета:")
    await message.answer_photo(
        photo=photo_id,
        caption=format_profile(user),
        reply_markup=main_menu_kb(is_premium)
    )

# ==================== ПРОСМОТР АНКЕТ ====================
@router.callback_query(F.data == "browse")
async def browse_profiles(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = db.get_user_dict(user_id)
    
    if not user or not user.get('photo_id'):
        await callback.answer("❌ Сначала создайте анкету!")
        return
    
    # Проверяем лимиты
    if user['likes_left'] <= 0 and not db.is_premium(user_id):
        await callback.answer("💎 Лайки закончились! Оформите премиум!")
        await callback.message.edit_text(
            "😔 <b>Лайки на сегодня закончились!</b>\n\n"
            "💎 Оформите премиум подписку для безлимитных лайков:",
            reply_markup=premium_kb()
        )
        return
    
    profiles = db.get_random_profiles(user_id, limit=1)
    
    if not profiles:
        await callback.answer("😔 Пока нет анкет для просмотра")
        await callback.message.edit_text(
            "😔 <b>Пока нет новых анкет</b>\n\nПопробуйте позже или расширьте поиск!",
            reply_markup=back_kb()
        )
        return
    
    profile = profiles[0]
    await state.update_data(current_profile=profile['user_id'])
    
    is_premium = db.is_premium(user_id)
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await callback.message.answer_photo(
        photo=profile['photo_id'],
        caption=format_profile(profile),
        reply_markup=profile_actions_kb(profile['user_id'], is_premium)
    )

@router.callback_query(F.data == "next_profile")
async def next_profile(callback: CallbackQuery, state: FSMContext):
    await browse_profiles(callback, state)

# ==================== ЛАЙКИ И СУПЕРЛАЙКИ ====================
@router.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])
    
    user = db.get_user_dict(user_id)
    
    if user['likes_left'] <= 0 and not db.is_premium(user_id):
        await callback.answer("💎 Лайки закончились!")
        return
    
    db.decrement_likes(user_id)
    is_mutual = db.add_like(user_id, target_id)
    
    if is_mutual:
        # Взаимный лайк - мэтч!
        target = db.get_user_dict(target_id)
        await callback.answer("🎉 Ура! Взаимная симпатия!")
        
        await callback.message.answer(
            f"💖 <b>МЭТЧ!</b> 💖\n\n"
            f"Вы и {target['first_name']} понравились друг другу!\n"
            f"💬 Можете начать общение прямо сейчас!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💬 Написать {target['first_name']}", url=f"tg://user?id={target_id}")],
                [InlineKeyboardButton(text="➡️ Продолжить", callback_data="next_profile")]
            ])
        )
        
        # Уведомляем второго пользователя
        try:
            await bot.send_message(
                target_id,
                f"💖 <b>У вас новый мэтч!</b>\n\n"
                f"{user['first_name']} тоже поставил(а) вам лайк!\n"
                f"💬 Начните общение прямо сейчас!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"💬 Написать {user['first_name']}", url=f"tg://user?id={user_id}")],
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
        except:
            pass
    else:
        await callback.answer("❤️ Лайк отправлен!")
    
    # Показываем следующую анкету
    await asyncio.sleep(1)
    await browse_profiles(callback, state)

@router.callback_query(F.data.startswith("superlike_"))
async def process_superlike(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])
    
    user = db.get_user_dict(user_id)
    
    if user['superlikes_left'] <= 0:
        await callback.answer("🔥 Суперлайки закончились!")
        return
    
    db.decrement_superlikes(user_id)
    db.add_like(user_id, target_id, is_superlike=1)
    
    # Уведомляем целевого пользователя
    try:
        target = db.get_user_dict(target_id)
        await bot.send_message(
            target_id,
            f"🔥 <b>Суперлайк!</b>\n\n"
            f"Кто-то проявил к вам особый интерес! 💘\n"
            f"Загляните в бота, чтобы узнать кто!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Мои лайки", callback_data="my_likes")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ])
        )
    except:
        pass
    
    await callback.answer("🔥 Суперлайк отправлен!")
    await asyncio.sleep(1)
    await browse_profiles(callback, state)

# ==================== МОИ ЛАЙКИ ====================
@router.callback_query(F.data == "my_likes")
async def my_likes(callback: CallbackQuery):
    user_id = callback.from_user.id
    likes = db.get_likes_received(user_id)
    
    if not likes:
        await callback.answer("😔 Пока никто не лайкнул")
        await callback.message.edit_text(
            "😔 <b>Пока никто не проявил интереса</b>\n\n"
            "Не расстраивайтесь! Продолжайте просматривать анкеты и ставить лайки!",
            reply_markup=back_kb()
        )
        return
    
    text = f"❤️ <b>Вам понравились ({len(likes)}):</b>\n\n"
    for like in likes[:10]:
        superlike = "🔥 " if like['is_superlike'] else ""
        text += f"{superlike}{like['first_name']}, {like['age']} лет, 📍{like['city']}\n"
    
    kb = InlineKeyboardBuilder()
    for like in likes[:5]:
        kb.button(text=f"💬 {like['first_name']}", callback_data=f"message_{like['user_id']}")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

# ==================== МЭТЧИ ====================
@router.callback_query(F.data == "matches")
async def my_matches(callback: CallbackQuery):
    user_id = callback.from_user.id
    matches = db.get_mutual_likes(user_id)
    
    if not matches:
        await callback.answer("😔 Пока нет мэтчей")
        await callback.message.edit_text(
            "😔 <b>Пока нет взаимных симпатий</b>\n\n"
            "Продолжайте просматривать анкеты и ставить лайки!",
            reply_markup=back_kb()
        )
        return
    
    text = f"💖 <b>Ваши мэтчи ({len(matches)}):</b>\n\n"
    for match in matches:
        text += f"• {match['first_name']}, {match['age']} лет, 📍{match['city']}\n"
    
    kb = InlineKeyboardBuilder()
    for match in matches[:5]:
        kb.button(text=f"💬 {match['first_name']}", url=f"tg://user?id={match['user_id']}")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

# ==================== МОЯ АНКЕТА ====================
@router.callback_query(F.data == "my_profile")
async def my_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user_dict(user_id)
    
    if not user or not user.get('photo_id'):
        await callback.answer("❌ Сначала создайте анкету!")
        return
    
    is_premium = db.is_premium(user_id)
    premium_text = "👑 PREMIUM" if is_premium else ""
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редактировать", callback_data="edit_profile")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    kb.adjust(2)
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await callback.message.answer_photo(
        photo=user['photo_id'],
        caption=format_profile(user) + f"\n{premium_text}\n\n❤️ Лайков: {user['likes_left']}\n🔥 Суперлайков: {user['superlikes_left']}",
        reply_markup=kb.as_markup()
    )

# ==================== ПРЕМИУМ ====================
@router.callback_query(F.data == "premium")
async def show_premium(callback: CallbackQuery):
    await callback.message.edit_text(
        get_premium_features(),
        reply_markup=premium_kb()
    )

@router.callback_query(F.data.startswith("premium_"))
async def process_premium(callback: CallbackQuery):
    plan = callback.data.split("_")[1]
    plan_info = PREMIUM_PRICES.get(plan)
    
    if not plan_info:
        await callback.answer("❌ Ошибка!")
        return
    
    # Создаем инвойс для оплаты через Telegram Payments
    # YooMoney напрямую не поддерживается Telegram Payments API
    # Поэтому показываем инструкцию по оплате через YooMoney
    amount = plan_info['price']
    label = plan_info['label']
    
    text = (
        f"💎 <b>Премиум подписка - {label}</b>\n\n"
        f"💰 Стоимость: <b>{amount}₽</b>\n\n"
        f"📲 <b>Способ оплаты через YooMoney:</b>\n\n"
        f"1. Переведите <b>{amount}₽</b> на кошелек:\n"
        f"<code>{YOOMONEY_WALLET}</code>\n\n"
        f"2. В комментарии к переводу укажите:\n"
        f"<code>PREMIUM_{callback.from_user.id}_{plan}</code>\n\n"
        f"3. После оплаты нажмите кнопку ниже\n\n"
        f"⚡ Активация в течение 5 минут!"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я оплатил", callback_data=f"confirm_payment_{plan}")
    kb.button(text="🏠 Меню", callback_data="main_menu")
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: CallbackQuery):
    plan = callback.data.split("_")[2]
    plan_info = PREMIUM_PRICES.get(plan)
    
    if not plan_info:
        await callback.answer("❌ Ошибка!")
        return
    
    # Активируем премиум (в реальном боте здесь нужна проверка платежа)
    db.activate_premium(callback.from_user.id, plan_info['days'])
    
    await callback.answer("🎉 Премиум активирован!")
    await callback.message.edit_text(
        f"👑 <b>Премиум активирован!</b>\n\n"
        f"✅ Подписка: {plan_info['label']}\n"
        f"📅 Действует до: {(datetime.now() + timedelta(days=plan_info['days'])).strftime('%d.%m.%Y')}\n\n"
        f"🎉 Наслаждайтесь всеми премиум возможностями!",
        reply_markup=main_menu_kb(is_premium=True)
    )
    
    # Уведомляем админа
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Новая премиум подписка!</b>\n\n"
            f"Пользователь: {callback.from_user.id}\n"
            f"Тариф: {plan_info['label']}\n"
            f"Сумма: {plan_info['price']}₽"
        )
    except:
        pass

# ==================== НАСТРОЙКИ ====================
@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ <b>Настройки профиля</b>\n\nВыберите действие:",
        reply_markup=settings_kb()
    )

@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ <b>Что хотите изменить?</b>\n\n"
        "1. Возраст\n2. Город\n3. Описание\n4. Фото\n\n"
        "Введите номер пункта:"
    )
    await state.set_state(EditProfile.field)

@router.message(EditProfile.field)
async def process_edit_field(message: Message, state: FSMContext):
    choice = message.text.strip()
    
    if choice == "1":
        await message.answer("🎂 Введите новый возраст:")
        await state.update_data(field="age")
    elif choice == "2":
        await message.answer("📍 Введите новый город:")
        await state.update_data(field="city")
    elif choice == "3":
        await message.answer("📝 Введите новое описание:")
        await state.update_data(field="bio")
    elif choice == "4":
        await message.answer("📸 Пришлите новое фото:")
        await state.update_data(field="photo")
    else:
        await message.answer("❌ Неверный выбор. Введите 1, 2, 3 или 4:")
        return
    
    await state.set_state(EditProfile.value)

@router.message(EditProfile.value)
async def process_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data['field']
    user_id = message.from_user.id
    
    if field == "photo":
        if not message.photo:
            await message.answer("❌ Пришлите фото!")
            return
        db.update_profile(user_id, photo_id=message.photo[-1].file_id)
    elif field == "age":
        try:
            age = int(message.text)
            if age < 18 or age > 99:
                await message.answer("⚠️ Введите корректный возраст!")
                return
            db.update_profile(user_id, age=age)
        except ValueError:
            await message.answer("⚠️ Введите число!")
            return
    else:
        db.update_profile(user_id, **{field: message.text})
    
    await state.clear()
    await message.answer("✅ Изменения сохранены!", reply_markup=back_kb())

@router.callback_query(F.data == "delete_profile")
async def delete_profile(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Да, удалить", callback_data="confirm_delete")
    kb.button(text="✅ Нет, оставить", callback_data="main_menu")
    
    await callback.message.edit_text(
        "🗑 <b>Удаление анкеты</b>\n\n"
        "Вы уверены, что хотите удалить свою анкету?\n"
        "Все данные будут безвозвратно удалены!",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery):
    user_id = callback.from_user.id
    db.cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    db.cursor.execute("DELETE FROM likes WHERE from_user = ? OR to_user = ?", (user_id, user_id))
    db.cursor.execute("DELETE FROM blocks WHERE user_id = ? OR blocked_id = ?", (user_id, user_id))
    db.conn.commit()
    
    await callback.message.edit_text(
        "😢 <b>Ваша анкета удалена</b>\n\n"
        "Будем рады видеть вас снова! Нажмите /start для новой регистрации.",
        reply_markup=None
    )

# ==================== ЖАЛОБЫ ====================
@router.callback_query(F.data.startswith("report_"))
async def start_report(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target=target_id)
    
    await callback.message.edit_text(
        "🚫 <b>Пожаловаться на пользователя</b>\n\n"
        "Введите причину жалобы:",
        reply_markup=back_kb()
    )
    await state.set_state(ReportState.reason)

@router.message(ReportState.reason)
async def process_report(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['report_target']
    user_id = message.from_user.id
    
    db.add_report(user_id, target_id, message.text)
    
    # Уведомляем админа
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🚫 <b>Новая жалоба!</b>\n\n"
            f"От: {user_id}\n"
            f"На: {target_id}\n"
            f"Причина: {message.text}"
        )
    except:
        pass
    
    await state.clear()
    await message.answer(
        "✅ Жалоба отправлена администратору.\n\nСпасибо за помощь в поддержании порядка!",
        reply_markup=back_kb()
    )

# ==================== СООБЩЕНИЯ ====================
@router.callback_query(F.data.startswith("message_"))
async def send_message_link(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user = db.get_user_dict(target_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!")
        return
    
    is_premium = db.is_premium(callback.from_user.id)
    if not is_premium:
        await callback.answer("💎 Только для премиум!")
        return
    
    await callback.message.answer(
        f"💬 <b>Написать {user['first_name']}</b>\n\n"
        f"Нажмите на кнопку ниже, чтобы открыть чат:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💬 Написать", url=f"tg://user?id={target_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="next_profile")]
        ])
    )

# ==================== ГЛАВНОЕ МЕНЮ ====================
@router.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user_dict(user_id)
    is_premium = db.is_premium(user_id)
    
    if not user or not user.get('gender'):
        await callback.message.edit_text(
            "❌ <b>Сначала создайте анкету!</b>\n\nНажмите /start для регистрации."
        )
        return
    
    text = (
        f"💖 <b>LoveSpark - Главное меню</b> 💖\n\n"
        f"Привет, {user['first_name']}!\n\n"
        f"{'👑 Премиум активен!' if is_premium else '💎 Оформите премиум для полного доступа'}\n\n"
        f"❤️ Лайков сегодня: {user['likes_left']}\n"
        f"🔥 Суперлайков: {user['superlikes_left']}\n\n"
        f"Выберите действие:"
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb(is_premium))
    except:
        await callback.message.answer(text, reply_markup=main_menu_kb(is_premium))

# ==================== АДМИНКА ====================
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    stats = db.get_stats()
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"💎 Премиум: {stats['premium']}\n"
        f"❤️ Всего лайков: {stats['likes']}\n\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        reply_markup=admin_kb()
    )

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВведите текст для рассылки всем пользователям:"
    )

# ==================== ЗАПУСК ====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
