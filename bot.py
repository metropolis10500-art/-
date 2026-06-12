import asyncio
import os
import sqlite3
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== СОСТОЯНИЯ ====================
class ProfileSetup(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    bio = State()
    photo = State()

class EditProfile(StatesGroup):
    field = State()
    value = State()

class ChatState(StatesGroup):
    active = State()

class ReportState(StatesGroup):
    reason = State()

class VerifyState(StatesGroup):
    photo = State()

class AdminPremium(StatesGroup):
    user_id = State()
    days = State()

class AdminBroadcast(StatesGroup):
    text = State()

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('love_spark.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        name TEXT,
        age INTEGER,
        gender TEXT,
        city TEXT,
        bio TEXT,
        photo_id TEXT,
        verify_photo_id TEXT,
        is_verified INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0,
        premium_until TIMESTAMP,
        is_visible INTEGER DEFAULT 1,
        profile_boosted_until TIMESTAMP,
        likes_left INTEGER DEFAULT 10,
        superlikes_left INTEGER DEFAULT 1,
        gifts_sent INTEGER DEFAULT 0,
        gifts_received INTEGER DEFAULT 0,
        total_likes INTEGER DEFAULT 0,
        total_matches INTEGER DEFAULT 0,
        profile_views INTEGER DEFAULT 0,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_banned INTEGER DEFAULT 0,
        ban_reason TEXT,
        search_age_from INTEGER DEFAULT 18,
        search_age_to INTEGER DEFAULT 50,
        search_gender TEXT,
        search_city TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        is_super INTEGER DEFAULT 0,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER,
        user2 INTEGER,
        last_message_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        from_user INTEGER,
        text TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS gifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        gift_type TEXT,
        gift_name TEXT,
        price INTEGER,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS gift_types (
        id INTEGER PRIMARY KEY,
        name TEXT,
        emoji TEXT,
        price INTEGER
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER,
        reported_id INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_type TEXT,
        product_name TEXT,
        price INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        activated_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_id INTEGER,
        blocked_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Заполняем подарки
    c.execute("SELECT COUNT(*) FROM gift_types")
    if c.fetchone()[0] == 0:
        gifts = [
            (1, 'Роза', '🌹', 29),
            (2, 'Сердце', '❤️', 49),
            (3, 'Букет', '💐', 99),
            (4, 'Кольцо', '💍', 199),
            (5, 'Корона', '👑', 299),
            (6, 'Бриллиант', '💎', 499),
        ]
        c.executemany("INSERT INTO gift_types VALUES (?,?,?,?)", gifts)
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect('love_spark.db')

def get_user(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, joined_at, last_reset, last_active) VALUES (?, ?, ?, ?)",
                  (user_id, datetime.now(), datetime.now(), datetime.now()))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    conn.close()
    return row

def update_activity(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now(), user_id))
    conn.commit()
    conn.close()

def reset_daily_limits(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_reset FROM users WHERE user_id = ?", (user_id,))
    last = c.fetchone()[0]
    last_dt = datetime.fromisoformat(last) if isinstance(last, str) else last
    
    if (datetime.now() - last_dt).days >= 1:
        c.execute('''UPDATE users SET likes_left = 10, superlikes_left = 1, last_reset = ? WHERE user_id = ?''',
                  (datetime.now(), user_id))
        conn.commit()
    conn.close()

def check_premium(user_id: int) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return False
    
    is_prem, until = row
    if is_prem and until:
        until_dt = datetime.fromisoformat(until) if isinstance(until, str) else until
        if until_dt > datetime.now():
            return True
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    return False

def is_boosted(user_id: int) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT profile_boosted_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row and row[0]:
        until_dt = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
        return until_dt > datetime.now()
    return False

def get_match_id(user1: int, user2: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM matches WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)",
              (user1, user2, user2, user1))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def is_blocked(user_id: int, target_id: int) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (user_id, target_id))
    row = c.fetchone()
    conn.close()
    return bool(row)

# ==================== КЛАВИАТУРЫ ====================
def main_menu(user_id: int):
    kb = [
        [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="browse")],
        [InlineKeyboardButton(text="💕 Взаимности", callback_data="my_likes"),
         InlineKeyboardButton(text="💌 Сообщения", callback_data="my_chats")],
        [InlineKeyboardButton(text="🎁 Подарки", callback_data="my_gifts"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="my_profile")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
         InlineKeyboardButton(text="💎 Премиум", callback_data="premium")],
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="🔑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def profile_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать анкету", callback_data="edit_profile")],
        [InlineKeyboardButton(text="📸 Сменить фото", callback_data="update_photo")],
        [InlineKeyboardButton(text="✅ Верификация", callback_data="verify_profile")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
    ])

def chat_menu(partner_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Отправить подарок", callback_data=f"send_gift_{partner_id}")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_{partner_id}")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data=f"report_{partner_id}")],
        [InlineKeyboardButton(text="◀️ К чатам", callback_data="my_chats")]
    ])

