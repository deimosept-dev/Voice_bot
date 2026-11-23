import asyncio
import os
import sqlite3
import json
import io
import re
import pytesseract
from PIL import Image
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"
ADMIN_ID = 1636139244 

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

def log_action(user_id, action):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(db()) as conn:
        conn.execute("INSERT INTO users(user_id) VALUES(?) ON CONFLICT DO NOTHING", (user_id,))
        conn.execute("INSERT INTO stats(user_id, action, created_at) VALUES(?, ?, ?)", (user_id, action, now))
        conn.commit()

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log_action(message.from_user.id, "start")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer(
        "👋 Привет! Нажми на кнопку внизу, чтобы открыть калькулятор.\n\n"
        "После того как выберешь фото, **пришли их сюда в чат**, и я оценю аккаунт.",
        reply_markup=kb
    )

@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "calculate":
            await message.answer("✅ Отлично! Теперь отправь скриншоты прямо сюда в чат.")
    except Exception as e:
        print("WebApp error:", e)

@dp.message(F.photo)
async def handle_photo(message: Message):
    log_action(message.from_user.id, "photo_uploaded")
    status_msg = await message.answer("📊 Анализирую данные аккаунта...")

    try:
        # 1. Скачиваем фото
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        downloaded_file = await message.bot.download_file(file_info.file_path)

        # 2. Читаем текст локально
        image = Image.open(io.BytesIO(downloaded_file.read()))
        text = pytesseract.image_to_string(image, lang='rus+eng')
        text_lower = text.lower()

        if len(text.strip()) < 5:
            raise Exception("Не удалось разглядеть текст.")

        # 3. Локальный подсчет (без ИИ)
        base_price = 1500 # Базовая цена за любой аккаунт
        details = []
        bonuses = 0

        # Ищем ранг
        if "immortal" in text_lower or "бессмерт" in text_lower:
            bonuses += 11500
            details.append("• Максимальный ранг: <b>Immortal (Бессмертный)</b> (+11 500 руб.)")
        elif "glory" in text_lower or "слав" in text_lower:
            bonuses += 5750
            details.append("• Максимальный ранг: <b>Mythical Glory</b> (+5 750 руб.)")
        else:
            details.append("• Максимальный ранг: не определен или ниже Mythic")

        # Ищем винрейт (ищем проценты)
        winrate_match = re.search(r'(\d{2}\.?\d{0,2})\s*%', text_lower)
        if winrate_match:
            wr = float(winrate_match.group(1))
            details.append(f"• Винрейт: <b>{wr}%</b>")
            if wr >= 60:
                bonuses += 1500
                details.append("  <i>(Бонус за высокий винрейт: +1 500 руб.)</i>")
        
        # Ищем количество матчей (ищем 4-5 значные числа рядом со словом "матчи")
        matches_match = re.search(r'(\d{3,5})\s*(матчи|matches)', text_lower)
        if matches_match:
            matches = int(matches_match.group(1))
            details.append(f"• Количество матчей: <b>{matches}</b>")
            if matches > 5000:
                bonuses += 500

        # Ищем скины (если есть слово "скин" или "skin" и цифры)
        skins_match = re.search(r'(\d{2,3})\s*(скин|skin|образ)', text_lower)
        if skins_match:
            skins = int(skins_match.group(1))
            details.append(f"• Найдено скинов: <b>{skins}</b>")
            bonuses += skins * 50 # По 50 руб за скин (примерно)
        else:
            details.append("• Данные по скинам не предоставлены")

        total_price = base_price + bonuses

        # 4. Собираем красивый ответ
        details_text = "\n".join(details)
        final_answer = (
            f"<b>Анализ аккаунта завершен</b>\n\n"
            f"{details_text}\n\n"
            f"<b>Примерная стоимость: {total_price} рублей</b>\n\n"
            f"<i>Совет: Чтобы продать аккаунт быстрее, обязательно сделайте скриншоты редких скинов (Supreme или Collector) — они повышают цену.</i>"
        )

        await message.answer(final_answer, parse_mode="HTML")
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка:\n{str(e)[:200]}")
        print("Error:", repr(e))

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_starts = conn.execute("SELECT COUNT(*) FROM stats WHERE action='start'").fetchone()[0]
        total_photos = conn.execute("SELECT COUNT(*) FROM stats WHERE action='photo_uploaded'").fetchone()[0]
    await message.answer(
        f"📊 <b>Статистика:</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🚀 Запустили бота: {total_starts}\n"
        f"📸 Загрузили фото на оценку: {total_photos}",
        parse_mode="HTML"
    )

async def main():
    if not BOT_TOKEN:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот запущен (без ИИ, локальный подсчет)!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
