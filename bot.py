#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LoveSpark - Bot for dating across Russia, DNR and LNR
Version: 1.0.0
Stack: aiogram 3.x + sqlite3
"""

import asyncio
import logging
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, List
from contextlib import closing

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8934692936:AAHO1WgDH6-dyyxnctpRRpmIcfILSG-8mWM"
PAYMENT_PROVIDER_TOKEN = "YOUR_PAYMENT_TOKEN_HERE"
ADMIN_ID = 5494544187

DAILY_FREE_LIKES = 10

PREMIUM_PRICES = {
    "week": {"label": "Premium 1 week", "price": 19900, "days": 7},
    "month": {"label": "Premium 1 month", "price": 49900, "days": 30},
    "quarter": {"label": "Premium 3 months", "price": 119900, "days": 90},
    "year": {"label": "Premium 1 year", "price": 299900, "days": 365},
}

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
DB_NAME = "lovespark.db"


def init_db():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                daily_likes INTEGER DEFAULT 10,
                last_like_reset TEXT,
                superlikes INTEGER DEFAULT 0,
                undos INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                city TEXT NOT NULL,
                bio TEXT,
                photo_id TEXT,
                additional_photos TEXT,
                looking_for TEXT NOT NULL,
                interests TEXT,
                goal TEXT DEFAULT 'all',
                height INTEGER,
                is_active INTEGER DEFAULT 1,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                is_superlike INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_user_id, to_user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user1_id, user2_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                plan TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS viewed_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                viewer_id INTEGER NOT NULL,
                viewed_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(viewer_id, viewed_id)
            )
        """)

        conn.commit()
        logger.info("Database initialized")


def get_db():
    return sqlite3.connect(DB_NAME)


def generate_ref_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()

        if not user:
            ref_code = generate_ref_code()
            cursor.execute(
                "INSERT INTO users (telegram_id, username, first_name, referral_code, last_like_reset) VALUES (?, ?, ?, ?, ?)",
                (telegram_id, username, first_name, ref_code, datetime.now().isoformat())
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

        return dict(user)


def get_user(telegram_id: int) -> Optional[dict]:
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_profile(user_id: int) -> Optional[dict]:
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def save_profile(user_id: int, data: dict):
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO profiles 
            (user_id, name, age, gender, city, bio, photo_id, looking_for, is_active, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            user_id, data.get("name"), data.get("age"), data.get("gender"),
            data.get("city"), data.get("bio"), data.get("photo_id"),
            data.get("looking_for"), datetime.now().isoformat()
        ))
        conn.commit()