# ==================== КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    user = get_user(user_id)
    update_activity(user_id)
    
    if user[25]:  # is_banned
        await message.answer("⛔ Ваш аккаунт заблокирован.")
        return
    
    if not user[3]:  # name is null
        await message.answer(
            "💕 <b>Добро пожаловать в LoveSpark!</b>\n\n"
            "✨ Здесь начинаются настоящие истории\n\n"
            "Давайте создадим вашу анкету!\n\n"
            "📝 Шаг 1/6: Как вас зовут?",
            parse_mode="HTML"
        )
        await dp.fsm.set_state(message.from_user.id, ProfileSetup.name)
        return
    
    await message.answer(
        f"💕 <b>LoveSpark</b> — Бот знакомств\n\n"
        f"✨ Найди свою искру\n\n"
        f"🔍 Смотри анкеты\n"
        f"💕 Ставь лайки\n"
        f"💌 Общайся при взаимности\n"
        f"🎁 Отправляй подарки\n\n"
        f"{'✅ Профиль верифицирован' if user[9] else '⚠️ Пройди верификацию для доверия'}\n"
        f"{'💎 Премиум активен' if check_premium(user_id) else ''}",
        reply_markup=main_menu(user_id),
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer(
        "💕 <b>LoveSpark</b> — Главное меню",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="HTML"
    )

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    await show_profile_message(message.from_user.id, message)

@dp.message(Command("browse"))
async def cmd_browse(message: types.Message):
    await browse_from_message(message.from_user.id, message)

@dp.message(Command("premium"))
async def cmd_premium(message: types.Message):
    await show_premium_message(message.from_user.id, message)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "💕 <b>Помощь по LoveSpark</b>\n\n"
        f"/start — Запустить бота\n"
        f"/menu — Главное меню\n"
        f"/profile — Мой профиль\n"
        f"/browse — Смотреть анкеты\n"
        f"/premium — Премиум подписка\n"
        f"/help — Эта справка\n\n"
        f"💡 <b>Как это работает:</b>\n"
        f"1. Создай анкету\n"
        f"2. Смотри анкеты других\n"
        f"3. Ставь 💕 если понравился\n"
        f"4. При взаимности — откроется чат\n"
        f"5. Общайся и находи свою искру!\n\n"
        f"💎 Премиум даёт безлимитные лайки, видит кто лайкнул, и многое другое!",
        parse_mode="HTML"
    )

# ==================== РЕГИСТРАЦИЯ ====================
@dp.message(ProfileSetup.name)
async def set_name(message: types.Message, state: FSMContext):
    if len(message.text) > 30:
        await message.answer("❌ Слишком длинное имя (макс. 30 символов)")
        return
    await state.update_data(name=message.text)
    await message.answer("🎂 Шаг 2/6: Сколько вам лет?")
    await state.set_state(ProfileSetup.age)

@dp.message(ProfileSetup.age)
async def set_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text)
        if age < 18 or age > 100:
            await message.answer("❌ Возраст от 18 до 100 лет")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    await state.update_data(age=age)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужской", callback_data="gender_male"),
         InlineKeyboardButton(text="👩 Женский", callback_data="gender_female")]
    ])
    await message.answer("👤 Шаг 3/6: Ваш пол:", reply_markup=kb)
    await state.set_state(ProfileSetup.gender)

@dp.callback_query(F.data.startswith("gender_"))
async def set_gender(callback: types.CallbackQuery, state: FSMContext):
    gender = "male" if callback.data == "gender_male" else "female"
    await state.update_data(gender=gender)
    await callback.message.edit_text("🏙 Шаг 4/6: Из какого вы города?")
    await state.set_state(ProfileSetup.city)
    await callback.answer()

@dp.message(ProfileSetup.city)
async def set_city(message: types.Message, state: FSMContext):
    if len(message.text) > 30:
        await message.answer("❌ Слишком длинное название")
        return
    await state.update_data(city=message.text)
    await message.answer("💭 Шаг 5/6: Расскажите о себе (до 200 символов):")
    await state.set_state(ProfileSetup.bio)

