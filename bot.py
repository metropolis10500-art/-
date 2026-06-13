# -*- coding: utf-8 -*-
"""
LoveSpark - Бот знакомств для всех городов России, ДНР и ЛНР
Все в одном файле: бот, база данных, YooMoney, конфиг
"""

import logging
import asyncio
import sqlite3
import requests
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
ADMIN_ID = 5494544187

YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"

DB_PATH = "lovespark.db"

FREE_LIKES_PER_DAY = 10
FREE_PROFILES_PER_DAY = 20

PREMIUM_PRICES = {
    "1_day": {"price": 49, "label": "1 день", "hours": 24},
    "7_days": {"price": 199, "label": "7 дней", "hours": 168},
    "30_days": {"price": 499, "label": "30 дней", "hours": 720},
    "forever": {"price": 1499, "label": "Навсегда", "hours": 999999},
}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at TEXT,
            is_premium INTEGER DEFAULT 0,
            premium_until TEXT,
            likes_today INTEGER DEFAULT 0,
            profiles_viewed_today INTEGER DEFAULT 0,
            last_activity TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT,
            looking_for TEXT,
            about TEXT,
            photo_file_id TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER,
            to_user INTEGER,
            created_at TEXT,
            is_mutual INTEGER DEFAULT 0,
            UNIQUE(from_user, to_user)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            tariff TEXT,
            status TEXT DEFAULT 'pending',
            yoomoney_label TEXT,
            created_at TEXT,
            paid_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER,
            to_user INTEGER,
            reason TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, registered_at, last_activity)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, first_name, last_name, now, now))
    conn.commit()
    conn.close()


