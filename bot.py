import asyncio
import os
import sqlite3
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
COIN_RATE = float(os.getenv("COIN_RATE", 0.01))
WITHDRAW_FEE = float(os.getenv("WITHDRAW_FEE", 0.10))
REFERRAL_BONUS = float(os.getenv("REFERRAL_BONUS", 0.10))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('factory_game.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        referred_by INTEGER,
        joined_at TIMESTAMP,
        coins REAL DEFAULT 1000,
        total_earned REAL DEFAULT 0,
        total_taps INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 1000,
        max_energy INTEGER DEFAULT 1000,
        energy_restore_rate INTEGER DEFAULT 1,
        last_energy_update TIMESTAMP,
        is_premium INTEGER DEFAULT 0,
        premium_until TIMESTAMP,
        balance_rub REAL DEFAULT 0,
        last_daily_bonus TIMESTAMP,
        daily_streak INTEGER DEFAULT 0,
        tap_power INTEGER DEFAULT 1,
        auto_tap_rate INTEGER DEFAULT 0,
        last_auto_tap TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_factories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        factory_id INTEGER,
        level INTEGER DEFAULT 1,
        purchased_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS factory_types (
        id INTEGER PRIMARY KEY,
        name TEXT,
        base_production REAL,
        base_price INTEGER,
        max_level INTEGER,
        image TEXT,
        is_premium_only INTEGER DEFAULT 0,
        is_limited INTEGER DEFAULT 0,
        total_limit INTEGER,
        sold_count INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        description TEXT,
        created_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        coins_amount REAL,
        rub_amount REAL,
        status TEXT DEFAULT 'pending',
        payment_details TEXT,
        created_at TIMESTAMP,
        processed_at TIMESTAMP
    )''')
    
    c.execute("SELECT COUNT(*) FROM factory_types")
    if c.fetchone()[0] == 0:
        factories = [
            (1, 'Мини-Фабрика', 10, 500, 10, '🏭', 0, 0, 0),
            (2, 'Завод', 50, 2500, 10, '🏢', 0, 0, 0),
            (3, 'Корпорация', 200, 10000, 10, '🌐', 0, 0, 0),
            (4, 'Космическая станция', 1000, 50000, 5, '🚀', 0, 0, 0),
            (5, 'Кристальная шахта', 5000, 250000, 3, '💎', 1, 0, 0),
            (6, 'Легендарная кузница', 25000, 1000000, 1, '🔥', 1, 1, 100),
        ]
        c.executemany('''INSERT INTO factory_types 
            (id, name, base_production, base_price, max_level, image, is_premium_only, is_limited, total_limit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', factories)
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect('factory_game.db')

# ==================== УТИЛИТЫ ====================
def create_user(user_id: int, username: str, referred_by: int = None):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now()
    c.execute('''INSERT OR IGNORE INTO users 
        (user_id, username, referred_by, joined_at, last_energy_update, last_auto_tap)
        VALUES (?, ?, ?, ?, ?, ?)''', 
        (user_id, username, referred_by, now, now, now))
    conn.commit()
    conn.close()

def update_energy(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT energy, max_energy, energy_restore_rate, last_energy_update FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return 0
    energy, max_energy, rate, last_update = row
    
    now = datetime.now()
    last = datetime.fromisoformat(last_update) if isinstance(last_update, str) else last_update
    minutes_passed = (now - last).total_seconds() / 60
    restored = int(minutes_passed * rate)
    new_energy = min(energy + restored, max_energy)
    
    c.execute("UPDATE users SET energy = ?, last_energy_update = ? WHERE user_id = ?",
              (new_energy, now, user_id))
    conn.commit()
    conn.close()
    return new_energy

def calculate_production(user_id: int) -> float:
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT ft.base_production, uf.level 
                   FROM user_factories uf
                   JOIN factory_types ft ON uf.factory_id = ft.id
                   WHERE uf.user_id = ?''', (user_id,))
    factories = c.fetchall()
    conn.close()
    
    total = 0
    for base_prod, level in factories:
        production = base_prod * level * (1.5 ** (level - 1))
        total += production
    return total

def add_coins(user_id: int, amount: float, description: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?",
              (amount, amount, user_id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, 'earn', amount, description, datetime.now()))
    conn.commit()
    conn.close()

# ==================== КЛАВИАТУРЫ ====================
def main_menu(user_id: int):
    kb = [
        [InlineKeyboardButton(text="👆 ТАПАТЬ", callback_data="tap")],
        [InlineKeyboardButton(text="🏭 Мои фабрики", callback_data="my_factories"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="💎 Премиум", callback_data="premium")],
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="🔑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    referred_by = None
    if message.text and len(message.text.split()) > 1:
        try:
            referred_by = int(message.text.split()[1])
        except:
            pass
    
    create_user(user_id, username, referred_by)
    
    if referred_by and referred_by != user_id:
        add_coins(referred_by, 500, f"Реферальный бонус от @{username}")
        try:
            await bot.send_message(referred_by, f"🎉 У вас новый реферал @{username}! +500 монет")
        except:
            pass
    
    await message.answer(
        "🏭 <b>Добро пожаловать в Фабрику Миллионеров!</b>\n\n"
        "👆 <b>Тапай</b> — зарабатывай монеты\n"
        "🏭 <b>Покупай фабрики</b> — получай пассивный доход\n"
        "💰 <b>Выводи</b> монеты в реальные рубли\n\n"
        "🎁 <b>Бонус новичка:</b> +1000 монет!\n"
        "👥 <b>Пригласи друга</b> — получи 500 монет",
        reply_markup=main_menu(user_id),
        parse_mode="HTML"
    )

# ==================== ТАПАЛКА ====================
@dp.callback_query(F.data == "tap")
async def tap_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    update_energy(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT energy, tap_power, is_premium FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    energy, tap_power, is_premium = row
    
    if energy < tap_power:
        await callback.answer("⚡ Не хватает энергии! Подождите или купите восстановление.", show_alert=True)
        return
    
    bonus = 1.5 if is_premium else 1.0
    earned = int(tap_power * bonus * random.uniform(0.9, 1.1))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET energy = energy - ?, coins = coins + ?, total_taps = total_taps + 1 WHERE user_id = ?",
              (tap_power, earned, user_id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, 'tap', earned, 'Тап', datetime.now()))
    conn.commit()
    
    c.execute("SELECT coins, energy, max_energy FROM users WHERE user_id = ?", (user_id,))
    coins, energy, max_energy = c.fetchone()
    conn.close()
    
    production = calculate_production(user_id)
    
    text = (
        f"👆 <b>ТАПАЛКА</b>\n\n"
        f"💰 Монет: <b>{coins:,.0f}</b>\n"
        f"⚡ Энергия: <b>{energy}/{max_energy}</b>\n"
        f"🏭 Пассивный доход: <b>{production:,.0f}/час</b>\n\n"
        f"👆 Тапайте для заработка!\n"
        f"💡 Купите фабрики для пассивного дохода"
    )
    
    await callback.message.edit_text(text, reply_markup=main_menu(user_id), parse_mode="HTML")
    await callback.answer(f"+{earned} монет!")

# ==================== ФАБРИКИ ====================
@dp.callback_query(F.data == "my_factories")
async def my_factories(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    production = calculate_production(user_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT ft.name, ft.image, uf.level, ft.base_production
                 FROM user_factories uf
                 JOIN factory_types ft ON uf.factory_id = ft.id
                 WHERE uf.user_id = ?''', (user_id,))
    factories = c.fetchall()
    conn.close()
    
    if not factories:
        await callback.message.edit_text(
            "🏭 У вас пока нет фабрик!\n\nКупите их в магазине.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 В магазин", callback_data="shop")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        return
    
    text = f"🏭 <b>Ваши фабрики</b>\nПроизводство: <b>{production:,.0f} монет/час</b>\n\n"
    kb = []
    
    for name, image, level, base in factories:
        prod = base * level * (1.5 ** (level - 1))
        text += f"{image} <b>{name}</b> (ур. {level})\n   └ {prod:,.0f} мон/час\n"
        kb.append([InlineKeyboardButton(text=f"⬆️ Улучшить {name}", callback_data=f"upgrade_{name}")])
    
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ==================== МАГАЗИН ====================
@dp.callback_query(F.data == "shop")
async def shop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))
    is_premium = c.fetchone()[0]
    
    c.execute("SELECT * FROM factory_types")
    factories = c.fetchall()
    conn.close()
    
    text = "🛒 <b>Магазин фабрик</b>\n\n"
    kb = []
    
    for f in factories:
        fid, name, base_prod, price, max_lvl, image, prem_only, is_limited, total_limit, sold = f
        status = ""
        if prem_only and not is_premium:
            status = " 🔒 Только премиум"
        elif is_limited:
            remaining = total_limit - sold
            status = f" ⚡ Осталось: {remaining}"
        
        text += f"{image} <b>{name}</b>{status}\n"
        text += f"   💰 Цена: <b>{price:,.0f}</b> монет\n"
        text += f"   📈 Доход: <b>{base_prod:,.0f}</b> мон/час\n\n"
        
        if prem_only and not is_premium:
            kb.append([InlineKeyboardButton(text=f"🔒 {name}", callback_data="premium_required")])
        elif is_limited and sold >= total_limit:
            kb.append([InlineKeyboardButton(text=f"❌ {name} (распродано)", callback_data="sold_out")])
        else:
            kb.append([InlineKeyboardButton(text=f"💰 Купить {name} ({price:,.0f})", callback_data=f"buy_factory_{fid}")])
    
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_factory_"))
async def buy_factory(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    factory_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    coins = c.fetchone()[0]
    
    c.execute("SELECT * FROM factory_types WHERE id = ?", (factory_id,))
    factory = c.fetchone()
    
    if not factory:
        await callback.answer("Ошибка!", show_alert=True)
        conn.close()
        return
    
    fid, name, base_prod, price, max_lvl, image, prem_only, is_limited, total_limit, sold = factory
    
    if coins < price:
        await callback.answer(f"❌ Недостаточно монет! Нужно: {price:,.0f}", show_alert=True)
        conn.close()
        return
    
    if is_limited and sold >= total_limit:
        await callback.answer("❌ Распродано!", show_alert=True)
        conn.close()
        return
    
    c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, user_id))
    c.execute("INSERT INTO user_factories (user_id, factory_id, level, purchased_at) VALUES (?, ?, 1, ?)",
              (user_id, factory_id, datetime.now()))
    
    if is_limited:
        c.execute("UPDATE factory_types SET sold_count = sold_count + 1 WHERE id = ?", (factory_id,))
    
    c.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, 'spend', -price, f"Покупка {name}", datetime.now()))
    
    conn.commit()
    conn.close()
    
    await callback.answer(f"✅ Куплено: {name}!")
    await shop(callback)