@dp.message(ProfileSetup.bio)
async def set_bio(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer(f"❌ Слишком длинно ({len(message.text)}/200). Сократите:")
        return
    await state.update_data(bio=message.text)
    await message.answer(
        "📸 Шаг 6/6: Отправьте ваше лучшее фото:\n"
        "<i>Это фото увидят другие пользователи</i>"
    )
    await state.set_state(ProfileSetup.photo)

@dp.message(ProfileSetup.photo, F.photo)
async def set_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE users SET name = ?, age = ?, gender = ?, city = ?, bio = ?, photo_id = ?,
                 search_gender = ?
                 WHERE user_id = ?''',
              (data['name'], data['age'], data['gender'], data['city'], data['bio'], photo_id,
               'female' if data['gender'] == 'male' else 'male', message.from_user.id))
    conn.commit()
    conn.close()
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Анкета создана!</b>\n\n"
        f"Добро пожаловать в LoveSpark, {data['name']}!\n\n"
        f"Теперь вы можете:\n"
        f"🔍 Смотреть анкеты\n"
        f"💕 Ставить лайки\n"
        f"💌 Общаться при взаимности\n\n"
        f"💡 Совет: Пройдите верификацию, чтобы получать больше внимания!",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="HTML"
    )

# ==================== ПРОСМОТР АНКЕТ ====================
async def browse_from_message(user_id: int, message: types.Message):
    update_activity(user_id)
    reset_daily_limits(user_id)
    
    user = get_user(user_id)
    if user[25]:  # is_banned
        await message.answer("⛔ Ваш аккаунт заблокирован.")
        return
    
    is_premium = check_premium(user_id)
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT search_age_from, search_age_to, search_gender, search_city, gender, city, age 
                 FROM users WHERE user_id = ?''', (user_id,))
    search = c.fetchone()
    age_from, age_to, search_gender, search_city, my_gender, my_city, my_age = search
    
    query = '''SELECT user_id, name, age, city, bio, photo_id, is_verified, is_premium 
               FROM users 
               WHERE user_id != ? 
               AND gender = ?
               AND age BETWEEN ? AND ?
               AND is_visible = 1
               AND is_banned = 0
               AND user_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
               AND user_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
               AND user_id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)'''
    params = [user_id, search_gender or ('female' if my_gender == 'male' else 'male'), 
              age_from or 18, age_to or 100, user_id, user_id, user_id]
    
    if search_city:
        query += " AND city = ?"
        params.append(search_city)
    
    query += " ORDER BY CASE WHEN profile_boosted_until > datetime('now') THEN 0 ELSE 1 END, RANDOM() LIMIT 1"
    
    c.execute(query, params)
    profile = c.fetchone()
    conn.close()
    
    if not profile:
        await message.answer(
            "😔 Пока нет подходящих анкет.\n\n"
            "💡 Попробуйте изменить настройки поиска\n"
            "🚀 Или купите буст, чтобы вас видели чаще!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Фильтры", callback_data="filters")],
                [InlineKeyboardButton(text="🚀 Буст профиля", callback_data="buy_boost")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ])
        )
        return
    
    target_id, name, age, city, bio, photo_id, is_verified, target_premium = profile
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET profile_views = profile_views + 1 WHERE user_id = ?", (target_id,))
    conn.commit()
    c.execute("SELECT likes_left, superlikes_left FROM users WHERE user_id = ?", (user_id,))
    likes_left, superlikes_left = c.fetchone()
    conn.close()
    
    likes_text = "∞" if is_premium else likes_left
    super_text = "∞" if is_premium else superlikes_left
    verify_badge = "✅ " if is_verified else ""
    prem_badge = "💎 " if target_premium else ""
    boost_badge = "🚀 " if is_boosted(target_id) else ""
    
    caption = (
        f"{verify_badge}{prem_badge}{boost_badge}<b>{name}</b>, {age}\n"
        f"📍 {city}\n\n"
        f"{bio}\n\n"
        f"💕 Лайков: {likes_text} | ⭐ Супер: {super_text}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_{target_id}"),
            InlineKeyboardButton(text="💕 Лайк", callback_data=f"like_{target_id}"),
            InlineKeyboardButton(text="⭐ Супер", callback_data=f"superlike_{target_id}")
        ],
        [
            InlineKeyboardButton(text="🎁 Подарок", callback_data=f"gift_to_{target_id}"),
            InlineKeyboardButton(text="🚫 Жалоба", callback_data=f"report_{target_id}")
        ],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
    ])
    
    await message.answer_photo(photo_id, caption=caption, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "browse")