def update_activity(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE users SET last_activity = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()


def get_profile(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id = ? AND is_active = 1", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def save_profile(user_id, name, age, gender, city, looking_for, about, photo_file_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO profiles (user_id, name, age, gender, city, looking_for, about, photo_file_id, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (user_id, name, age, gender, city, looking_for, about, photo_file_id))
    conn.commit()
    conn.close()


def delete_profile(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE profiles SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def search_profiles(user_id, gender_filter=None, city_filter=None, min_age=None, max_age=None, limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT to_user FROM likes WHERE from_user = ?", (user_id,))
    liked = [r[0] for r in c.fetchall()]
    liked.append(user_id)

    query = "SELECT * FROM profiles WHERE is_active = 1 AND user_id NOT IN ({})".format(",".join(["?"]*len(liked)))
    params = liked[:]

    if gender_filter:
        query += " AND gender = ?"
        params.append(gender_filter)
    if city_filter:
        query += " AND city = ?"
        params.append(city_filter)
    if min_age:
        query += " AND age >= ?"
        params.append(min_age)
    if max_age:
        query += " AND age <= ?"
        params.append(max_age)

    query += " ORDER BY (SELECT is_premium FROM users WHERE users.user_id = profiles.user_id) DESC, RANDOM()"
    query += " LIMIT ?"
    params.append(limit)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows


def add_like(from_user, to_user):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("SELECT 1 FROM likes WHERE from_user = ? AND to_user = ?", (to_user, from_user))
    is_mutual = 1 if c.fetchone() else 0

    try:
        c.execute("""
            INSERT INTO likes (from_user, to_user, created_at, is_mutual)
            VALUES (?, ?, ?, ?)
        """, (from_user, to_user, now, is_mutual))

        if is_mutual:
            c.execute("UPDATE likes SET is_mutual = 1 WHERE from_user = ? AND to_user = ?", (to_user, from_user))

        c.execute("UPDATE users SET likes_today = likes_today + 1 WHERE user_id = ?", (from_user,))

        conn.commit()
        conn.close()
        return is_mutual
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_mutual_likes(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT l.from_user, p.name, p.photo_file_id, u.username
        FROM likes l
        JOIN profiles p ON l.from_user = p.user_id
        JOIN users u ON l.from_user = u.user_id
        WHERE l.to_user = ? AND l.is_mutual = 1
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_who_liked_me(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT l.from_user, p.name, p.photo_file_id, u.username
        FROM likes l
        JOIN profiles p ON l.from_user = p.user_id
        JOIN users u ON l.from_user = u.user_id
        WHERE l.to_user = ? AND l.is_mutual = 0
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def check_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return False

    is_premium, premium_until = row
    if is_premium and premium_until:
        until = datetime.fromisoformat(premium_until)
        if datetime.now() > until:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return False
        return True
    return False


def activate_premium(user_id, hours):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    until = (datetime.now() + timedelta(hours=hours)).isoformat()
    c.execute("UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?", (until, user_id))
    conn.commit()
    conn.close()


def add_payment(user_id, amount, tariff, yoomoney_label):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO payments (user_id, amount, tariff, yoomoney_label, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, tariff, yoomoney_label, now))
    conn.commit()
    payment_id = c.lastrowid
    conn.close()
    return payment_id


def get_payment_by_label(yoomoney_label):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE yoomoney_label = ?", (yoomoney_label,))
    row = c.fetchone()
    conn.close()
    return row


def mark_payment_paid(payment_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE payments SET status = 'paid', paid_at = ? WHERE id = ?", (now, payment_id))
    conn.commit()
    conn.close()


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM profiles WHERE is_active = 1")
    active_profiles = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM likes")
    total_likes = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM payments WHERE status = 'paid'")
    total_revenue = c.fetchone()[0] or 0
    conn.close()
    return {
        "total_users": total_users,
        "active_profiles": active_profiles,
        "premium_users": premium_users,
        "total_likes": total_likes,
        "total_revenue": total_revenue
    }


def add_report(from_user, to_user, reason):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO reports (from_user, to_user, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (from_user, to_user, reason, now))
    conn.commit()
    conn.close()


# ==================== YOOMONEY ====================
def get_auth_headers():
    return {
        "Authorization": "Bearer " + YOOMONEY_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded"
    }


def create_payment_link(user_id, tariff_key):
    if tariff_key not in PREMIUM_PRICES:
        return None, None

    tariff = PREMIUM_PRICES[tariff_key]
    amount = tariff["price"]
    label = "lovespark_" + str(user_id) + "_" + tariff_key + "_" + uuid.uuid4().hex[:8]

    add_payment(user_id, amount, tariff_key, label)

    payment_link = (
        "https://yoomoney.ru/quickpay/confirm.xml?"
        + "receiver=" + YOOMONEY_WALLET
        + "&quickpay-form=shop"
        + "&targets=LoveSpark+Premium+" + tariff['label']
        + "&paymentType=AC"
        + "&sum=" + str(amount)
        + "&label=" + label
        + "&successURL=https://t.me/LoveSparkBot"
    )

    return payment_link, label


def check_payment_yoomoney(label):
    try:
        response = requests.post(
            "https://yoomoney.ru/api/operation-history",
            headers=get_auth_headers(),
            data={"type": "deposition", "label": label}
        )

        if response.status_code == 200:
            data = response.json()
            operations = data.get("operations", [])

            for op in operations:
                if op.get("status") == "success":
                    return True
        return False
    except Exception as e:
        print("Ошибка проверки платежа: " + str(e))
        return False


def process_payment(label):
    payment = get_payment_by_label(label)
    if not payment:
        return False

    payment_id = payment[0]
    user_id = payment[1]
    tariff = payment[3]
    status = payment[4]

    if status == "paid":
        return True

    if check_payment_yoomoney(label):
        hours = PREMIUM_PRICES.get(tariff, {}).get("hours", 24)
        mark_payment_paid(payment_id)
        activate_premium(user_id, hours)
        return True

    return False


def get_balance():
    try:
        response = requests.post(
            "https://yoomoney.ru/api/account-info",
            headers=get_auth_headers()
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("balance", 0)
        return None
    except Exception as e:
        print("Ошибка получения баланса: " + str(e))
        return None


# ==================== БОТ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())


# ==================== СТЕЙТЫ ====================
class Registration(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    looking_for = State()
    about = State()
    photo = State()
    confirm = State()


class ReportState(StatesGroup):
    reason = State()


# ==================== КЛАВИАТУРЫ ====================
def main_menu_kb(is_premium=False):
    buttons = [
        [KeyboardButton(text="💘 Искать пару"), KeyboardButton(text="👤 Моя анкета")],
        [KeyboardButton(text="❤️ Мои лайки"), KeyboardButton(text="💎 Премиум")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Статистика")],
    ]
    if is_premium:
        buttons[1][0] = KeyboardButton(text="❤️ Мои лайки ⭐")
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def gender_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]
        ],
        resize_keyboard=True
    )


def looking_for_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👨 Мужчин"), KeyboardButton(text="👩 Женщин")],
            [KeyboardButton(text="💕 Всех")]
        ],
        resize_keyboard=True
    )


def confirm_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Всё верно"), KeyboardButton(text="🔄 Заполнить заново")]
        ],
        resize_keyboard=True
    )


def search_action_kb(target_user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Лайк", callback_data="like_" + str(target_user_id))],
        [InlineKeyboardButton(text="👎 Пропустить", callback_data="skip_" + str(target_user_id))],
        [InlineKeyboardButton(text="🚫 Пожаловаться", callback_data="report_" + str(target_user_id))],
    ])


def premium_kb():
    kb = []
    for key, tariff in PREMIUM_PRICES.items():
        kb.append([InlineKeyboardButton(
            text=tariff['label'] + " — " + str(tariff['price']) + "₽",
            callback_data="premium_" + key
        )])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать анкету", callback_data="edit_profile")],
        [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="delete_profile")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")],
    ])


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Баланс YooMoney", callback_data="admin_balance")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")],
    ])