# ==================== БАЛАНС И ВЫВОД ====================
@dp.callback_query(F.data == "balance")
async def balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coins, balance_rub, total_earned FROM users WHERE user_id = ?", (user_id,))
    coins, balance_rub, total_earned = c.fetchone()
    conn.close()
    
    rub_value = coins * COIN_RATE
    
    text = (
        f"💰 <b>Ваш баланс</b>\n\n"
        f"🪙 Монет: <b>{coins:,.0f}</b>\n"
        f"💵 В рублях: <b>{rub_value:,.2f} ₽</b>\n"
        f"💳 На выводе: <b>{balance_rub:,.2f} ₽</b>\n"
        f"📊 Всего заработано: <b>{total_earned:,.0f}</b> монет\n\n"
        f"📉 Курс: <b>100 монет = {100 * COIN_RATE:.2f} ₽</b>\n"
        f"📉 Комиссия вывода: <b>{WITHDRAW_FEE * 100:.0f}%</b>\n\n"
        f"Минимум для вывода: <b>1000 монет (10 ₽)</b>"
    )
    
    kb = [
        [InlineKeyboardButton(text="💳 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    coins = c.fetchone()[0]
    conn.close()
    
    if coins < 1000:
        await callback.answer("❌ Минимум для вывода: 1000 монет!", show_alert=True)
        return
    
    rub = coins * COIN_RATE * (1 - WITHDRAW_FEE)
    
    await callback.message.edit_text(
        f"💳 <b>Заявка на вывод</b>\n\n"
        f"Доступно: <b>{coins:,.0f}</b> монет\n"
        f"К выводу: <b>{rub:,.2f} ₽</b> (комиссия {WITHDRAW_FEE*100:.0f}%)\n\n"
        f"⚠️ Вывод осуществляется вручную администратором.\n"
        f"Отправьте реквизиты (номер карты или кошелёк) одним сообщением:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="balance")]
        ]),
        parse_mode="HTML"
    )
    
    # Сохраняем состояние ожидания реквизитов
    await callback.answer()

# ==================== ПРЕМИУМ ====================
@dp.callback_query(F.data == "premium")
async def premium_info(callback: types.CallbackQuery):
    text = (
        "💎 <b>Премиум подписка</b>\n\n"
        "✅ +50% к доходу фабрик\n"
        "✅ Безлимитная энергия\n"
        "✅ Доступ к эксклюзивным фабрикам\n"
        "✅ x2 скорость восстановления энергии\n"
        "✅ Уникальный значок в профиле\n\n"
        "💰 <b>299 ₽ / 30 дней</b>\n\n"
        "Для покупки премиума напишите администратору."
    )
    
    kb = [
        [InlineKeyboardButton(text="📨 Написать админу", url=f"tg://user?id={ADMIN_ID}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ==================== РЕФЕРАЛЫ ====================
@dp.callback_query(F.data == "referrals")
async def referrals(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    ref_count = c.fetchone()[0]
    c.execute("SELECT total_earned FROM users WHERE user_id = ?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    
    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено: <b>{ref_count}</b>\n"
        f"💰 Бонус за друга: <b>500</b> монет\n"
        f"📊 <b>10%</b> от их заработка\n\n"
        f"💡 Поделитесь ссылкой с друзьями!"
    )
    
    kb = [
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Зарабатывай в Фабрике Миллионеров!")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ==================== ЕЖЕДНЕВНЫЙ БОНУС ====================
@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_daily_bonus, daily_streak, coins FROM users WHERE user_id = ?", (user_id,))
    last_bonus, streak, coins = c.fetchone()
    conn.close()
    
    now = datetime.now()
    last = datetime.fromisoformat(last_bonus) if isinstance(last_bonus, str) and last_bonus else now - timedelta(days=2)
    
    hours_since = (now - last).total_seconds() / 3600
    
    if hours_since < 20:
        wait_hours = int(24 - hours_since)
        await callback.answer(f"⏰ Следующий бонус через {wait_hours}ч!", show_alert=True)
        return
    
    is_streak = hours_since < 48
    if is_streak:
        streak = min(streak + 1, 30)
    else:
        streak = 1
    
    bonus = int(100 * streak * (1 + streak / 10))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ?, daily_streak = ?, last_daily_bonus = ? WHERE user_id = ?",
              (bonus, streak, now, user_id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, 'bonus', bonus, f'Ежедневный бонус (streak {streak})', now))
    conn.commit()
    conn.close()
    
    text = (
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"💰 Получено: <b>{bonus:,.0f}</b> монет\n"
        f"🔥 Streak: <b>{streak}</b> дней\n\n"
        f"📈 Завтра: <b>{int(100 * (streak + 1) * (1 + (streak + 1) / 10)):,.0f}</b> монет"
    )
    
    kb = [[InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer(f"+{bonus} монет!")

# ==================== СТАТИСТИКА ====================
@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT total_taps, total_earned, daily_streak FROM users WHERE user_id = ?", (user_id,))
    taps, earned, streak = c.fetchone()
    
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    refs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_factories WHERE user_id = ?", (user_id,))
    factories = c.fetchone()[0]
    
    production = calculate_production(user_id)
    
    c.execute("SELECT username, total_earned FROM users ORDER BY total_earned DESC LIMIT 5")
    top = c.fetchall()
    conn.close()
    
    text = (
        f"📊 <b>Ваша статистика</b>\n\n"
        f"👆 Всего тапов: <b>{taps:,.0f}</b>\n"
        f"🏭 Фабрик: <b>{factories}</b>\n"
        f"📈 Пассивный доход: <b>{production:,.0f}/час</b>\n"
        f"👥 Рефералов: <b>{refs}</b>\n"
        f"🔥 Streak: <b>{streak}</b> дней\n"
        f"💰 Всего заработано: <b>{earned:,.0f}</b> монет\n\n"
        f"🏆 <b>Топ игроков:</b>\n"
    )
    
    for i, (name, score) in enumerate(top, 1):
        name = name or "Аноним"
        text += f"{i}. {name}: {score:,.0f} монет\n"
    
    kb = [[InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

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
    c.execute("SELECT SUM(coins) FROM users")
    total_coins = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
    pending_withdrawals = c.fetchone()[0]
    conn.close()
    
    text = (
        f"🔑 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"🪙 Всего монет в игре: <b>{total_coins:,.0f}</b>\n"
        f"💳 Заявок на вывод: <b>{pending_withdrawals}</b>\n\n"
        f"Выберите действие:"
    )
    
    kb = [
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💳 Заявки на вывод", callback_data="admin_withdrawals")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_withdrawals")
async def admin_withdrawals(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT w.id, w.user_id, w.coins_amount, w.rub_amount, w.payment_details, w.created_at, u.username
                 FROM withdrawals w
                 JOIN users u ON w.user_id = u.user_id
                 WHERE w.status = 'pending'
                 ORDER BY w.created_at''')
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await callback.message.edit_text(
            "Нет заявок на вывод.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
            ])
        )
        await callback.answer()
        return
    
    for row in rows:
        wid, uid, coins, rub, details, created, username = row
        text = (
            f"💳 <b>Заявка #{wid}</b>\n"
            f"👤 Пользователь: @{username or uid}\n"
            f"🪙 Монет: <b>{coins:,.0f}</b>\n"
            f"💵 К выводу: <b>{rub:.2f} ₽</b>\n"
            f"📋 Реквизиты: <code>{details}</code>\n"
            f"🕐 Создана: {created}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выплачено", callback_data=f"withdraw_approve_{wid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"withdraw_reject_{wid}")
            ]
        ])
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    
    await callback.message.answer(
        "Все заявки выше.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("withdraw_approve_"))
async def approve_withdrawal(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    wid = int(callback.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE withdrawals SET status = 'completed', processed_at = ? WHERE id = ?",
              (datetime.now(), wid))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text("✅ Заявка помечена как выплачена.")
    await callback.answer("Выплачено!")

@dp.callback_query(F.data.startswith("withdraw_reject_"))
async def reject_withdrawal(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    wid = int(callback.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT user_id, coins_amount FROM withdrawals WHERE id = ?", (wid,))
    row = c.fetchone()
    if row:
        uid, coins = row
        c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (coins, uid))
        c.execute("UPDATE withdrawals SET status = 'rejected', processed_at = ? WHERE id = ?",
                  (datetime.now(), wid))
        conn.commit()
        try:
            await bot.send_message(uid, f"❌ Ваша заявка на вывод #{wid} отклонена. Монеты возвращены.")
        except:
            pass
    
    conn.close()
    await callback.message.edit_text("❌ Заявка отклонена, монеты возвращены пользователю.")
    await callback.answer("Отклонено!")

# ==================== ГЛАВНОЕ МЕНЮ ====================
@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🏭 <b>Фабрика Миллионеров</b>\n\nГлавное меню:",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode="HTML"
    )
    await callback.answer()

# ==================== ОБРАБОТКА РЕКВИЗИТОВ ДЛЯ ВЫВОДА ====================
@dp.message(F.text)
async def handle_withdraw_details(message: types.Message):
    user_id = message.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    if not row or row[0] < 1000:
        conn.close()
        return
    
    coins = row[0]
    rub = coins * COIN_RATE * (1 - WITHDRAW_FEE)
    details = message.text.strip()
    
    if len(details) < 5:
        await message.answer("❌ Введите корректные реквизиты.")
        conn.close()
        return
    
    c.execute("UPDATE users SET coins = 0, balance_rub = balance_rub + ? WHERE user_id = ?",
              (rub, user_id))
    c.execute('''INSERT INTO withdrawals (user_id, coins_amount, rub_amount, payment_details, status, created_at)
                 VALUES (?, ?, ?, ?, 'pending', ?)''',
              (user_id, coins, rub, details, datetime.now()))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ <b>Заявка на вывод создана!</b>\n\n"
        f"🪙 Списано: <b>{coins:,.0f}</b> монет\n"
        f"💵 К выводу: <b>{rub:.2f} ₽</b>\n"
        f"📋 Реквизиты: <code>{details}</code>\n\n"
        f"⏰ Обработка в течение 24 часов.",
        parse_mode="HTML"
    )
    
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💳 <b>Новая заявка на вывод!</b>\n\n"
            f"👤 Пользователь: @{message.from_user.username or user_id}\n"
            f"🪙 Монет: <b>{coins:,.0f}</b>\n"
            f"💵 Сумма: <b>{rub:.2f} ₽</b>\n"
            f"📋 Реквизиты: <code>{details}</code>",
            parse_mode="HTML"
        )
    except:
        pass

# ==================== ПАССИВНЫЙ ДОХОД ====================
async def passive_income_task():
    while True:
        await asyncio.sleep(600)
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        
        for (user_id,) in users:
            production = calculate_production(user_id)
            if production > 0:
                earned = production / 6
                c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (earned, user_id))
                c.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
                          (user_id, 'passive', earned, 'Пассивный доход', datetime.now()))
        
        conn.commit()
        conn.close()

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    asyncio.create_task(passive_income_task())
    print("🏭 Фабрика Миллионеров запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