async def browse_callback(callback: types.CallbackQuery):
    await browse_from_message(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_"))
async def skip_profile(callback: types.CallbackQuery):
    await browse_callback(callback)

@dp.callback_query(F.data.startswith("like_"))
async def like_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])
    is_premium = check_premium(user_id)
    
    if is_blocked(target_id, user_id):
        await callback.answer("❌ Этот пользователь ограничил взаимодействие", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    
    if not is_premium:
        c.execute("SELECT likes_left FROM users WHERE user_id = ?", (user_id,))
        likes = c.fetchone()[0]
        if likes <= 0:
            await callback.answer("❌ Лайки закончились!", show_alert=True)
            conn.close()
            return
        c.execute("UPDATE users SET likes_left = likes_left - 1 WHERE user_id = ?", (user_id,))
    
    c.execute("INSERT INTO likes (from_user, to_user, created_at) VALUES (?, ?, ?)",
              (user_id, target_id, datetime.now()))
    
    c.execute("SELECT * FROM likes WHERE from_user = ? AND to_user = ?", (target_id, user_id))
    mutual = c.fetchone()
    
    if mutual:
        c.execute("INSERT INTO matches (user1, user2, created_at) VALUES (?, ?, ?)",
                  (min(user_id, target_id), max(user_id, target_id), datetime.now()))
        c.execute("UPDATE users SET total_matches = total_matches + 1 WHERE user_id IN (?, ?)",
                  (user_id, target_id))
        conn.commit()
        conn.close()
        
        try:
            c.execute("SELECT name FROM users WHERE user_id = ?", (user_id,))
            my_name = c.fetchone()[0]
            await bot.send_message(
                target_id,
                f"✨ <b>Искра зажглась!</b>\n\n"
                f"Вы понравились друг другу с {my_name}!\n"
                f"Начните общение 💌",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💌 Написать", callback_data=f"open_chat_{user_id}")]
                ]),
                parse_mode="HTML"
            )
        except:
            pass
        
        await callback.answer("✨ Искра! Открывайте чат!", show_alert=True)
    else:
        c.execute("UPDATE users SET total_likes = total_likes + 1 WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        
        if check_premium(target_id):
            try:
                c.execute("SELECT name FROM users WHERE user_id = ?", (user_id,))
                name = c.fetchone()[0]
                await bot.send_message(
                    target_id,
                    f"💕 <b>Новый лайк!</b>\n\n"
                    f"Кто-то заинтересовался вами!\n"
                    f"Купите премиум, чтобы увидеть кто.",
                    parse_mode="HTML"
                )
            except:
                pass
        
        await callback.answer("💕 Лайк отправлен!")
    
    await browse_callback(callback)

@dp.callback_query(F.data.startswith("superlike_"))
async def superlike_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])
    is_premium = check_premium(user_id)
    
    conn = get_db()
    c = conn.cursor()
    
    if not is_premium:
        c.execute("SELECT superlikes_left FROM users WHERE user_id = ?", (user_id,))
        supers = c.fetchone()[0]
        if supers <= 0:
            await callback.answer("❌ Супер-лайки закончились!", show_alert=True)
            conn.close()
            return
        c.execute("UPDATE users SET superlikes_left = superlikes_left - 1 WHERE user_id = ?", (user_id,))
    
    c.execute("INSERT INTO likes (from_user, to_user, is_super, created_at) VALUES (?, ?, 1, ?)",
              (user_id, target_id, datetime.now()))
    conn.commit()
    conn.close()
    
    try:
        c.execute("SELECT name FROM users WHERE user_id = ?", (user_id,))
        name = c.fetchone()[0]
        await bot.send_message(
            target_id,
            f"⭐ <b>Супер-лайк от {name}!</b>\n\n"
            f"Этот пользователь очень заинтересован в вами!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💕 Лайк в ответ", callback_data=f"like_{user_id}")]
            ]),
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.answer("⭐ Супер-лайк отправлен!")
    await browse_callback(callback)