# ==================== КОМАНДЫ ====================
async def set_commands():
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="search", description="Искать пару"),
        BotCommand(command="profile", description="Моя анкета"),
        BotCommand(command="premium", description="Премиум функции"),
        BotCommand(command="likes", description="Мои лайки"),
        BotCommand(command="settings", description="Настройки"),
    ]
    await bot.set_my_commands(commands)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    add_user(user_id, username, first_name, last_name)
    update_activity(user_id)

    is_premium = check_premium(user_id)

    welcome_text = """<b>💘 Добро пожаловать в LoveSpark!</b>

Привет, {name}! Я — твой помощник в поиске второй половинки.

✨ <b>Что я умею:</b>
• Находить людей рядом и по всей России
• Показывать анкеты с фото и описанием
• Соединять взаимные симпатии
• Защищать твою анонимность

🌍 <b>Работаю во всех городах России</b>, включая ДНР и ЛНР!

💎 <b>Премиум</b> открывает безлимитные лайки, приоритет в поиске и просмотр тех, кто тебя лайкнул!

Нажми <b>💘 Искать пару</b>, чтобы начать!""".format(name=first_name)

    await message.answer(welcome_text, reply_markup=main_menu_kb(is_premium))


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """<b>📖 Помощь по LoveSpark</b>

<b>Основные команды:</b>
/start — Запустить бота
/search — Начать поиск пары
/profile — Посмотреть свою анкету
/likes — Посмотреть лайки
/premium — Премиум функции
/settings — Настройки

<b>Как пользоваться:</b>
1️⃣ Создай анкету через 💘 Искать пару
2️⃣ Просматривай анкеты других
3️⃣ Ставь ❤️ Лайк тем, кто понравился
4️⃣ При взаимной симпатии — получи контакт!

<b>Безопасность:</b>
• Никто не видит твой номер телефона
• Можешь пожаловаться на нарушителя
• Удалить анкету в любой момент

По вопросам: @admin"""
    await message.answer(help_text)


# ==================== РЕГИСТРАЦИЯ ====================
@dp.message(F.text == "💘 Искать пару")
async def search_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    profile = get_profile(user_id)

    if profile:
        await start_search(message, user_id)
        return

    await message.answer(
        """<b>✨ Давай создадим твою анкету!</b>

Ответь на несколько простых вопросов, и я найду для тебя идеальную пару 💕

<b>Как тебя зовут?</b> (напиши своё имя)""",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.name)


@dp.message(Registration.name)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("❌ Имя должно быть от 2 до 30 символов. Попробуй ещё раз:")
        return
    await state.update_data(name=name)
    await message.answer("<b>Сколько тебе лет?</b> (напиши число)")
    await state.set_state(Registration.age)


@dp.message(Registration.age)
async def reg_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 16 or age > 100:
            await message.answer("❌ Возраст должен быть от 16 до 100 лет. Попробуй ещё раз:")
            return
    except ValueError:
        await message.answer("❌ Пожалуйста, введи число:")
        return

    await state.update_data(age=age)
    await message.answer(
        "<b>Какой твой пол?</b>",
        reply_markup=gender_kb()
    )
    await state.set_state(Registration.gender)


