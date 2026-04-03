import sys
import json
import asyncio
from Module.dcbot import DCBot
from Module.config import TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_discord_intents

def load_gallery_config(gallery_name):
    with open("galleries.json", "r", encoding="utf-8") as f:
        galleries = json.load(f)

    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)

    return galleries[gallery_name]

async def main(gallery_name):
    config = load_gallery_config(gallery_name)
    intents = get_discord_intents()
    bot = DCBot(
        token=TOKEN,
        base_url=config["base_url"],
        channel_ids=config["channel_ids"],
        telegram_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID,
        intents=intents,
    )
    await bot.run_bot()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_gallery.py <gallery_name>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
