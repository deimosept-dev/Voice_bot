import asyncio
import os
import sqlite3
import tempfile
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from edge_tts import Communicate

# Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
MAX_CHARS = int(os.getenv("MAX_CHARS", "1500"))

# Библиотека голосов (Виктория, Игорь и др.)
VOICES = {
    "victoria": ("Виктория (RU, жен)", "ru-RU-DariyaNeural"),
    "igor": ("Игорь (RU, муж)", "ru-RU-LevNeural"),
    "maria": ("Мария (RU, жен)", "ru-RU-MashaNeural"),
    "aria": ("Aria (US, жен)", "en-US-AriaNeural"),
    "guy": ("Guy (US, муж)", "en-US-GuyNeural"),
    "sonia": ("Sonia (UK, жен)", "en-GB-SoniaNeural"),
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                voice TEXT NOT NULL DEFAULT 'victoria'
            )
        """)
        conn.commit()

def get_user_voice(user_id):
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        conn.commit()
        row = conn.execute("SELECT voice FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["voice"] if row else "victoria"

def set_user_voice(user_id, voice):
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        conn.execute("UPDATE users SET voice=? WHERE user_id=?", (voice, user_id))
        conn.commit()

def get_voices_kb():
    rows = []
    items = list(VOICES.items())
    for i in range(0, len(items), 2):
        row = []
        for key, (label, _) in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"voice:{key}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для озвучки текста.\n\n"
        "🎙 Выбери голос кнопкой ниже, а затем просто отправь мне любой текст, "
        "и я пришлю тебе готовый аудиофайл.\n\n"
        "Всё абсолютно БЕСПЛАТНО!",
        reply_markup=get_voices_kb()
    )

@dp.message(Command("voices"))
async def cmd_voices(message: Message):
    await message.answer("Выбери голос для озвучки:", reply_markup=get_voices_kb())

@dp.callback_query(F.data.startswith("voice:"))
async def cb_voice(cq: CallbackQuery):
    voice_key = cq.data.split(":", 1)[1]
    if voice_key not in VOICES:
        await cq.answer("Неизвестный голос", show_alert=True)
        return
    
    set_user_voice(cq.from_user.id, voice_key)
    await cq.message.answer(f"✅ Голос выбран: {VOICES[voice_key][0]}.\nТеперь отправь мне текст!")
    await cq.answer()

@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    if text.startswith("/"):
        return
    
    if len(text) > MAX_CHARS:
        await message.answer(f"⚠️ Текст слишком длинный. Максимум {MAX_CHARS} символов.")
        return

    voice_key = get_user_voice(message.from_user.id)
    if voice_key not in VOICES:
        voice_key = "victoria"

    # Отправляем сообщение о процессе
    status_msg = await message.answer("⏳ Генерирую аудио...")

    # Создаем временный файл для аудио
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        # Генерация озвучки
        communicate = Communicate(text, VOICES[voice_key][1])
        await communicate.save(tmp_path)
        
        # Отправка аудио
        await message.answer_audio(
            FSInputFile(tmp_path),
            caption=f"🎙 Голос: {VOICES[voice_key][0]}"
        )
        
        # Удаляем сообщение "Генерирую..."
        await status_msg.delete()
        
    except Exception as e:
        print("TTS error:", repr(e))
        await status_msg.edit_text("❌ Ошибка при генерации. Попробуй еще раз или отправь текст покороче.")
    finally:
        # Удаляем временный файл, чтобы не забивать память
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

async def main():
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не задан в переменных!")
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