@dp.message(Registration.gender)
async def reg_gender(message: types.Message, state: FSMContext):
    gender_map = {"👨 Мужчина": "male", "👩 Женщина": "female"}
    if message.text not in gender_map:
        await message.answer("❌ Выбери пол с помощью кнопок:", reply_markup=gender_kb())
        return

    await state.update_data(gender=gender_map[message.text])
    await message.answer(
        """<b>Из какого ты города?</b>

Напиши название города (например: Москва, Санкт-Петербург, Донецк, Луганск)""",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.city)


@dp.message(Registration.city)
async def reg_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2 or len(city) > 50:
        await message.answer("❌ Название города слишком короткое или длинное. Попробуй ещё раз:")
        return

    await state.update_data(city=city)
    await message.answer(
        "<b>Кого ты ищешь?</b>",
        reply_markup=looking_for_kb()
    )
    await state.set_state(Registration.looking_for)


@dp.message(Registration.looking_for)
async def reg_looking_for(message: types.Message, state: FSMContext):
    looking_map = {"👨 Мужчин": "male", "👩 Женщин": "female", "💕 Всех": "all"}
    if message.text not in looking_map:
        await message.answer("❌ Выбери вариант с помощью кнопок:", reply_markup=looking_for_kb())
        return

    await state.update_data(looking_for=looking_map[message.text])
    await message.answer(
        """<b>Расскажи немного о себе</b> 💭

Чем увлекаешься? Какой у тебя характер? Что ищешь в отношениях?
(от 20 до 500 символов)""",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.about)


@dp.message(Registration.about)
async def reg_about(message: types.Message, state: FSMContext):
    about = message.text.strip()
    if len(about) < 20 or len(about) > 500:
        await message.answer("❌ Описание должно быть от 20 до 500 символов. Попробуй ещё раз:")
        return

    await state.update_data(about=about)
    await message.answer(
        """<b>Отправь своё фото</b> 📸

Это главное фото твоей анкеты. Выбери лучшее!"""
    )
    await state.set_state(Registration.photo)


@dp.message(Registration.photo, F.photo)
async def reg_photo(message: types.Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)

    data = await state.get_data()

    gender_display = {"male": "👨 Мужчина", "female": "👩 Женщина"}
    looking_display = {"male": "👨 Мужчин", "female": "👩 Женщин", "all": "💕 Всех"}

    preview = """<b>📋 Твоя анкета:</b>

<b>Имя:</b> {name}
<b>Возраст:</b> {age} лет
<b>Пол:</b> {gender}
<b>Город:</b> {city}
<b>Ищу:</b> {looking}
<b>О себе:</b> {about}

<b>Всё верно?</b>""".format(
        name=data['name'],
        age=data['age'],
        gender=gender_display.get(data['gender'], data['gender']),
        city=data['city'],
        looking=looking_display.get(data['looking_for'], data['looking_for']),
        about=data['about']
    )

    await message.answer_photo(photo_file_id, caption=preview, reply_markup=confirm_kb())
    await state.set_state(Registration.confirm)


@dp.message(Registration.photo)
async def reg_photo_invalid(message: types.Message):
    await message.answer("❌ Пожалуйста, отправь фото (не файл).")


@dp.message(Registration.confirm, F.text == "✅ Всё верно")
async def reg_confirm_yes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id

    save_profile(
        user_id=user_id,
        name=data["name"],
        age=data["age"],
        gender=data["gender"],
        city=data["city"],
        looking_for=data["looking_for"],
        about=data["about"],
        photo_file_id=data["photo_file_id"]
    )

    await state.clear()
    is_premium = check_premium(user_id)

    await message.answer(
        """<b>🎉 Анкета создана!</b>

Теперь ты можешь искать свою вторую половинку! 💘

Нажми <b>💘 Искать пару</b>, чтобы начать просмотр анкет.""",
        reply_markup=main_menu_kb(is_premium)
    )


@dp.message(Registration.confirm, F.text == "🔄 Заполнить заново")
async def reg_confirm_no(message: types.Message, state: FSMContext):
    await state.clear()
    await search_start(message, state)


