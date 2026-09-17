"""
Telegram-бот для поиска изображений по текстовому запросу.
"""

import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InputMediaPhoto
from aiohttp import web
from deep_translator import GoogleTranslator

# ==== НАСТРОЙКИ ====
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
UNSPLASH_ACCESS_KEY = os.environ["UNSPLASH_ACCESS_KEY"]
RESULTS_PER_QUERY = 3
PORT = int(os.environ.get("PORT", 8080))
# ====================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

_translation_cache: dict[str, str] = {}


async def translate_via_mymemory(query: str) -> str | None:
    """Прямой запрос к MyMemory API. Параметр de= — email,
    бесплатно поднимает дневной лимит с 5000 до 50000 символов."""
    url = "https://api.mymemory.translated.net/get"
    params = {
        "q": query,
        "langpair": "ru|en",
        "de": "imagesearchbot@example.com",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=8)
            ) as response:
                data = await response.json()
                translated = data.get("responseData", {}).get("translatedText")
                if translated and "MYMEMORY WARNING" not in translated.upper():
                    return translated
    except Exception as e:
        logging.warning("MyMemory request failed: %s", e)
    return None


async def translate_to_english(query: str) -> str:
    cache_key = query.lower().strip()
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    translated = None

    try:
        translated = GoogleTranslator(source="auto", target="en").translate(query)
    except Exception as e:
        logging.warning("Google Translate failed, trying MyMemory: %s", e)

    if not translated:
        translated = await translate_via_mymemory(query)

    result = translated or query
    _translation_cache[cache_key] = result
    logging.info("Translated '%s' -> '%s'", query, result)
    return result


async def search_images(query: str, count: int = 5) -> list[str]:
    search_query = await translate_to_english(query)

    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": search_query,
        "per_page": count,
        "client_id": UNSPLASH_ACCESS_KEY,
        "content_filter": "high",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logging.error("Unsplash API error: %s", await response.text())
                return []
            data = await response.json()

    results = data.get("results", [])
    return [item["urls"]["regular"] for item in results]


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! 👋\n\n"
        "Напиши мне любое слово или фразу — я найду подходящие изображения.\n\n"
        "Например: закат на море, космос, милые щенки"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Просто напиши текстовый запрос — и я пришлю несколько картинок по теме."
    )


@dp.message()
async def handle_text(message: types.Message):
    query = (message.text or "").strip()
    if not query:
        await message.answer("Пришли текстовый запрос, чтобы я мог найти картинки.")
        return

    searching_msg = await message.answer(f"🔍 Ищу картинки по запросу «{query}»...")

    image_urls = await search_images(query, RESULTS_PER_QUERY)

    await searching_msg.delete()

    if not image_urls:
        await message.answer(
            "Ничего не нашлось 😕 Попробуй другой запрос или другое слово."
        )
        return

    if len(image_urls) == 1:
        await message.answer_photo(photo=image_urls[0])
        return

    media = [InputMediaPhoto(media=url) for url in image_urls]
    await bot.send_media_group(chat_id=message.chat.id, media=media)


async def health_check(request):
    return web.Response(text="Bot is running")


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info("Health-check веб-сервер запущен на порту %s", PORT)


async def main():
    print("Бот запущен. Нажми Ctrl+C для остановки.")
    await run_web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
