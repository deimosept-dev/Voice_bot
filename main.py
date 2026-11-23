import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from pricing import ACCESS, RANKS, SKIN_TIERS, calculate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mlbb")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
PORT = int(os.environ.get("PORT", "8080"))
HOURLY_LIMIT = int(os.environ.get("HOURLY_LIMIT", "5"))
MAX_PHOTOS = 10

BASE_DIR = Path(__file__).parent
usage = {}

TOOL = {
    "name": "report_account",
    "description": "Сообщить данные аккаунта Mobile Legends, найденные на скриншотах.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skins": {
                "type": "object",
                "description": "Количество скинов по тирам. Только то, что видно на скринах.",
                "properties": {k: {"type": "integer"} for k in SKIN_TIERS},
            },
            "collection_points": {"type": ["integer", "null"]},
            "highest_rank": {"type": "string", "enum": list(RANKS) + ["unknown"]},
            "current_rank": {"type": ["string", "null"]},
            "win_rate": {"type": ["number", "null"]},
            "ranked_matches": {"type": ["integer", "null"]},
            "heroes_owned": {"type": ["integer", "null"]},
            "maxed_emblems": {"type": ["integer", "null"]},
            "diamonds": {"type": ["integer", "null"]},
            "notes": {
                "type": "string",
                "description": "По-русски: что не удалось определить и каких скриншотов не хватает.",
            },
        },
        "required": ["skins", "highest_rank", "notes"],
    },
}

PROMPT = (
    "Это скриншоты аккаунта Mobile Legends: Bang Bang. Найди на них данные и вызови report_account.\n"
    "Тиры скинов: Supreme (Legend), Grand (Collab/Aspirants), Exquisite (Collector/Lucky Box), "
    "Deluxe (Epic/Zodiac/Lightborn), Exceptional (Special/Starlight), Common (Basic/Elite/Season), Painted.\n"
    "Правила: считай только то, что реально видно. Ничего не додумывай. Если данных нет, ставь null "
    "(для скинов 0, для ранга unknown) и напиши в notes, чего не хватает. "
    "Если один и тот же экран есть на нескольких скринах, не считай дважды."
)


def check_init_data(init_data):
    """Проверка подписи Telegram, чтобы чужие не тратили ваш ключ ИИ."""
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received = parsed.pop("hash", None)
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        return json.loads(parsed.get("user", "{}")).get("id")
    except ValueError:
        return None


def rate_limited(user_id):
    now = time.time()
    recent = [t for t in usage.get(user_id, []) if now - t < 3600]
    if len(recent) >= HOURLY_LIMIT:
        usage[user_id] = recent
        return True
    recent.append(now)
    usage[user_id] = recent
    return False


async def extract_from_images(images):
    content = []
    for media_type, raw in images:
        if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            media_type = "image/jpeg"
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(raw).decode()},
        })
    content.append({"type": "text", "text": PROMPT})

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 1500,
                "tools": [TOOL],
                "tool_choice": {"type": "tool", "name": "report_account"},
                "messages": [{"role": "user", "content": content}],
            },
        )
    if r.status_code != 200:
        log.error("Anthropic %s: %s", r.status_code, r.text[:500])
        raise RuntimeError("Сервис распознавания временно недоступен")
    for block in r.json().get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise RuntimeError("Не удалось разобрать скриншоты")


async def valuate(request):
    try:
        form = await request.post()
        user_id = check_init_data(form.get("init_data", ""))
        if user_id is None:
            return web.json_response({"ok": False, "error": "Откройте приложение через Telegram"}, status=403)
        if rate_limited(user_id):
            return web.json_response({"ok": False, "error": f"Лимит {HOURLY_LIMIT} оценок в час. Попробуйте позже."}, status=429)

        images = []
        for f in form.getall("photos", [])[:MAX_PHOTOS]:
            if hasattr(f, "file"):
                images.append((f.content_type, f.file.read()))
        if not images:
            return web.json_response({"ok": False, "error": "Нет фото"}, status=400)

        access = form.get("access", "safe")
        if access not in ACCESS:
            access = "safe"
        data = await extract_from_images(images)
        return web.json_response({"ok": True, "extracted": data, "result": calculate(data, access)})
    except Exception as e:
        log.exception("valuate failed")
        return web.json_response({"ok": False, "error": str(e) or "Ошибка сервера"}, status=500)


async def index(request):
    return web.FileResponse(BASE_DIR / "index.html")


async def health(request):
    return web.Response(text="ok")


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📸 Оценить аккаунт", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await message.answer(
        "Привет! Я оценю твой аккаунт MLBB по скриншотам.\n"
        "Нажми кнопку и загрузи скрины профиля, коллекции скинов, героев и эмблем.\n\n"
        "⚠️ Оценка примерная. Покупка и продажа аккаунтов нарушает правила Moonton.",
        reply_markup=kb,
    )


async def main():
    app = web.Application(client_max_size=40 * 1024 * 1024)
    app.add_routes([web.get("/", index), web.get("/health", health), web.post("/api/valuate", valuate)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Web server on port %s", PORT)

    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