# ==================== ПОИСК ====================
async def start_search(message, user_id):
    profile = get_profile(user_id)
    if not profile:
        await message.answer(
            """<b>❌ Сначала создай анкету!</b>

Нажми 💘 Искать пару"""
        )
        return

    is_premium = check_premium(user_id)
    user = get_user(user_id)

    if not is_premium and user and user[5] >= FREE_PROFILES_PER_DAY:
        await message.answer(
            """<b>⚠️ Достигнут лимит просмотров на сегодня!</b>

Бесплатно можно просмотреть {limit} анкет в день.
💎 Купи Премиум для безлимитного просмотра!""".format(limit=FREE_PROFILES_PER_DAY),
            reply_markup=premium_kb()
        )
        return

    gender_filter = None
    if profile[4] == "male":
        gender_filter = "female"
    elif profile[4] == "female":
        gender_filter = "male"

    profiles = search_profiles(user_id, gender_filter=gender_filter, limit=1)

    if not profiles:
        await message.answer(
            """<b>😔 Пока нет подходящих анкет</b>

Попробуй позже или расширь критерии поиска.""",
            reply_markup=main_menu_kb(is_premium)
        )
        return

    target = profiles[0]
    target_id = target[0]
    target_name = target[1]
    target_age = target[2]
    target_gender = target[3]
    target_city = target[4]
    target_about = target[6]
    target_photo = target[7]

    gender_emoji = "👨" if target_gender == "male" else "👩"

    caption = """<b>{name}</b>, {age} {emoji}
📍 {city}

<b>О себе:</b>
{about}

❤️ Лайкни, если понравился(ась)!""".format(
        name=target_name,
        age=target_age,
        emoji=gender_emoji,
        city=target_city,
        about=target_about
    )

    await message.answer_photo(
        target_photo,
        caption=caption,
        reply_markup=search_action_kb(target_id)
    )


