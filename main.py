import asyncio
import os
import tempfile
import httpx

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
SILERO_API_URL = os.getenv("SILERO_API_URL", "http://localhost:8000")
MAX_CHARS = int(os.getenv("MAX_CHARS", "1000"))

# Названия для кнопок (внутри используются технические ID Silero: baya, aidar и т.д.)
VOICES = {
    "baya": "🎙 Виктория (жен)",
    "aidar": "🎙 Игорь (муж)",
    "kseniya": "🎙 Мария (жен)",
    "xenia": "🎙 Анна (жен)",
    "eugene": "🎙 Александр (муж)",
}

user_voices = {}

def get_voices_kb():
    rows = []
    for key, label in VOICES.items():
        rows.append([InlineKeyboardButton(text=label, callback_data=f"voice:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для озвучки (Silero TTS).\n\n"
        "🎙 Выбери голос кнопкой ниже, а затем отправь текст.",
        reply_markup=get_voices_kb()
    )

@dp.callback_query(F.data.startswith("voice:"))
async def cb_voice(cq: CallbackQuery):
    voice_key = cq.data.split(":", 1)[1]
    if voice_key not in VOICES:
        await cq.answer("Неизвестный голос", show_alert=True)
        return
    user_voices[cq.from_user.id] = voice_key
    await cq.message.answer(f"✅ Голос выбран: {VOICES[voice_key]}.\nТеперь отправь мне текст!")
    await cq.answer()

@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    if text.startswith("/"):
        return
    if len(text) > MAX_CHARS:
        await message.answer(f"⚠️ Текст слишком длинный. Максимум {MAX_CHARS} символов.")
        return

    voice_key = user_voices.get(message.from_user.id, "baya") # По умолчанию Виктория
    status_msg = await message.answer("⏳ Генерирую аудио...")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{SILERO_API_URL}/generate",
                params={"text": text, "speaker": voice_key}
            )
        
        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

        with open(tmp_path, "wb") as f:
            f.write(response.content)
        
        await message.answer_audio(
            FSInputFile(tmp_path),
            caption=f"🎙 Голос: {VOICES[voice_key]}"
        )
        await status_msg.delete()

    except Exception as e:
        print("TTS error:", repr(e))
        await status_msg.edit_text("❌ Ошибка генерации. Попробуй позже.")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

async def main():
    if not BOT_TOKEN:
        return
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
