import asyncio
import os
import sqlite3
import httpx
import random
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")
MODEL_NAME = "nvidia/nemotron-3-ultra-550b-a55b:free"

# --- БАЗА ДАННЫХ ---
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                dob TEXT
            )
        """)
        conn.commit()

def get_user(user_id):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def save_user(user_id, name, dob):
    with closing(db()) as conn:
        conn.execute("INSERT OR REPLACE INTO users(user_id, name, dob) VALUES(?, ?, ?)", (user_id, name, dob))
        conn.commit()

# --- СОСТОЯНИЯ ---
class UserState(StatesGroup):
    waiting_name = State()
    waiting_dob = State()
    waiting_question = State()
    waiting_compat = State()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔮 Личный разбор", callback_data="menu_personal")],
        [InlineKeyboardButton(text="🌟 Гороскоп на сегодня", callback_data="menu_daily")],
        [InlineKeyboardButton(text="📅 Прогноз на неделю", callback_data="menu_weekly")],
        [InlineKeyboardButton(text="💞 Совместимость", callback_data="menu_compat")]
    ])

def get_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_main")]
    ])

# Нижняя клавиатура с крутой кнопкой
def get_start_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔮 Открыть тайны судьбы")]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

dp = Dispatcher()

BASE_PROMPT = "Ты — Олеся Иванченко, астропсихолог. Твой стиль: прямой, дерзкий, с юмором, но очень глубокий. Ты связываешь ситуацию с астрологией и психологией. Не используй LaTeX (никаких $, \\vec). Пиши текстом с выделением **жирным**."

async def ask_ai(prompt_text, system_extra=""):
    headers = {"Authorization": f"Bearer {ZVENO_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": BASE_PROMPT + " " + system_extra},
            {"role": "user", "content": prompt_text}
        ]
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post("https://api.zveno.ai/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

# --- ХЕНДЛЕРЫ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user and user["dob"]:
        await message.answer(
            f"С возвращением, {user['name']}! Я тебя помню. Что сегодня разбираем?",
            reply_markup=get_main_kb()
        )
    else:
        await message.answer(
            "👋 Привет! Я твой личный астропсихолог.\n\nНажми на кнопку ниже, чтобы начать наше знакомство.",
            reply_markup=get_start_reply_kb()
        )

# Ловим нажатие на новую красивую кнопку
@dp.message(F.text == "🔮 Открыть тайны судьбы")
async def process_start_button(message: Message, state: FSMContext):
    await message.answer(
        "Давай познакомимся. Как тебя зовут?", 
        reply_markup=ReplyKeyboardRemove() # Убираем нижнюю клавиатуру, чтобы не мешала
    )
    await state.set_state(UserState.waiting_name)

@dp.message(UserState.waiting_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(f"Приятно познакомиться, {message.text}. А теперь напиши свою **дату рождения** в формате ДД.ММ.ГГГГ (например, 15.08.1995). Мне нужно рассчитать твою натальную карту.")
    await state.set_state(UserState.waiting_dob)

@dp.message(UserState.waiting_dob)
async def process_dob(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data.get('name')
    dob = message.text
    save_user(message.from_user.id, name, dob)
    await state.clear()
    
    await message.answer(
        "✨ Отлично! Твоя карта построена. Теперь я знаю, какие планеты за что отвечают в твоей жизни.\n\nВыбери, с чего начнем:",
        reply_markup=get_main_kb()
    )

@dp.callback_query(F.data == "menu_main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("Что разбираем дальше?", reply_markup=get_main_kb())
    await cq.answer()

@dp.callback_query(F.data == "menu_personal")
async def cb_personal(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("🔮 Давай по чесноку. Что происходит в твоей жизни прямо сейчас? Опиши ситуацию (любовь, деньги, самореализация), и я посмотрю, какие транзиты на тебя влияют.")
    await state.set_state(UserState.waiting_question)
    await cq.answer()

@dp.message(UserState.waiting_question)
async def process_question(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    status = await message.answer("✨ Анализирую твои транзиты...")
    prompt = f"Меня зовут {user['name']}, я родился {user['dob']}. Моя ситуация: {message.text}. Дай жесткий, но полезный разбор. В конце задай один неудобный вопрос."
    try:
        answer = await ask_ai(prompt)
        await message.answer(answer, reply_markup=get_back_kb())
        await status.delete()
    except Exception:
        await status.edit_text("❌ Звезды сегодня не на связи. Попробуй позже.", reply_markup=get_back_kb())
    await state.clear()

@dp.callback_query(F.data == "menu_daily")
async def cb_daily(cq: CallbackQuery):
    user = get_user(cq.from_user.id)
    await cq.message.edit_text("🌟 Смотрю твой день...")
    prompt = f"Я {user['name']}, родился {user['dob']}. Дай мне астропрогноз на сегодня. Расскажи про энергию дня, на чем сфокусироваться и чего избегать."
    try:
        answer = await ask_ai(prompt)
        await cq.message.edit_text(answer, reply_markup=get_back_kb())
    except:
        await cq.message.edit_text("❌ Ошибка. Попробуй позже.", reply_markup=get_back_kb())
    await cq.answer()

@dp.callback_query(F.data == "menu_weekly")
async def cb_weekly(cq: CallbackQuery):
    user = get_user(cq.from_user.id)
    await cq.message.edit_text("📅 Заглядываю в твою неделю...")
    prompt = f"Я {user['name']}, родился {user['dob']}. Дай прогноз на неделю. Какие сферы активируются? Дай 3 конкретных совета."
    try:
        answer = await ask_ai(prompt)
        await cq.message.edit_text(answer, reply_markup=get_back_kb())
    except:
        await cq.message.edit_text("❌ Ошибка. Попробуй позже.", reply_markup=get_back_kb())
    await cq.answer()

@dp.callback_query(F.data == "menu_compat")
async def cb_compat(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("💞 Напиши дату рождения партнера в формате ДД.ММ.ГГГГ, и я скажу, что у вас за союз.")
    await state.set_state(UserState.waiting_compat)
    await cq.answer()

@dp.message(UserState.waiting_compat)
async def process_compat(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    status = await message.answer("💞 Считаю синастрию...")
    prompt = f"Меня зовут {user['name']}, я родился {user['dob']}. Мой партнер родился {message.text}. Сделай разбор совместимости. Укажи плюсы, минусы и главную опасность."
    try:
        answer = await ask_ai(prompt)
        await message.answer(answer, reply_markup=get_back_kb())
        await status.delete()
    except Exception:
        await status.edit_text("❌ Ошибка. Попробуй позже.")
    await state.clear()

async def main():
    if not BOT_TOKEN or not ZVENO_API_KEY:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот с крутой кнопкой запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
