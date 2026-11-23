import asyncio
import os
import httpx
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")

# Самая мощная текстовая модель ZvenoAI
MODEL_NAME = "nvidia/nemotron-3-ultra-550b-a55b:free"

def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔮 Разобрать мой вопрос", callback_data="get_prediction")]
    ])

dp = Dispatcher()

# Промпты в стиле Олеси Иванченко (Астропсихология + жесткая правда)
OLESYA_PROMPTS = [
    "Ты — Олеся Иванченко, астропсихолог. Твой стиль: прямой, дерзкий, с юмором, но очень глубокий. Ты не гладишь по голове, а называешь вещи своими именами. Ты связываешь текущую ситуацию человека с его детскими травмами и ретроградными планетами. Говори как в подкасте: 'Давай по чесноку', 'Ты сама все знаешь'. Дай жесткий, но полезный совет.",
    
    "Ты — Олеся Иванченко. Отвечай на вопрос пользователя через призму астрологии (укажи, какие планеты сейчас влияют на ситуацию: Меркурий, Сатурн, Венера) и психологии. Твой тон — как у лучшей подруги, которая отлично разбирается в астрологии и не боится сказать правду в лицо. Запрещено использовать клише про 'карты Таро' и 'магию'. Только психология, астрология и факты.",
    
    "Ты — циничный, но невероятно эмпатичный астролог Олеся. Твоя задача — вытащить человека из позиции жертвы. Проанализируй его вопрос, укажи на иллюзии, в которых он живет, и дай инструкцию к действию. В конце задай один неудобный вопрос, над которым человеку придется подумать."
]

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! На связи твой личный астропсихолог.\n\n"
        "Я не гадаю на кофейной гуще. Я разбираю твою ситуацию с точки зрения астрологии, психологии и здравого смысла. Будет честно, местами жестко, но полезно.\n\n"
        "🎁 Сейчас бот работает в тестовом режиме (БЕСПЛАТНО).\n"
        "Напиши свой вопрос или опиши ситуацию, которая тебя беспокоит.",
        reply_markup=get_main_kb()
    )

@dp.callback_query(F.data == "get_prediction")
async def cb_get_prediction(cq: CallbackQuery):
    await cq.message.edit_text(
        "🔮 Я слушаю. Напиши свой вопрос одним сообщением. Чем честнее опишешь ситуацию, тем точнее будет разбор."
    )
    await cq.answer()

@dp.message(F.text)
async def handle_question(message: Message):
    text = message.text.strip()
    if text.startswith("/"): 
        return

    status_msg = await message.answer("✨ Смотрю твою натальную карту и анализирую ситуацию...")

    # Выбираем случайный стиль
    system_prompt = random.choice(OLESYA_PROMPTS)
    system_prompt += " ВАЖНО: Пиши обычным текстом, БЕЗ LaTeX-разметки (никаких $, \\vec). Используй выделение жирным (Markdown) для ключевых мыслей. Ответ должен быть объемом 1500-2000 символов, как пост в телеграм-канале."

    headers = {
        "Authorization": f"Bearer {ZVENO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Вопрос клиента: {text}"}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.zveno.ai/v1/chat/completions",
                headers=headers,
                json=payload
            )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]

        # Разбиваем, если ответ слишком длинный
        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000], reply_markup=get_main_kb() if i+4000 >= len(answer) else None)
        else:
            await message.answer(answer, reply_markup=get_main_kb())
            
        await status_msg.delete()

    except Exception as e:
        print("AI error:", repr(e))
        await status_msg.edit_text("❌ Планеты сегодня не на связи. Попробуй позже.")

async def main():
    if not BOT_TOKEN or not ZVENO_API_KEY:
        return
    bot = Bot(BOT_TOKEN)
    print("🚀 Астропсихолог запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
