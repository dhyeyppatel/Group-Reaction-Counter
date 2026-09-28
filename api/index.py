import os
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update
from aiogram.filters import Command
from pymongo import MongoClient
import json

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")

# Initialize FastAPI & aiogram
app = FastAPI()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Cache MongoDB connection outside the handler for warm starts
client = MongoClient(MONGO_URI) if MONGO_URI else None
db = client.reaction_bot if client else None
col_reactions = db.reactions if db else None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I am a **Group Reaction Tracker Bot**.\n\n"
        "Make sure I am an Admin in your group to track all messages, and use `/stats` to see the leaderboard!",
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not col_reactions:
        await message.answer("Database is not configured. Please set MONGO_URI.")
        return
        
    chat_id = message.chat.id
    
    # Aggregation pipeline to get top reactions in the group
    pipeline = [
        {"$match": {"chat_id": chat_id, "user_id": {"$exists": False}}},
        {"$match": {"count": {"$gt": 0}}},
        {"$sort": {"count": -1}}
    ]
    
    results = list(col_reactions.aggregate(pipeline))
    
    if not results:
        await message.answer("No reactions recorded yet in this group.")
        return
        
    text = "📊 **Group Reaction Stats**\n\n"
    total = 0
    for r in results:
        emoji = r.get("reaction")
        count = r.get("count")
        text += f"{emoji} : {count}\n"
        total += count
        
    text += f"\n**Total Reactions:** {total}"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_reaction()
async def on_reaction(reaction: types.MessageReactionUpdated):
    if not col_reactions:
        return
        
    chat_id = reaction.chat.id
    msg_id = reaction.message_id
    user_id = reaction.user.id if reaction.user else "anonymous"
    
    def get_key(r):
        return r.emoji if r.type == 'emoji' else f"custom_{r.custom_emoji_id}"
        
    new_r = [get_key(r) for r in reaction.new_reaction]
    old_r = [get_key(r) for r in reaction.old_reaction]
    
    added = [r for r in new_r if r not in old_r]
    removed = [r for r in old_r if r not in new_r]
    
    # Process additions
    for r in added:
        # Increment group total
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": {"$exists": False}},
            {"$inc": {"count": 1}},
            upsert=True
        )
        # Increment user specific total (if not anonymous)
        if user_id != "anonymous":
            col_reactions.update_one(
                {"chat_id": chat_id, "reaction": r, "user_id": user_id},
                {"$inc": {"count": 1}},
                upsert=True
            )
            
    # Process removals
    for r in removed:
        # Decrement group total
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": {"$exists": False}},
            {"$inc": {"count": -1}}
        )
        # Decrement user specific total (if not anonymous)
        if user_id != "anonymous":
            col_reactions.update_one(
                {"chat_id": chat_id, "reaction": r, "user_id": user_id},
                {"$inc": {"count": -1}}
            )

# Vercel Serverless Function entry point
@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """
    This endpoint will be called by Telegram whenever there's a new update.
    """
    try:
        update_data = await request.json()
        # Parse Telegram JSON into aiogram Update model
        update = Update(**update_data)
        
        # Feed the update into aiogram's dispatcher
        await dp.feed_update(bot, update)
    except Exception as e:
        print(f"Error processing update: {e}")
        
    return {"status": "ok"}

@app.get("/api/setup_webhook")
async def setup_webhook(request: Request):
    """
    Visit this URL in your browser to tell Telegram to send updates to this Vercel app.
    e.g., https://your-vercel-app.vercel.app/api/setup_webhook
    """
    # Construct the webhook URL dynamically based on the current request host
    webhook_url = f"https://{request.headers.get('host')}/api/webhook"
    
    # Configure exactly which updates we want (including reactions!)
    allowed_updates = ["message", "edited_message", "callback_query", "inline_query", "message_reaction", "message_reaction_count"]
    
    # Send the request to Telegram
    success = await bot.set_webhook(
        url=webhook_url,
        allowed_updates=allowed_updates,
        drop_pending_updates=True
    )
    
    if success:
        return {"status": "success", "message": f"Webhook securely set to {webhook_url} with reactions enabled!"}
    else:
        return {"status": "error", "message": "Failed to set webhook. Check your BOT_TOKEN."}