def is_premium(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user["is_premium"]:
        return False
    if user["premium_until"]:
        until = datetime.fromisoformat(user["premium_until"])
        if until > datetime.now():
            return True
    return False


def reset_daily_likes_if_needed(user_id: int):
    user = get_user(user_id)
    if not user:
        return
    last_reset = datetime.fromisoformat(user["last_like_reset"]) if user["last_like_reset"] else datetime.min
    if last_reset.date() < datetime.now().date():
        with closing(get_db()) as conn:
            cursor = conn.cursor()
            likes = 999 if is_premium(user_id) else DAILY_FREE_LIKES
            cursor.execute(
                "UPDATE users SET daily_likes = ?, last_like_reset = ? WHERE telegram_id = ?",
                (likes, datetime.now().isoformat(), user_id)
            )
            conn.commit()


def decrement_likes(user_id: int) -> bool:
    reset_daily_likes_if_needed(user_id)
    if is_premium(user_id):
        return True
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT daily_likes FROM users WHERE telegram_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row[0] > 0:
            cursor.execute("UPDATE users SET daily_likes = daily_likes - 1 WHERE telegram_id = ?", (user_id,))
            conn.commit()
            return True
        return False


def get_remaining_likes(user_id: int) -> int:
    reset_daily_likes_if_needed(user_id)
    if is_premium(user_id):
        return 999
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT daily_likes FROM users WHERE telegram_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0


def add_like(from_id: int, to_id: int, superlike: bool = False) -> bool:
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO likes (from_user_id, to_user_id, is_superlike) VALUES (?, ?, ?)",
                (from_id, to_id, 1 if superlike else 0)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

        cursor.execute(
            "SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?",
            (to_id, from_id)
        )
        mutual = cursor.fetchone()

        if mutual:
            try:
                cursor.execute(
                    "INSERT INTO matches (user1_id, user2_id) VALUES (?, ?)",
                    (min(from_id, to_id), max(from_id, to_id))
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
        return False


def mark_viewed(viewer_id: int, viewed_id: int, action: str):
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO viewed_profiles (viewer_id, viewed_id, action) VALUES (?, ?, ?)",
                (viewer_id, viewed_id, action)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass


def get_next_profile(viewer_id: int) -> Optional[dict]:
    my_profile = get_profile(viewer_id)
    if not my_profile:
        return None

    looking_for = my_profile["looking_for"]
    my_gender = my_profile["gender"]

    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT viewed_id FROM viewed_profiles WHERE viewer_id = ?", (viewer_id,))
        viewed = [row[0] for row in cursor.fetchall()]

        if viewed:
            placeholders = ",".join(["?"] * len(viewed))
            query = f"""
                SELECT p.*, u.is_premium FROM profiles p
                JOIN users u ON p.user_id = u.telegram_id
                WHERE p.user_id != ? 
                AND p.is_active = 1 
                AND u.is_banned = 0
                AND p.user_id NOT IN ({placeholders})
            """
            params = [viewer_id] + viewed
        else:
            query = """
                SELECT p.*, u.is_premium FROM profiles p
                JOIN users u ON p.user_id = u.telegram_id
                WHERE p.user_id != ? 
                AND p.is_active = 1 
                AND u.is_banned = 0
            """
            params = [viewer_id]

        if looking_for != "all":
            query += " AND p.gender = ?"
            params.append(looking_for)

        query += " AND (p.looking_for = ? OR p.looking_for = 'all')"
        params.append(my_gender)

        query += " ORDER BY u.is_premium DESC, p.last_active DESC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def get_likes_to_user(user_id: int) -> List[dict]:
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.*, p.name, p.age, p.city, p.photo_id, p.gender 
            FROM likes l
            JOIN profiles p ON l.from_user_id = p.user_id
            WHERE l.to_user_id = ?
            AND NOT EXISTS (
                SELECT 1 FROM matches 
                WHERE (user1_id = l.from_user_id AND user2_id = l.to_user_id)
                OR (user1_id = l.to_user_id AND user2_id = l.from_user_id)
            )
            ORDER BY l.created_at DESC
        """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_matches(user_id: int) -> List[dict]:
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.*, p.name, p.age, p.city, p.photo_id, p.gender, p.bio,
                   CASE WHEN m.user1_id = ? THEN m.user2_id ELSE m.user1_id END as partner_id
            FROM matches m
            JOIN profiles p ON (CASE WHEN m.user1_id = ? THEN m.user2_id ELSE m.user1_id END) = p.user_id
            WHERE m.user1_id = ? OR m.user2_id = ?
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id, user_id))
        return [dict(row) for row in cursor.fetchall()]


def activate_premium(user_id: int, plan: str):
    info = PREMIUM_PRICES[plan]
    until = datetime.now() + timedelta(days=info["days"])
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_premium = 1, premium_until = ?, daily_likes = 999 WHERE telegram_id = ?",
            (until.isoformat(), user_id)
        )
        conn.commit()


def update_profile_activity(user_id: int):
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE profiles SET last_active = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()


# ==================== KEYBOARDS ====================
def main_menu_kb(is_premium: bool = False):
    buttons = [
        [KeyboardButton(text="Browse profiles")],
        [KeyboardButton(text="Who liked me"), KeyboardButton(text="My matches")],
        [KeyboardButton(text="My profile"), KeyboardButton(text="Settings")],
    ]
    if not is_premium:
        buttons.append([KeyboardButton(text="Premium")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def profile_action_kb(target_id: int):
    buttons = [
        [
            InlineKeyboardButton(text="Skip", callback_data=f"dislike:{target_id}"),
            InlineKeyboardButton(text="Like", callback_data=f"like:{target_id}"),
        ],
        [
            InlineKeyboardButton(text="Super-like", callback_data=f"superlike:{target_id}"),
        ],
        [
            InlineKeyboardButton(text="Report", callback_data=f"report:{target_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def premium_kb():
    buttons = []
    for key, info in PREMIUM_PRICES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{info['label']} - {info['price']//100} RUB",
            callback_data=f"buy:{key}"
        )])
    buttons.append([InlineKeyboardButton(text="Back", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Edit profile", callback_data="edit_profile")],
        [InlineKeyboardButton(text="Toggle active", callback_data="toggle_active")],
        [InlineKeyboardButton(text="Delete profile", callback_data="delete_profile")],
        [InlineKeyboardButton(text="Back", callback_data="back_main")],
    ])


def gender_kb(prefix: str = "gender"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Male", callback_data=f"{prefix}:male"),
            InlineKeyboardButton(text="Female", callback_data=f"{prefix}:female"),
        ]
    ])


def looking_for_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Males", callback_data="look:male"),
            InlineKeyboardButton(text="Females", callback_data="look:female"),
        ],
        [InlineKeyboardButton(text="Everyone", callback_data="look:all")],
    ])


def city_kb():
    cities = ["Moscow", "St. Petersburg", "Donetsk", "Lugansk", "Krasnodar", "Yekaterinburg", "Other"]
    buttons = []
    row = []
    for i, city in enumerate(cities):
        row.append(InlineKeyboardButton(text=city, callback_data=f"city:{city}"))
        if (i + 1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== FSM STATES ====================
class RegStates(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    city_manual = State()
    looking_for = State()
    photo = State()
    bio = State()
    confirm = State()


class EditStates(StatesGroup):
    field = State()
    value = State()


# ==================== ROUTER ====================
router = Router()


# ==================== HANDLERS ====================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    profile = get_profile(message.from_user.id)

    if profile:
        likes_remaining = get_remaining_likes(message.from_user.id)
        premium_status = "Premium active!" if is_premium(message.from_user.id) else "Get Premium for unlimited!"
        text = (
            "Welcome back to LoveSpark!\n\n"
            + "Your profile is active\n"
            + f"Likes remaining today: {likes_remaining}\n"
            + f"{premium_status}\n\n"
            + "Choose action below:"
        )
        await message.answer(
            text,
            reply_markup=main_menu_kb(is_premium(message.from_user.id))
        )
    else:
        text = (
            "Welcome to LoveSpark!\n\n"
            + "I am the smartest dating bot for Russia, DNR and LNR.\n"
            + "Find your spark right now!\n\n"
            + "Let's create your profile. What is your name?"
        )
        await message.answer(text)
        await state.set_state(RegStates.name)


# ----- REGISTRATION -----
@router.message(RegStates.name)
async def reg_name(message: Message, state: FSMContext):
    if len(message.text) > 50:
        await message.answer("Name too long! Maximum 50 characters.")
        return
    await state.update_data(name=message.text)
    await message.answer("How old are you? (18-80)")
    await state.set_state(RegStates.age)


@router.message(RegStates.age)
async def reg_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Please enter a number.")
        return
    age = int(message.text)
    if not (18 <= age <= 80):
        await message.answer("Age must be between 18 and 80.")
        return
    await state.update_data(age=age)
    await message.answer("Your gender?", reply_markup=gender_kb("gender"))
    await state.set_state(RegStates.gender)


@router.callback_query(RegStates.gender, F.data.startswith("gender:"))
async def reg_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    await state.update_data(gender=gender)
    await callback.message.edit_text("Select your city:", reply_markup=city_kb())
    await state.set_state(RegStates.city)


@router.callback_query(RegStates.city, F.data.startswith("city:"))
async def reg_city(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(":")[1]
    if city == "Other":
        await callback.message.edit_text("Type your city name:")
        await state.set_state(RegStates.city_manual)
        return
    await state.update_data(city=city)
    await callback.message.edit_text("Who are you looking for?", reply_markup=looking_for_kb())
    await state.set_state(RegStates.looking_for)


@router.message(RegStates.city_manual)
async def reg_city_manual(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Who are you looking for?", reply_markup=looking_for_kb())
    await state.set_state(RegStates.looking_for)


@router.callback_query(RegStates.looking_for, F.data.startswith("look:"))
async def reg_looking_for(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.split(":")[1]
    await state.update_data(looking_for=looking)
    await callback.message.edit_text("Send your best photo:")
    await state.set_state(RegStates.photo)


@router.message(RegStates.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("Tell about yourself (hobbies, interests, goals) - up to 300 characters:")
    await state.set_state(RegStates.bio)


@router.message(RegStates.photo)
async def reg_photo_invalid(message: Message, state: FSMContext):
    await message.answer("Please send a photo!")


@router.message(RegStates.bio)
async def reg_bio(message: Message, state: FSMContext):
    if len(message.text) > 300:
        await message.answer("Too long! Maximum 300 characters.")
        return
    await state.update_data(bio=message.text)
    data = await state.get_data()

    gender_emoji = "Male" if data["gender"] == "male" else "Female"
    looking_emoji = {"male": "Males", "female": "Females", "all": "Everyone"}[data["looking_for"]]

    preview = (
        "Your profile:\n\n"
        + f"{gender_emoji} {data['name']}, {data['age']} years\n"
        + f"Location: {data['city']}\n"
        + f"Bio: {data['bio']}\n\n"
        + f"Looking for: {looking_emoji}\n\n"
        + "Is everything correct?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, correct", callback_data="confirm:yes")],
        [InlineKeyboardButton(text="Start over", callback_data="confirm:no")],
    ])

    await message.answer_photo(
        photo=data["photo_id"],
        caption=preview,
        reply_markup=kb
    )
    await state.set_state(RegStates.confirm)


@router.callback_query(RegStates.confirm, F.data.startswith("confirm:"))
async def reg_confirm(callback: CallbackQuery, state: FSMContext):
    answer = callback.data.split(":")[1]
    if answer == "yes":
        data = await state.get_data()
        save_profile(callback.from_user.id, data)
        await callback.message.delete()
        text = (
            "Profile created!\n\n"
            + "Now you can:\n"
            + "- Browse profiles\n"
            + "- Send likes\n"
            + "- Buy Premium for unlimited access\n\n"
            + "Good luck in your search!"
        )
        await callback.message.answer(
            text,
            reply_markup=main_menu_kb()
        )
        await state.clear()
    else:
        await callback.message.delete()
        await callback.message.answer("Let's create your profile again. What is your name?")
        await state.set_state(RegStates.name)


# ----- BROWSE PROFILES -----
async def show_next_profile(message: Message, user_id: int):
    profile = get_next_profile(user_id)
    if not profile:
        text = (
            "No new profiles yet.\n"
            + "Try again later or change filters in settings."
        )
        await message.answer(
            text,
            reply_markup=main_menu_kb(is_premium(user_id))
        )
        return

    update_profile_activity(user_id)

    gender_emoji = "Male" if profile["gender"] == "male" else "Female"
    premium_badge = " [PREMIUM]" if profile["is_premium"] else ""
    likes_remaining = get_remaining_likes(user_id)

    text = (
        f"{gender_emoji} {profile['name']}, {profile['age']} years{premium_badge}\n"
        + f"Location: {profile['city']}\n"
        + f"Bio: {profile['bio'] or 'No description'}\n\n"
        + f"Likes remaining: {likes_remaining}"
    )

    kb = profile_action_kb(profile["user_id"])

    await message.answer_photo(
        photo=profile["photo_id"],
        caption=text,
        reply_markup=kb
    )


@router.message(F.text == "Browse profiles")
async def browse_profiles(message: Message, state: FSMContext):
    await state.clear()
    profile = get_profile(message.from_user.id)
    if not profile:
        await message.answer(
            "Create your profile first! Type /start",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/start")]],
                resize_keyboard=True
            )
        )
        return
    await show_next_profile(message, message.from_user.id)


@router.callback_query(F.data.startswith("dislike:"))
async def dislike_profile(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    mark_viewed(callback.from_user.id, target_id, "dislike")
    await callback.answer("Skipped")
    await callback.message.delete()
    await show_next_profile(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("like:"))
async def like_profile(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    if not decrement_likes(user_id):
        await callback.answer(
            "Like limit reached! Get Premium for unlimited.",
            show_alert=True
        )
        return

    mark_viewed(user_id, target_id, "like")
    is_match = add_like(user_id, target_id)

    if is_match:
        await callback.answer("MATCH!", show_alert=True)
        await callback.message.delete()

        my_profile = get_profile(user_id)
        target_profile = get_profile(target_id)

        await callback.message.answer(
            f"You have a match with {target_profile['name']}!\n\n"
            + "Start chatting!"
        )

        try:
            await callback.bot.send_message(
                target_id,
                f"You have a match with {my_profile['name']}!\n\n"
                + "Someone just liked you back! Check the bot!"
            )
        except Exception:
            pass
    else:
        await callback.answer("Like sent!")
        await callback.message.delete()

    await show_next_profile(callback.message, user_id)


@router.callback_query(F.data.startswith("superlike:"))
async def superlike_profile(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    if not is_premium(user_id):
        await callback.answer(
            "Super-like is Premium only!",
            show_alert=True
        )
        return

    mark_viewed(user_id, target_id, "superlike")
    is_match = add_like(user_id, target_id, superlike=True)

    try:
        my_profile = get_profile(user_id)
        await callback.bot.send_message(
            target_id,
            f"Super-like!\n\n"
            + f"{my_profile['name']} sent you a super-like!\n"
            + "They are definitely interested - check the bot!"
        )
    except Exception:
        pass

    if is_match:
        await callback.answer("MATCH + SUPER-LIKE!", show_alert=True)
    else:
        await callback.answer("Super-like sent!", show_alert=True)

    await callback.message.delete()
    await show_next_profile(callback.message, user_id)


@router.callback_query(F.data.startswith("report:"))
async def report_profile(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    await callback.answer("Report sent to moderator", show_alert=True)
    await callback.message.delete()
    await show_next_profile(callback.message, callback.from_user.id)


# ----- WHO LIKED ME -----
@router.message(F.text == "Who liked me")
async def who_liked(message: Message):
    if not is_premium(message.from_user.id):
        text = (
            "Viewing likes is a Premium feature.\n\n"
            + "Find out who liked you and start chatting first!\n"
            + "Without Premium you only see likes in mutual matches."
        )
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Buy Premium", callback_data="premium")]
            ])
        )
        return

    likes = get_likes_to_user(message.from_user.id)
    if not likes:
        text = (
            "No one liked you yet.\n"
            + "Like others - and they will notice you!"
        )
        await message.answer(
            text,
            reply_markup=main_menu_kb(is_premium=True)
        )
        return

    await message.answer(f"People who liked you ({len(likes)}):")

    for like in likes[:5]:
        gender_emoji = "Male" if like.get('gender') == 'male' else "Female"
        text = (
            f"{gender_emoji} {like['name']}, {like['age']} years\n"
            + f"Location: {like['city']}\n"
            + f"{'Super-like!' if like['is_superlike'] else 'Regular like'}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Like back", callback_data=f"like_back:{like['from_user_id']}")],
            [InlineKeyboardButton(text="Skip", callback_data=f"dislike_back:{like['from_user_id']}")],
        ])

        if like.get("photo_id"):
            await message.answer_photo(photo=like["photo_id"], caption=text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("like_back:"))
async def like_back(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    is_match = add_like(callback.from_user.id, target_id)

    if is_match:
        await callback.answer("MATCH!", show_alert=True)
        my_profile = get_profile(callback.from_user.id)
        await callback.bot.send_message(
            target_id,
            f"Match with {my_profile['name']}!\n\n"
            + "You liked each other! Start chatting!"
        )
    else:
        await callback.answer("Like sent!")

    await callback.message.delete()


@router.callback_query(F.data.startswith("dislike_back:"))
async def dislike_back(callback: CallbackQuery):
    await callback.answer("Skipped")
    await callback.message.delete()


# ----- MATCHES -----
@router.message(F.text == "My matches")
async def my_matches(message: Message):
    matches = get_matches(message.from_user.id)
    if not matches:
        text = (
            "No matches yet.\n"
            + "Send more likes - someone will respond!"
        )
        await message.answer(
            text,
            reply_markup=main_menu_kb(is_premium(message.from_user.id))
        )
        return

    await message.answer(f"Your matches ({len(matches)}):")

    for match in matches:
        gender_emoji = "Male" if match.get('gender') == 'male' else "Female"
        text = (
            f"{gender_emoji} {match['name']}, {match['age']} years\n"
            + f"Location: {match['city']}\n"
            + f"Bio: {match['bio'] or 'No description'}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Chat", url=f"tg://user?id={match['partner_id']}")],
        ])

        if match.get("photo_id"):
            await message.answer_photo(photo=match["photo_id"], caption=text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)


# ----- PREMIUM -----
@router.message(F.text == "Premium")
@router.callback_query(F.data == "premium")
async def show_premium(event: Message | CallbackQuery):
    text = (
        "LoveSpark Premium\n\n"
        + "Unlock all features:\n"
        + "- Unlimited likes\n"
        + "- Super-likes\n"
        + "- View who liked you\n"
        + "- Priority in search\n"
        + "- Extended filters\n"
        + "- Undo dislikes\n"
        + "- Invisible mode\n"
        + "- No ads\n"
        + "- VIP badge\n\n"
        + "Choose your plan:"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=premium_kb())
    else:
        await event.answer(text, reply_markup=premium_kb())


@router.callback_query(F.data.startswith("buy:"))
async def process_buy(callback: CallbackQuery):
    plan = callback.data.split(":")[1]
    info = PREMIUM_PRICES[plan]

    await callback.message.answer_invoice(
        title=info["label"],
        description=f"Premium access for {info['days']} days",
        payload=f"premium_{plan}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=info["label"], amount=info["price"])],
        start_parameter="premium"
    )


@router.pre_checkout_query()
async def precheckout_handler(pre_checkout: PreCheckoutQuery):
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    plan = payload.replace("premium_", "")

    if plan in PREMIUM_PRICES:
        activate_premium(message.from_user.id, plan)
        text = (
            "Payment successful!\n\n"
            + f"Premium activated for {PREMIUM_PRICES[plan]['days']} days!\n"
            + "Enjoy unlimited likes and all premium features!"
        )
        await message.answer(
            text,
            reply_markup=main_menu_kb(is_premium=True)
        )


# ----- MY PROFILE -----
@router.message(F.text == "My profile")
async def my_profile(message: Message):
    profile = get_profile(message.from_user.id)
    if not profile:
        await message.answer("You do not have a profile yet. Type /start")
        return

    gender_emoji = "Male" if profile["gender"] == "male" else "Female"
    premium_badge = " [PREMIUM]" if is_premium(message.from_user.id) else ""
    status = "Active" if profile["is_active"] else "Hidden"
    likes_remaining = get_remaining_likes(message.from_user.id)

    text = (
        f"{gender_emoji} {profile['name']}, {profile['age']} years{premium_badge}\n"
        + f"Location: {profile['city']}\n"
        + f"Bio: {profile['bio'] or 'No description'}\n"
        + f"Looking for: {profile['looking_for']}\n"
        + f"Status: {status}\n"
        + f"Likes today: {likes_remaining}"
    )

    await message.answer_photo(
        photo=profile["photo_id"],
        caption=text,
        reply_markup=settings_kb()
    )


# ----- SETTINGS -----
@router.message(F.text == "Settings")
async def settings(message: Message):
    await message.answer("Settings", reply_markup=settings_kb())


@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "What do you want to change?\n\n"
        + "1. Name\n"
        + "2. Age\n"
        + "3. City\n"
        + "4. About me\n"
        + "5. Photo\n"
        + "6. Looking for\n\n"
        + "Type the number (1-6):"
    )
    await state.set_state(EditStates.field)


@router.message(EditStates.field)
async def edit_field(message: Message, state: FSMContext):
    field_map = {
        "1": "name", "2": "age", "3": "city", "4": "bio", "5": "photo", "6": "looking_for"
    }
    choice = message.text.strip()
    if choice not in field_map:
        await message.answer("Enter a number from 1 to 6:")
        return

    field = field_map[choice]
    await state.update_data(edit_field=field)

    prompts = {
        "name": "Enter new name:",
        "age": "Enter new age:",
        "city": "Enter new city:",
        "bio": "Enter new description (up to 300 characters):",
        "photo": "Send new photo:",
        "looking_for": "Who are you looking for? (male/female/all)"
    }

    await message.answer(prompts[field])
    await state.set_state(EditStates.value)


@router.message(EditStates.value)
async def edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["edit_field"]

    with closing(get_db()) as conn:
        cursor = conn.cursor()

        if field == "photo":
            if not message.photo:
                await message.answer("Send a photo!")
                return
            value = message.photo[-1].file_id
        elif field == "age":
            if not message.text.isdigit():
                await message.answer("Enter a number!")
                return
            value = int(message.text)
        elif field == "looking_for":
            mapping = {"male": "male", "female": "female", "all": "all"}
            value = mapping.get(message.text.lower())
            if not value:
                await message.answer("Type: male, female or all")
                return
        else:
            value = message.text

        cursor.execute(f"UPDATE profiles SET {field} = ? WHERE user_id = ?", (value, message.from_user.id))
        conn.commit()

    await message.answer("Changes saved!", reply_markup=main_menu_kb(is_premium(message.from_user.id)))
    await state.clear()


@router.callback_query(F.data == "toggle_active")
async def toggle_active(callback: CallbackQuery):
    profile = get_profile(callback.from_user.id)
    new_status = 0 if profile["is_active"] else 1

    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE profiles SET is_active = ? WHERE user_id = ?", (new_status, callback.from_user.id))
        conn.commit()

    status_text = "Active" if new_status else "Hidden"
    await callback.answer(f"Profile is now {status_text}", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data == "delete_profile")
async def delete_profile(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, delete", callback_data="confirm_delete")],
        [InlineKeyboardButton(text="Cancel", callback_data="back_main")],
    ])
    await callback.message.edit_text(
        "Are you sure you want to delete your profile?\n\n"
        + "All data, likes and matches will be permanently deleted!",
        reply_markup=kb
    )


@router.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery):
    user_id = callback.from_user.id
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM likes WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id))
        cursor.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
        cursor.execute("DELETE FROM viewed_profiles WHERE viewer_id = ? OR viewed_id = ?", (user_id, user_id))
        conn.commit()

    await callback.message.edit_text(
        "Profile deleted.\n\n"
        + "If you want to come back - type /start",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Start over", callback_data="restart")]
        ])
    )


@router.callback_query(F.data == "restart")
async def restart(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await cmd_start(callback.message, state)


@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Main menu:",
        reply_markup=main_menu_kb(is_premium(callback.from_user.id))
    )


# ----- COMMANDS -----
@router.message(Command("profile"))
async def cmd_profile(message: Message):
    await my_profile(message)


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    await browse_profiles(message, state)


@router.message(Command("likes"))
async def cmd_likes(message: Message):
    await who_liked(message)


@router.message(Command("premium"))
async def cmd_premium(message: Message):
    await show_premium(message)


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await settings(message)


@router.message(Command("support"))
async def cmd_support(message: Message):
    text = (
        "LoveSpark Support\n\n"
        + "If you have issues with the bot:\n"
        + "- Profile not showing\n"
        + "- Payment error\n"
        + "- Report a user\n\n"
        + "Contact us: @support_lovespark"
    )
    await message.answer(
        text,
        reply_markup=main_menu_kb(is_premium(message.from_user.id))
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    with closing(get_db()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM profiles")
        profiles_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM matches")
        matches_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium_count = cursor.fetchone()[0]

    text = (
        f"LoveSpark Statistics\n\n"
        + f"Users: {users_count}\n"
        + f"Profiles: {profiles_count}\n"
        + f"Matches: {matches_count}\n"
        + f"Premium: {premium_count}"
    )
    await message.answer(text)


# ----- UNKNOWN MESSAGE -----
@router.message()
async def unknown_message(message: Message):
    await message.answer(
        "I do not understand this command. Use the menu below:",
        reply_markup=main_menu_kb(is_premium(message.from_user.id))
    )


# ==================== MAIN ====================
async def main():
    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Start / Restart"),
        BotCommand(command="profile", description="My profile"),
        BotCommand(command="search", description="Browse profiles"),
        BotCommand(command="likes", description="Who liked me"),
        BotCommand(command="premium", description="Premium access"),
        BotCommand(command="settings", description="Settings"),
        BotCommand(command="support", description="Support"),
    ])

    logger.info("LoveSpark bot started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