@dp.callback_query(F.data.startswith("like_"))
async def process_like(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_")[1])

    is_premium = check_premium(user_id)
    user = get_user(user_id)

    if not is_premium and user and user[5] >= FREE_LIKES_PER_DAY:
        await callback.answer("⚠️ Лимит лайков на сегодня! Купи Премиум 💎", show_alert=True)
        return

    result = add_like(user_id, target_id)

    if result is None:
        await callback.answer("❌ Вы уже лайкали эту анкету!")
        return

    if result:
        target_profile = get_profile(target_id)
        my_profile = get_profile(user_id)

        if target_profile and my_profile:
            await bot.send_message(
                target_id,
                """<b>💘 У вас взаимная симпатия!</b>

<b>{name}</b> тоже лайкнул(а) тебя!

Начните общаться: @{username}""".format(
                    name=my_profile[1],
                    username=callback.from_user.username or "пользователь"
                )
            )

            await callback.message.answer(
                """<b>🎉 Взаимная симпатия!</b>

<b>{name}</b> тоже лайкнул(а) тебя!

Контакт: @{user_id}""".format(
                    name=target_profile[1],
                    user_id=target_id
                )
            )
    else:
        await callback.answer("❤️ Лайк отправлен!")

    await callback.message.delete()
    await start_search(callback.message, user_id)


@dp.callback_query(F.data.startswith("skip_"))
async def process_skip(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.delete()
    await start_search(callback.message, user_id)


@dp.callback_query(F.data.startswith("report_"))
async def process_report(callback: types.CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target=target_id)
    await callback.message.answer(
        """<b>🚫 Жалоба на пользователя</b>

Опиши причину жалобы (спам, оскорбления, фейк и т.д.):"""
    )
    await state.set_state(ReportState.reason)


@dp.message(ReportState.reason)
async def report_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data["report_target"]
    reason = message.text.strip()

    add_report(message.from_user.id, target_id, reason)

    await bot.send_message(
        ADMIN_ID,
        """<b>🚨 Новая жалоба!</b>

От: {from_user}
На: {to_user}
Причина: {reason}""".format(
            from_user=message.from_user.id,
            to_user=target_id,
            reason=reason
        )
    )

    await message.answer(
        """<b>✅ Жалоба отправлена!</b>

Мы рассмотрим её в ближайшее время.""",
        reply_markup=main_menu_kb(check_premium(message.from_user.id))
    )
    await state.clear()


# ==================== МОЯ АНКЕТА ====================
@dp.message(F.text == "👤 Моя анкета")
async def my_profile(message: types.Message):
    user_id = message.from_user.id
    profile = get_profile(user_id)

    if not profile:
        await message.answer(
            """<b>❌ У тебя ещё нет анкеты!</b>

Нажми 💘 Искать пару, чтобы создать её."""
        )
        return

    gender_display = {"male": "👨 Мужчина", "female": "👩 Женщина"}
    looking_display = {"male": "👨 Мужчин", "female": "👩 Женщин", "all": "💕 Всех"}

    is_premium = check_premium(user_id)
    premium_badge = " ⭐ ПРЕМИУМ" if is_premium else ""

    caption = """<b>📋 Твоя анкета{badge}</b>

<b>Имя:</b> {name}
<b>Возраст:</b> {age} лет
<b>Пол:</b> {gender}
<b>Город:</b> {city}
<b>Ищу:</b> {looking}
<b>О себе:</b> {about}""".format(
        badge=premium_badge,
        name=profile[1],
        age=profile[2],
        gender=gender_display.get(profile[3], profile[3]),
        city=profile[4],
        looking=looking_display.get(profile[5], profile[5]),
        about=profile[6]
    )

    await message.answer_photo(profile[7], caption=caption)


# ==================== ЛАЙКИ ====================
@dp.message(F.text.in_(["❤️ Мои лайки", "❤️ Мои лайки ⭐"]))
async def my_likes(message: types.Message):
    user_id = message.from_user.id
    is_premium = check_premium(user_id)

    mutual = get_mutual_likes(user_id)
    who_liked = get_who_liked_me(user_id)

    text = "<b>❤️ Твои лайки</b>\n\n"

    if mutual:
        text += "<b>💘 Взаимные симпатии (" + str(len(mutual)) + "):</b>\n"
        for like in mutual:
            text += "• " + like[1] + "\n"
        text += "\n"
    else:
        text += "<b>💘 Взаимных симпатий пока нет</b>\n\n"

    if who_liked:
        if is_premium:
            text += "<b>👀 Тебя лайкнули (" + str(len(who_liked)) + "):</b>\n"
            for like in who_liked:
                text += "• " + like[1] + "\n"
        else:
            text += "<b>👀 Тебя лайкнули: " + str(len(who_liked)) + " человек</b>\n"
            text += "💎 Купи Премиум, чтобы увидеть кто именно!\n\n"
    else:
        text += "<b>👀 Тебя пока никто не лайкнул</b>\n"

    await message.answer(text)


# ==================== ПРЕМИУМ ====================
@dp.message(F.text == "💎 Премиум")
async def premium_menu(message: types.Message):
    text = """<b>💎 Премиум подписка LoveSpark</b>

<b>Что даёт Премиум:</b>
✅ Безлимитные лайки
✅ Безлимитный просмотр анкет
✅ Приоритет в поиске
✅ Просмотр кто тебя лайкнул
✅ Значок ⭐ в анкете
✅ Расширенные фильтры поиска

<b>Выбери тариф:</b>"""
    await message.answer(text, reply_markup=premium_kb())


@dp.callback_query(F.data.startswith("premium_"))
async def process_premium(callback: types.CallbackQuery):
    tariff_key = callback.data.replace("premium_", "")
    user_id = callback.from_user.id

    if tariff_key not in PREMIUM_PRICES:
        await callback.answer("❌ Неверный тариф")
        return

    tariff = PREMIUM_PRICES[tariff_key]
    payment_link, label = create_payment_link(user_id, tariff_key)

    if not payment_link:
        await callback.answer("❌ Ошибка создания платежа")
        return

    text = """<b>💎 Оплата Премиума</b>

Тариф: <b>{label}</b>
Стоимость: <b>{price}₽</b>

<b>После оплаты нажми "Проверить оплату"</b>""".format(
        label=tariff['label'],
        price=tariff['price']
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_link)],
        [InlineKeyboardButton(text="🔍 Проверить оплату", callback_data="check_" + label)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_premium")],
    ])

    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("check_"))
async def check_payment_callback(callback: types.CallbackQuery):
    label = callback.data.replace("check_", "")

    if process_payment(label):
        await callback.answer("✅ Оплата прошла успешно! Премиум активирован!")
        await callback.message.edit_text(
            """<b>🎉 Премиум активирован!</b>

Теперь у тебя безлимитные лайки, приоритет в поиске и многое другое!

Нажми 💘 Искать пару, чтобы начать!""",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💘 Искать пару", callback_data="back_main")]
            ])
        )
    else:
        await callback.answer("⏳ Платёж ещё не поступил. Попробуй позже.", show_alert=True)


