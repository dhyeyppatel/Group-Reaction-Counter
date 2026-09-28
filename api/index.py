import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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
db = client.reaction_bot if client is not None else None
col_reactions = db.reactions if db is not None else None

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

@app.get("/api/stats_data")
async def api_stats_data():
    """Returns JSON data for the web UI."""
    if not col_reactions:
        return {"error": "Database not configured"}
        
    pipeline = [
        {"$match": {"user_id": {"$exists": False}}},
        {"$match": {"count": {"$gt": 0}}},
        {"$group": {"_id": "$reaction", "count": {"$sum": "$count"}}},
        {"$sort": {"count": -1}}
    ]
    results = list(col_reactions.aggregate(pipeline))
    return {"data": [{"emoji": r["_id"], "count": r["count"]} for r in results]}

@app.get("/")
async def serve_ui():
    """Serves a beautiful Glassmorphism dashboard."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Reaction Tracker Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Outfit', sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                color: #f8fafc;
                min-height: 100vh;
            }
            .glass-card {
                background: rgba(255, 255, 255, 0.05);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            }
            .glow-text {
                text-shadow: 0 0 20px rgba(99, 102, 241, 0.5);
            }
            .bar-fill {
                background: linear-gradient(90deg, #6366f1 0%, #a855f7 100%);
                box-shadow: 0 0 15px rgba(168, 85, 247, 0.5);
                transition: width 1s ease-out;
            }
        </style>
    </head>
    <body class="flex items-center justify-center p-6">
        <div class="w-full max-w-3xl glass-card rounded-3xl p-8 md:p-12">
            <div class="text-center mb-10">
                <h1 class="text-4xl md:text-5xl font-bold mb-4 glow-text bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-purple-400">
                    Live Reaction Stats
                </h1>
                <p class="text-slate-400 text-lg">Real-time Telegram engagement leaderboard</p>
            </div>

            <div id="stats-container" class="space-y-6">
                <div class="flex justify-center">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
                </div>
            </div>
        </div>

        <script>
            async function fetchStats() {
                try {
                    const res = await fetch('/api/stats_data');
                    const data = await res.json();
                    
                    const container = document.getElementById('stats-container');
                    container.innerHTML = '';
                    
                    if (data.error || !data.data || data.data.length === 0) {
                        container.innerHTML = '<p class="text-center text-slate-400 text-lg mt-8">No reactions tracked yet. Go react to some messages!</p>';
                        return;
                    }
                    
                    const maxCount = Math.max(...data.data.map(d => d.count));
                    
                    data.data.forEach((item, index) => {
                        const percentage = (item.count / maxCount) * 100;
                        const emojiChar = item.emoji.startsWith('custom_') ? '🌟' : item.emoji;
                        
                        const row = document.createElement('div');
                        row.className = 'bg-slate-800/40 rounded-xl p-5 border border-slate-700/50 hover:bg-slate-800/80 transition-all duration-300 transform hover:-translate-y-1';
                        row.innerHTML = `
                            <div class="flex items-center justify-between mb-3">
                                <div class="flex items-center space-x-4">
                                    <div class="text-4xl drop-shadow-lg">${emojiChar}</div>
                                    <span class="text-xl font-semibold text-slate-200">Rank #${index + 1}</span>
                                </div>
                                <span class="text-3xl font-bold text-purple-400">${item.count}</span>
                            </div>
                            <div class="w-full bg-slate-900/50 rounded-full h-3 overflow-hidden">
                                <div class="bar-fill rounded-full h-3" style="width: 0%"></div>
                            </div>
                        `;
                        container.appendChild(row);
                        
                        // Trigger animation
                        setTimeout(() => {
                            row.querySelector('.bar-fill').style.width = `${percentage}%`;
                        }, 50 * (index + 1));
                    });
                    
                } catch (err) {
                    console.error(err);
                    document.getElementById('stats-container').innerHTML = '<p class="text-center text-red-400">Failed to load stats.</p>';
                }
            }
            
            fetchStats();
            // Refresh every 5 seconds
            setInterval(fetchStats, 5000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