# ==================== ПРОФИЛЬ ====================
async def show_profile_message(user_id: int, message: types.Message):
    update_activity(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT name, age, gender, city, bio, photo_id, is_verified, is_premium,
                 total_likes, total_matches, profile_views, gifts_received
                 FROM users WHERE user_id = ?''', (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await message.answer("❌ Анкета не найдена")
        return
    
    name, age, gender, city, bio, photo_id, is_verified, is_prem, likes, matches, views, gifts = row
    
    gender_icon = "👨" if gender == "male" else "👩"
    verify_badge = "✅ Верифицирован\n" if is_verified else "⚠️ Не верифицирован\n"
    prem_badge = "💎 Премиум активен\n" if check_premium(user_id) else ""
    
    caption = (
        f"{gender_icon} <b>{name}</b>, {age}\n"
        f"📍 {city}\n\n"
        f"{bio}\n\n"
        f"📊 Статистика:\n"
        f"👀 Просмотров: {views}\n"
        f"💕 Получено лайков: {likes}\n"
        f"✨ Искр: {matches}\n"
        f"🎁 Подарков: {gifts}\n\n"
        f"{verify_badge}"
        f"{prem_badge}"
    )
    
    await message.answer_photo(photo_id, caption=caption, reply_markup=profile_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "my_profile")
async def my_profile_callback(callback: types.CallbackQuery):
    # Удаляем старое сообщение и отправляем новое с фото
    try:
        await callback.message.delete()
    except:
        pass
    
    await show_profile_message(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "edit_profile")
async def edit_profile(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "✏️ <b>Редактирование анкеты</b>\n\n"
        "Что хотите изменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name"),
             InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
            [InlineKeyboardButton(text="🏙 Город", callback_data="edit_city"),
             InlineKeyboardButton(text="💭 О себе", callback_data="edit_bio")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="my_profile")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_"))
async def process_edit(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    field_names = {
        "name": "имя",
        "age": "возраст",
        "city": "город",
        "bio": "о себе"
    }
    
    await state.update_data(edit_field=field)
    await callback.message.edit_text(
        f"✏️ Введите новое {field_names.get(field, 'значение')}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="my_profile")]
        ])
    )
    await state.set_state(EditProfile.value)
    await callback.answer()

@dp.message(EditProfile.value)
async def save_edit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get('edit_field')
    user_id = message.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    
    if field == "age":
        try:
            val = int(message.text)
            if val < 18 or val > 100:
                await message.answer("❌ Возраст от 18 до 100")
                return
        except:
            await message.answer("❌ Введите число")
            return
    else:
        val = message.text
        if field == "bio" and len(val) > 200:
            await message.answer("❌ Максимум 200 символов")
            return
        if field in ["name", "city"] and len(val) > 30:
            await message.answer("❌ Максимум 30 символов")
            return
    
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (val, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ Изменено!", reply_markup=main_menu(user_id))

@dp.callback_query(F.data == "update_photo")
async def update_photo(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📸 Отправьте новое фото:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="my_profile")]
        ])
    )
    # В реальном боте — FSM для ожидания фото
    await callback.answer()

@dp.callback_query(F.data == "verify_profile")
async def start_verification(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,))
    is_verified = c.fetchone()[0]
    conn.close()
    
    if is_verified:
        await callback.answer("✅ Вы уже верифицированы!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "✅ <b>Верификация профиля</b>\n\n"
        "Отправьте селфи с листом бумаги, на котором написано:\n"
        f"<code>LoveSpark {user_id}</code>\n\n"
        "Это подтвердит, что вы реальный человек.\n"
        "Фото не публикуется, только проверяется модератором.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="my_profile")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

# ==================== ПРЕМИУМ ====================
async def show_premium_message(user_id: int, message: types.Message):
    is_premium = check_premium(user_id)
    
    if is_premium:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        until = c.fetchone()[0]
        conn.close()
        until_str = datetime.fromisoformat(until).strftime("%d.%m.%Y") if until else "неизвестно"
        
        await message.answer(
            f"💎 <b>Премиум активен</b>\n\n"
            f"До: <b>{until_str}</b>\n\n"
            f"Все функции доступны!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
        return
    
    text = (
        "💎 <b>Премиум подписка LoveSpark</b>\n\n"
        "✨ <b>Что вы получаете:</b>\n\n"
        "💕 <b>Безлимитные лайки</b>\n"
        "👁 <b>Видеть, кто вас лайкнул</b>\n"
        "💌 <b>Писать первым без взаимности</b>\n"
        "👻 <b>Режим невидимки</b>\n"
        "⭐ <b>5 супер-лайков в день</b>\n"
        "🚀 <b>Приоритет в поиске</b>\n"
        "🚫 <b>Нет рекламы</b>\n"
        "💎 <b>Значок премиум в профиле</b>\n\n"
        "📋 <b>Тарифы:</b>\n\n"
        "🥉 <b>Неделя</b> — 149 ₽\n"
        "🥈 <b>Месяц</b> — 399 ₽\n"
        "🥇 <b>3 месяца</b> — 999 ₽ (экономия 200 ₽)\n"
        "💎 <b>Год</b> — 2 999 ₽ (экономия 1 800 ₽)\n\n"
        "💡 <b>Популярный выбор:</b> Месяц за 399 ₽\n\n"
        f"Для покупки переведите сумму на карту:\n"
        f"<code>2200 1234 5678 9012</code>\n"
        f"И отправьте скриншот администратору."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Написать админу", url=f"tg://user?id={ADMIN_ID}")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "premium")
async def premium_callback(callback: types.CallbackQuery):
    await show_premium_message(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "buy_boost")
async def buy_boost(callback: types.CallbackQuery):
    text = (
        "🚀 <b>Буст профиля</b>\n\n"
        "Ваш профиль будет показываться в топе поиска 24 часа!\n\n"
        f"💰 <b>99 ₽ / 24 часа</b>\n\n"
        f"Для покупки переведите 99 ₽ на карту:\n"
        f"<code>2200 1234 5678 9012</code>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Написать админу", url=f"tg://user?id={ADMIN_ID}")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# ==================== ВЗАИМНОСТИ ====================
@dp.callback_query(F.data == "my_likes")
async def my_likes(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_premium = check_premium(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT l.from_user, u.name, u.age, u.photo_id, u.is_verified, l.is_super, l.created_at
                 FROM likes l
                 JOIN users u ON l.from_user = u.user_id
                 WHERE l.to_user = ? AND l.is_read = 0
                 ORDER BY l.created_at DESC''', (user_id,))
    likes = c.fetchall()
    
    c.execute("UPDATE likes SET is_read = 1 WHERE to_user = ?", (user_id,))
    conn.commit()
    conn.close()
    
    if not likes:
        await callback.message.edit_text(
            "💕 Пока никто не заинтересовался.\n\n"
            "Активнее просматривайте анкеты!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="browse")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        return
    
    if not is_premium:
        count = len(likes)
        await callback.message.edit_text(
            f"💕 <b>Вас заинтересовались {count} человек(а)</b>\n\n"
            f"🔒 Чтобы видеть, кто именно — купите премиум!\n\n"
            f"💎 Премиум даёт:\n"
            f"✅ Видеть всех, кто лайкнул\n"
            f"✅ Безлимитные лайки\n"
            f"✅ Писать первым\n"
            f"✅ Режим невидимки",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Купить премиум", callback_data="premium")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    text = "💕 <b>Вас заинтересовались:</b>\n\n"
    kb = []
    
    for from_id, name, age, photo_id, is_verified, is_super, created in likes[:10]:
        verify = "✅ " if is_verified else ""
        super_badge = "⭐ " if is_super else ""
        kb.append([InlineKeyboardButton(
            text=f"{super_badge}{verify}{name}, {age}", 
            callback_data=f"like_{from_id}"
        )])
    
    kb.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ==================== ЧАТЫ ====================
@dp.callback_query(F.data == "my_chats")
async def my_chats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    update_activity(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT m.id, m.user1, m.user2, u.name, u.photo_id, 
                 (SELECT COUNT(*) FROM messages WHERE match_id = m.id AND from_user != ? AND is_read = 0) as unread
                 FROM matches m
                 JOIN users u ON (CASE WHEN m.user1 = ? THEN m.user2 ELSE m.user1 END) = u.user_id
                 WHERE m.user1 = ? OR m.user2 = ?
                 ORDER BY m.last_message_at DESC NULLS LAST''', (user_id, user_id, user_id, user_id))
    matches = c.fetchall()
    conn.close()
    
    if not matches:
        await callback.message.edit_text(
            "💌 Пока нет искр.\n\n"
            "Ставьте лайки, чтобы найти свою искру!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="browse")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        return
    
    text = "💌 <b>Ваши искры:</b>\n\n"
    kb = []
    
    for mid, u1, u2, name, photo_id, unread in matches:
        partner_id = u2 if u1 == user_id else u1
        unread_badge = f" 🔴{unread}" if unread else ""
        kb.append([InlineKeyboardButton(text=f"💬 {name}{unread_badge}", callback_data=f"open_chat_{partner_id}")])
    
    kb.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("open_chat_"))
async def open_chat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    partner_id = int(callback.data.split("_")[2])
    
    if is_blocked(user_id, partner_id) or is_blocked(partner_id, user_id):
        await callback.answer("⛔ Чат недоступен", show_alert=True)
        return
    
    match_id = get_match_id(user_id, partner_id)
    if not match_id:
        await callback.answer("❌ Нет искры!", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("UPDATE messages SET is_read = 1 WHERE match_id = ? AND from_user = ? AND is_read = 0",
              (match_id, partner_id))
    
    c.execute('''SELECT from_user, text, created_at FROM messages 
                 WHERE match_id = ? ORDER BY created_at DESC LIMIT 20''', (match_id,))
    messages = c.fetchall()[::-1]
    
    c.execute("SELECT name, photo_id FROM users WHERE user_id = ?", (partner_id,))
    name, photo_id = c.fetchone()
    
    conn.commit()
    conn.close()
    
    text = f"💬 <b>Чат с {name}</b>\n\n"
    for msg_from, msg_text, msg_time in messages:
        sender = "Вы" if msg_from == user_id else name
        text += f"<b>{sender}:</b> {msg_text}\n"
    
    if not messages:
        text += "<i>✨ Искра зажглась! Начните общение 👇</i>"
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await callback.message.answer_photo(
        photo_id,
        caption=text,
        reply_markup=chat_menu(partner_id),
        parse_mode="HTML"
    )
    await callback.answer()

# ==================== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ ====================
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, есть ли активный чат (упрощённо)
    # В полной версии нужен менеджер активных чатов через FSM или Redis
    
    # Если это не команда и не ответ на вопрос бота — игнорируем или отправляем в меню
    await message.answer(
        "💕 Используйте меню для навигации:",
        reply_markup=main_menu(user_id)
    )

# ==================== ПОДАРКИ ====================
@dp.callback_query(F.data == "my_gifts")
async def my_gifts(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT g.gift_name, g.gift_type, g.price, u.name, g.created_at
                 FROM gifts g
                 JOIN users u ON g.from_user = u.user_id
                 WHERE g.to_user = ?
                 ORDER BY g.created_at DESC LIMIT 10''', (user_id,))
    gifts = c.fetchall()
    conn.close()
    
    if not gifts:
        await callback.message.edit_text(
            "🎁 Пока нет подарков.\n\n"
            "Получайте больше лайков, чтобы получать подарки!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="browse")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        return
    
    text = "🎁 <b>Ваши подарки:</b>\n\n"
    for name, emoji, price, from_name, created in gifts:
        text += f"{emoji} <b>{name}</b> от {from_name} ({price} ₽)\n"
    
    kb = [[InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("gift_to_"))
async def select_gift(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, emoji, price FROM gift_types")
    gifts = c.fetchall()
    c.execute("SELECT name FROM users WHERE user_id = ?", (target_id,))
    target_name = c.fetchone()[0]
    conn.close()
    
    text = f"🎁 <b>Подарок для {target_name}</b>\n\nВыберите подарок:"
    kb = []
    
    for gid, name, emoji, price in gifts:
        kb.append([InlineKeyboardButton(text=f"{emoji} {name} — {price} ₽", callback_data=f"sendgift_{target_id}_{gid}")])
    
    kb.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ==================== НАСТРОЙКИ ====================
@dp.callback_query(F.data == "settings")
async def settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_premium = check_premium(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_visible, search_age_from, search_age_to, search_city FROM users WHERE user_id = ?", (user_id,))
    visible, age_from, age_to, search_city = c.fetchone()
    conn.close()
    
    text = "⚙️ <b>Настройки</b>\n\n"
    kb = []
    
    if is_premium:
        status = "🟢 Видим" if visible else "🔴 Скрыт"
        kb.append([InlineKeyboardButton(text=f"👻 Невидимка: {status}", callback_data="toggle_invisible")])
    
    kb.append([InlineKeyboardButton(text="🔍 Фильтры поиска", callback_data="filters")])
    kb.append([InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="delete_profile")])
    kb.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "filters")
async def search_filters(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔍 <b>Фильтры поиска</b>\n\n"
        "В разработке. Скоро вы сможете настроить:\n"
        "• Возрастной диапазон\n"
        "• Город\n"
        "• Радиус поиска\n\n"
        "💎 Доступно в премиум!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить премиум", callback_data="premium")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="settings")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "toggle_invisible")
async def toggle_invisible(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not check_premium(user_id):
        await callback.answer("❌ Только для премиум!", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_visible FROM users WHERE user_id = ?", (user_id,))
    current = c.fetchone()[0]
    new_val = 0 if current else 1
    c.execute("UPDATE users SET is_visible = ? WHERE user_id = ?", (new_val, user_id))
    conn.commit()
    conn.close()
    
    status = "видим" if new_val else "невидим"
    await callback.answer(f"Профиль теперь {status}!")
    await settings(callback)

# ==================== ЖАЛОБА ====================
@dp.callback_query(F.data.startswith("report_"))
async def report_user(callback: types.CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    
    await state.update_data(reported_id=target_id)
    await callback.message.edit_text(
        "⚠️ <b>Жалоба на пользователя</b>\n\n"
        "Выберите причину:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖼 Фейковые фото", callback_data="report_reason_fake")],
            [InlineKeyboardButton(text="💰 Просит деньги", callback_data="report_reason_money")],
            [InlineKeyboardButton(text="🚫 Оскорбления", callback_data="report_reason_abuse")],
            [InlineKeyboardButton(text="🔞 Неприемлемый контент", callback_data="report_reason_adult")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="main_menu")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(ReportState.reason)
    await callback.answer()

@dp.callback_query(F.data.startswith("report_reason_"))
async def report_reason(callback: types.CallbackQuery, state: FSMContext):
    reason_map = {
        "report_reason_fake": "Фейковые фото",
        "report_reason_money": "Просит деньги",
        "report_reason_abuse": "Оскорбления",
        "report_reason_adult": "Неприемлемый контент"
    }
    reason = reason_map.get(callback.data, "Другое")
    
    data = await state.get_data()
    target_id = data.get('reported_id')
    reporter_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO reports (reporter_id, reported_id, reason, created_at)
                 VALUES (?, ?, ?, ?)''', (reporter_id, target_id, reason, datetime.now()))
    conn.commit()
    conn.close()
    
    await state.clear()
    
    try:
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Новая жалоба!</b>\n\n"
            f"От: {reporter_id}\n"
            f"На: {target_id}\n"
            f"Причина: {reason}",
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.message.edit_text(
        "✅ Жалоба отправлена модератору.\n\nСпасибо за помощь в поддержании порядка!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
        ])
    )
    await callback.answer()

# ==================== БЛОКИРОВКА ====================
@dp.callback_query(F.data.startswith("block_"))
async def block_user(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
              (user_id, target_id, datetime.now()))
    conn.commit()
    conn.close()
    
    await callback.answer("🚫 Пользователь заблокирован!")
    await callback.message.edit_text(
        "🚫 Пользователь заблокирован.\n\nОн больше не сможет с вами связаться.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
        ])
    )

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа!", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM matches")
    total_matches = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    pending_reports = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM purchases WHERE status = 'pending'")
    pending_purchases = c.fetchone()[0]
    conn.close()
    
    text = (
        f"🔑 <b>Админ-панель LoveSpark</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"💎 Премиум: <b>{premium_users}</b>\n"
        f"✨ Искр: <b>{total_matches}</b>\n"
        f"⚠️ Жалоб: <b>{pending_reports}</b>\n"
        f"💰 Заявок на оплату: <b>{pending_purchases}</b>\n\n"
        f"Выберите действие:"
    )
    
    kb = [
        [InlineKeyboardButton(text="💎 Активировать премиум", callback_data="admin_activate_premium")],
        [InlineKeyboardButton(text="⚠️ Жалобы", callback_data="admin_reports")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_activate_premium")
async def admin_activate_premium(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.edit_text(
        "💎 <b>Активация премиума</b>\n\n"
        "Отправьте: ID_пользователя количество_дней\n"
        "<i>Например: 123456789 30</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(AdminPremium.user_id)
    await callback.answer()

@dp.message(AdminPremium.user_id)
async def process_premium_activation(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    try:
        parts = message.text.split()
        user_id = int(parts[0])
        days = int(parts[1])
    except:
        await message.answer("❌ Формат: ID_пользователя количество_дней")
        return
    
    until = datetime.now() + timedelta(days=days)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?",
              (until, user_id))
    c.execute("INSERT INTO purchases (user_id, product_type, product_name, price, status, activated_at) VALUES (?, ?, ?, ?, 'completed', ?)",
              (user_id, 'premium', f'Premium {days} days', 0, datetime.now()))
    conn.commit()
    conn.close()
    
    await state.clear()
    
    await message.answer(f"✅ Премиум активирован для {user_id} на {days} дней!")
    
    try:
        await bot.send_message(
            user_id,
            f"💎 <b>Премиум активирован!</b>\n\n"
            f"Срок: <b>{days}</b> дней\n"
            f"До: <b>{until.strftime('%d.%m.%Y')}</b>\n\n"
            f"Наслаждайтесь всеми преимуществами!",
            parse_mode="HTML"
        )
    except:
        pass

@dp.callback_query(F.data == "admin_reports")
async def admin_reports(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT r.id, r.reporter_id, r.reported_id, r.reason, r.created_at, u1.username, u2.username
                 FROM reports r
                 JOIN users u1 ON r.reporter_id = u1.user_id
                 JOIN users u2 ON r.reported_id = u2.user_id
                 WHERE r.status = 'pending'
                 ORDER BY r.created_at''')
    reports = c.fetchall()
    conn.close()
    
    if not reports:
        await callback.message.edit_text(
            "Нет жалоб на рассмотрении.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
            ])
        )
        await callback.answer()
        return
    
    for rid, rep_id, target_id, reason, created, rep_name, target_name in reports:
        text = (
            f"⚠️ <b>Жалоба #{rid}</b>\n"
            f"От: @{rep_name or rep_id}\n"
            f"На: @{target_name or target_id}\n"
            f"Причина: {reason}\n"
            f"Дата: {created}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отклонить", callback_data=f"report_dismiss_{rid}"),
                InlineKeyboardButton(text="🚫 Забанить", callback_data=f"report_ban_{rid}_{target_id}")
            ]
        ])
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    
    await callback.message.answer(
        "Все жалобы выше.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("report_dismiss_"))
async def dismiss_report(callback: types.CallbackQuery):
    rid = int(callback.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE reports SET status = 'dismissed', resolved_at = ? WHERE id = ?",
              (datetime.now(), rid))
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ Жалоба отклонена.")
    await callback.answer()

@dp.callback_query(F.data.startswith("report_ban_"))
async def ban_user(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    rid = int(parts[2])
    target_id = int(parts[3])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE reports SET status = 'resolved', resolved_at = ? WHERE id = ?", (datetime.now(), rid))
    c.execute("UPDATE users SET is_banned = 1, ban_reason = 'Жалобы пользователей' WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()
    
    try:
        await bot.send_message(target_id, "⛔ Ваш аккаунт заблокирован за нарушение правил.")
    except:
        pass
    
    await callback.message.edit_text("🚫 Пользователь забанен.")
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nОтправьте текст сообщения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(AdminBroadcast.text)
    await callback.answer()

@dp.message(AdminBroadcast.text)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    text = message.text
    await state.clear()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    for (uid,) in users:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-1 day')")
    active_day = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-7 days')")
    active_week = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM likes WHERE created_at > datetime('now', '-1 day')")
    likes_today = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM matches WHERE created_at > datetime('now', '-1 day')")
    matches_today = c.fetchone()[0]
    c.execute("SELECT SUM(price) FROM purchases WHERE status = 'completed'")
    total_revenue = c.fetchone()[0] or 0
    
    conn.close()
    
    text = (
        f"📊 <b>Статистика LoveSpark</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"📱 Активных за день: <b>{active_day}</b>\n"
        f"📱 Активных за неделю: <b>{active_week}</b>\n"
        f"💕 Лайков сегодня: <b>{likes_today}</b>\n"
        f"✨ Искр сегодня: <b>{matches_today}</b>\n"
        f"💰 Общая выручка: <b>{total_revenue}</b> ₽"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

# ==================== ГЛАВНОЕ МЕНЮ ====================
@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💕 <b>LoveSpark</b> — Бот знакомств\n\n"
        "✨ Найди свою искру\n\n"
        "🔍 Смотри анкеты\n"
        "💕 Ставь лайки\n"
        "💌 Общайся при взаимности\n"
        "🎁 Отправляй подарки",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode="HTML"
    )
    await callback.answer()

# ==================== ЕЖЕДНЕВНЫЕ ЗАДАЧИ ====================
async def daily_tasks():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute("UPDATE users SET likes_left = 10, superlikes_left = 1, last_reset = ?",
                  (datetime.now(),))
        
        c.execute("UPDATE users SET profile_boosted_until = NULL WHERE profile_boosted_until < ?",
                  (datetime.now(),))
        
        c.execute('''SELECT DISTINCT l.to_user, COUNT(*) 
                     FROM likes l 
                     WHERE l.created_at > datetime('now', '-1 day') 
                     AND l.is_read = 0
                     GROUP BY l.to_user''')
        for user_id, count in c.fetchall():
            try:
                await bot.send_message(
                    user_id,
                    f"💕 <b>У вас {count} новых лайков!</b>\n\n"
                    f"Откройте бота, чтобы посмотреть кто это.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔍 Смотреть", url=f"https://t.me/{(await bot.get_me()).username}")]
                    ]),
                    parse_mode="HTML"
                )
            except:
                pass
        
        conn.commit()
        conn.close()

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    asyncio.create_task(daily_tasks())
    print("💕 LoveSpark запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