# ==================== НАСТРОЙКИ ====================
@dp.message(F.text == "⚙️ Настройки")
async def settings_menu(message: types.Message):
    await message.answer("<b>⚙️ Настройки</b>", reply_markup=settings_kb())


@dp.callback_query(F.data == "edit_profile")
async def edit_profile(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        """<b>✏️ Редактирование анкеты</b>

Анкета будет создана заново. Нажми 💘 Искать пару."""
    )
    await state.clear()


@dp.callback_query(F.data == "delete_profile")
async def delete_profile_cmd(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete")],
        [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="back_main")],
    ])
    await callback.message.edit_text(
        """<b>🗑 Удалить анкету?</b>

Все данные будут удалены безвозвратно.""",
        reply_markup=kb
    )


@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    delete_profile(user_id)
    await callback.message.edit_text(
        """<b>✅ Анкета удалена!</b>

Ты можешь создать новую в любой момент через 💘 Искать пару."""
    )


# ==================== СТАТИСТИКА ====================
@dp.message(F.text == "📊 Статистика")
async def stats_menu(message: types.Message):
    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        stats = get_stats()
        text = """<b>📊 Статистика бота (Admin)</b>

👥 Всего пользователей: <b>{users}</b>
✅ Активных анкет: <b>{profiles}</b>
⭐ Премиум пользователей: <b>{premium}</b>
❤️ Всего лайков: <b>{likes}</b>
💰 Общая выручка: <b>{revenue}₽</b>

Выбери действие:""".format(
            users=stats['total_users'],
            profiles=stats['active_profiles'],
            premium=stats['premium_users'],
            likes=stats['total_likes'],
            revenue=stats['total_revenue']
        )
        await message.answer(text, reply_markup=admin_kb())
    else:
        my_profile = get_profile(user_id)
        if not my_profile:
            await message.answer("❌ Сначала создай анкету!")
            return

        mutual = get_mutual_likes(user_id)
        who_liked = get_who_liked_me(user_id)

        text = """<b>📊 Твоя статистика</b>

💘 Взаимных симпатий: <b>{mutual}</b>
👀 Лайков получено: <b>{liked}</b>

Продолжай искать свою любовь! 💕""".format(
            mutual=len(mutual),
            liked=len(who_liked)
        )
        await message.answer(text)


# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    stats = get_stats()
    text = """<b>📊 Детальная статистика</b>

👥 Пользователей: {users}
✅ Анкет: {profiles}
⭐ Премиум: {premium}
❤️ Лайков: {likes}
💰 Выручка: {revenue}₽""".format(
        users=stats['total_users'],
        profiles=stats['active_profiles'],
        premium=stats['premium_users'],
        likes=stats['total_likes'],
        revenue=stats['total_revenue']
    )
    await callback.message.edit_text(text, reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_balance")
async def admin_balance_cmd(callback: types.CallbackQuery):
    balance = get_balance()
    if balance is not None:
        text = "<b>💰 Баланс YooMoney:</b> " + str(balance) + "₽"
    else:
        text = "<b>❌ Не удалось получить баланс</b>"
    await callback.message.edit_text(text, reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery):
    await callback.message.edit_text(
        """<b>📢 Рассылка</b>

Отправь сообщение для рассылки всем пользователям:"""
    )


# ==================== НАВИГАЦИЯ ====================
@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    is_premium = check_premium(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer(
        "<b>💘 Главное меню</b>",
        reply_markup=main_menu_kb(is_premium)
    )


@dp.callback_query(F.data == "back_premium")
async def back_premium(callback: types.CallbackQuery):
    await premium_menu(callback.message)


# ==================== ОБРАБОТКА ТЕКСТА ====================
@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.text not in ["💘 Искать пару", "👤 Моя анкета", "❤️ Мои лайки", 
                            "❤️ Мои лайки ⭐", "💎 Премиум", "⚙️ Настройки", "📊 Статистика"]:
        await message.answer(
            """<b>🤔 Я не понял команду</b>

Используй кнопки меню или /help для справки."""
        )


# ==================== ЗАПУСК ====================
async def main():
    init_db()
    await set_commands()
    logger.info("LoveSpark Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
