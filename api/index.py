import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from pymongo import MongoClient
import html
import datetime

try:
    from api.themes import THEMES
except ImportError:
    from themes import THEMES

# ── Environment ─────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI  = os.environ.get("MONGO_URI")

# ── App & Bot ────────────────────────────────────────────────────────────────
app = FastAPI()
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ── MongoDB ──────────────────────────────────────────────────────────────────
client        = MongoClient(MONGO_URI) if MONGO_URI else None
db            = client.reaction_bot   if client is not None else None
col_reactions = db.reactions          if db is not None else None   # per-user & global reaction counts
col_chats     = db.chats              if db is not None else None   # group/channel metadata
col_users     = db.users              if db is not None else None   # user display names
col_msg_reactions = db.msg_reactions  if db is not None else None   # per-message reaction state
col_milestones = db.milestones        if db is not None else None   # tracks awarded milestones

# ── Sentiment & Mood ─────────────────────────────────────────────────────────
POSITIVE_EMOJIS = {
    "❤️", "🔥", "🎉", "👍", "🥰", "👏", "🤩", "😍", "💯", "💖", 
    "😂", "🤣", "😁", "🕊️", "🫡", "🙏", "🤝", "👌", "💋", "⚡", 
    "🏆", "🤗", "🎅", "🎄", "☃", "🆒", "💘", "🦄", "😘", "😎"
}
NEGATIVE_EMOJIS = {
    "👎", "💩", "🤬", "🤮", "🤡", "🖕", "💔", "😡", "🥱", "📉",
    "😢", "😭", "😨", "😱"
}
EMOJI_LABELS = {
    "❤️": "LOVE", "🥰": "LOVE", "😍": "LOVE", "💖": "LOVE", "💘": "LOVE", "😘": "LOVE",
    "😂": "FUN", "🤣": "FUN", "😁": "FUN", "🤪": "FUN", "🤡": "FUN",
    "🔥": "HYPE", "⚡": "HYPE", "💯": "HYPE", "🤩": "HYPE", "😎": "HYPE",
    "🎉": "CELEBRATE", "👏": "APPLAUSE", "🏆": "VICTORY", "🍾": "CELEBRATE",
    "👍": "AGREE", "👌": "AGREE", "🤝": "AGREEMENT", "🫡": "RESPECT", "🙏": "PRAYER",
    "👎": "DISLIKE", "🖕": "HOSTILE", "📉": "DOWN",
    "😮": "SURPRISE", "😱": "SHOCK", "🤯": "MIND BLOWN", "😨": "FEAR",
    "😢": "SAD", "😭": "CRYING", "💔": "HEARTBREAK",
    "😡": "ANGER", "🤬": "RAGE",
    "💩": "TRASH", "🤮": "DISGUST", "🤢": "DISGUST",
    "🥱": "BORED", "😴": "SLEEP", "😐": "NEUTRAL", "🆒": "COOL", "🦄": "MAGIC",
    "🕊️": "PEACE", "💋": "KISS"
}

# ── Gamification Roles ────────────────────────────────────────────────────────

def get_roles_for_chat(chat_doc: dict) -> list:
    if not chat_doc:
        return THEMES["default"]
    
    # 1. Custom roles set by admin
    if chat_doc.get("custom_roles"):
        roles = [(r["threshold"], r["title"]) for r in chat_doc["custom_roles"]]
        roles.sort(key=lambda x: x[0], reverse=True)
        return roles
        
    # 2. Selected theme
    theme_key = chat_doc.get("theme", "default")
    return THEMES.get(theme_key, THEMES["default"])

def get_title(count: int, roles: list) -> str:
    for threshold, title in roles:
        if count >= threshold:
            return title
    return roles[-1][1] if roles else "Observer 👀"


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_bot_account(user) -> bool:
    """Golden Rule #1: Never count bot accounts (name/username ending in 'bot')."""
    if user is None:
        return True
    if getattr(user, 'is_bot', False):
        return True
    first = (user.first_name or "").lower().strip()
    uname = (user.username  or "").lower().strip()
    return first.endswith("bot") or uname.endswith("bot")


def save_chat_meta(chat):
    """Cache chat metadata so the leaderboard can show titles/links."""
    if col_chats is None or chat is None:
        return
    col_chats.update_one(
        {"chat_id": chat.id},
        {"$set": {
            "chat_id":  chat.id,
            "title":    getattr(chat, "title", None) or getattr(chat, "first_name", str(chat.id)),
            "type":     chat.type,
            "username": getattr(chat, "username", None),
        }},
        upsert=True
    )


def save_user_meta(user):
    """Cache user display name/username for the leaderboard."""
    if col_users is None or user is None:
        return
    full = (user.first_name or "")
    if getattr(user, "last_name", None):
        full += f" {user.last_name}"
    col_users.update_one(
        {"user_id": user.id},
        {"$set": {
            "user_id":      user.id,
            "display_name": full.strip() or str(user.id),
            "username":     getattr(user, "username", None),
        }},
        upsert=True
    )


async def resolve_user(uid, bot_instance=None) -> dict:
    """Return display info for a user_id from cache, fallback to API."""
    if col_users is None:
        return {"display_name": str(uid), "username": None}
    doc = col_users.find_one({"user_id": uid}, {"_id": 0})
    if doc:
        return doc
    
    if bot_instance:
        try:
            chat = await bot_instance.get_chat(uid)
            full = (chat.first_name or "")
            if getattr(chat, "last_name", None):
                full += f" {chat.last_name}"
            doc = {
                "user_id": uid,
                "display_name": full.strip() or str(uid),
                "username": getattr(chat, "username", None)
            }
            col_users.update_one({"user_id": uid}, {"$set": doc}, upsert=True)
            return doc
        except Exception:
            pass
            
    return {"display_name": str(uid), "username": None}


# ── Bot Handlers ─────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Welcome to Reaction Tracker Bot!</b>\n\n"
        "I am the ultimate gamification and analytics bot for your Telegram communities! "
        "I track reactions, create beautiful leaderboards, and turn engagement into a fun game with unlockable roles.\n\n"
        "<i>What would you like to explore?</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 How to Use", callback_data="help_how")],
            [InlineKeyboardButton(text="👥 Group Commands", callback_data="help_group"),
             InlineKeyboardButton(text="👤 PM Commands", callback_data="help_pm")],
            [InlineKeyboardButton(text="🏆 Global Leaderboard", url="https://group-reaction-counter-pi.vercel.app/")],
            [InlineKeyboardButton(text="ℹ️ Privacy & Credits", callback_data="help_privacy")]
        ])
    )

@dp.callback_query(lambda c: c.data and c.data.startswith('help_'))
async def process_help_callbacks(callback_query: CallbackQuery):
    action = callback_query.data.split('_')[1]
    
    if action == "how":
        text = (
            "🛠️ <b>How to Use the Bot</b>\n\n"
            "1. <b>Add me to your Group/Channel.</b>\n"
            "2. <b>Promote me to Administrator.</b> (I need to see messages to count reactions!).\n"
            "3. <b>Start Reacting!</b> Whenever someone reacts to a message, I track it automatically.\n\n"
            "Use <code>/roles</code> to see the unlockable titles, and <code>/stats</code> to see your rank!"
        )
    elif action == "group":
        text = (
            "👥 <b>Group Commands</b>\n"
            "These commands are designed to be used inside your group/channel:\n\n"
            "• <code>/stats</code> - Show your personal rank and role.\n"
            "• <code>/show</code> - Display the group's top reactors.\n"
            "• <code>/top</code> - Link to the highest-reacted message of the day.\n"
            "• <code>/mood</code> - Show a graph of the group's emotional vibe.\n"
            "• <code>/roles</code> - List all unlockable Reaction Titles.\n"
            "• <code>/themes</code> - (Admin) Change the gamification theme.\n"
            "• <code>/settheme</code> - (Admin) Apply a new theme.\n"
            "• <code>/setrole</code> - (Admin) Create custom titles.\n"
            "• <code>/setinvite</code> - (Admin) Link your private group to the global board.\n"
            "• <code>/uncover</code> - Start a random giveaway based on reactions.\n"
            "• <code>/forcewrapped</code> - (Admin) Manually trigger the Weekly Wrapped report."
        )
    elif action == "pm":
        text = (
            "👤 <b>PM Commands</b>\n"
            "These commands can be sent to me privately in this chat:\n\n"
            "• <code>/audit @username</code> - Get a fair, bot-filtered Engagement Audit Report for any public group or channel. Great for advertisers!\n"
            "• <code>/mood</code> - Show the Global Vibe across all communities.\n"
            "• <code>/start</code> - Show this main menu."
        )
    elif action == "privacy":
        text = (
            "ℹ️ <b>Privacy & Credits</b>\n\n"
            "<b>Privacy Policy:</b>\n"
            "We only track reaction counts, user IDs, and message IDs. We do NOT read or store the actual content of your messages. "
            "All data is processed securely to provide you with the best analytics.\n\n"
            "<b>Developer Credits:</b>\n"
            "Developed with ❤️ by the open-source community. If you love this bot, make sure to give us a star on GitHub!"
        )
    elif action == "menu":
        text = (
            "👋 <b>Welcome to Reaction Tracker Bot!</b>\n\n"
            "I am the ultimate gamification and analytics bot for your Telegram communities! "
            "I track reactions, create beautiful leaderboards, and turn engagement into a fun game with unlockable roles.\n\n"
            "<i>What would you like to explore?</i>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 How to Use", callback_data="help_how")],
            [InlineKeyboardButton(text="👥 Group Commands", callback_data="help_group"),
             InlineKeyboardButton(text="👤 PM Commands", callback_data="help_pm")],
            [InlineKeyboardButton(text="🏆 Global Leaderboard", url="https://group-reaction-counter-pi.vercel.app/")],
            [InlineKeyboardButton(text="ℹ️ Privacy & Credits", callback_data="help_privacy")]
        ])
        await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback_query.answer()
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="help_menu")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback_query.answer()


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if col_reactions is None:
        await message.answer("Database is not configured.")
        return

    if message.chat.type == "private":
        await message.answer(
            "ℹ️ /stats shows a specific group's stats.\nUse /show here to see the Global Leaderboard!",
            parse_mode="HTML"
        )
        return

    save_chat_meta(message.chat)

    chat_id    = message.chat.id
    chat_title = message.chat.title or str(chat_id)

    emoji_results = list(col_reactions.aggregate([
        {"$match": {"chat_id": chat_id, "user_id": "GLOBAL", "count": {"$gt": 0}}},
        {"$sort": {"count": -1}},
        {"$limit": 30}
    ]))

    user_results = list(col_reactions.aggregate([
        {"$match": {"chat_id": chat_id, "user_id": {"$ne": "GLOBAL"}, "count": {"$gt": 0}}},
        {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}},
        {"$limit": 50}
    ]))

    if not emoji_results and not user_results:
        await message.answer("No reactions recorded yet in this group. React to some messages first!")
        return

    lines = [f"📊 <b>{html.escape(chat_title)} — Reaction Stats</b>\n"]

    if emoji_results:
        total = sum(r["count"] for r in emoji_results)
        lines.append("<blockquote expandable>")
        lines.append("🎭 <b>Emoji Leaderboard:</b>")
        for r in emoji_results:
            lines.append(f"  {r['reaction']}  {r['count']}")
        lines.append(f"  ┄ Total: <b>{total}</b>")
        lines.append("</blockquote>\n")

    if user_results:
        medals = ["🥇", "🥈", "🥉"]
        lines.append("<blockquote expandable>")
        lines.append("🏆 <b>Top Reactors in this Group:</b>")
        
        chat_doc = col_chats.find_one({"chat_id": chat_id}, {"_id": 0}) if col_chats is not None else None
        roles = get_roles_for_chat(chat_doc)
        
        for i, u in enumerate(user_results):
            user_id = u["_id"]
            total = u['total']
            info    = await resolve_user(user_id, bot)
            uname   = info.get("username")
            display = html.escape(info.get("display_name", str(user_id)))
            
            title_name = get_title(total, roles)
            
            # Hyperlink user
            if uname:
                name_part = f'<a href="https://t.me/{uname}">{display}</a>'
            else:
                name_part = f'<a href="tg://user?id={user_id}">{display}</a>'
                
            medal   = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"  {medal} {name_part} • <i>{title_name}</i> — {total}")
        lines.append("</blockquote>")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("show"))
async def cmd_show(message: types.Message):
    """Global group leaderboard — designed for PM use."""
    if col_reactions is None or col_chats is None:
        await message.answer("Database is not configured.")
        return

    results = list(col_reactions.aggregate([
        {"$match": {"user_id": "GLOBAL", "count": {"$gt": 0}}},
        {"$group": {"_id": "$chat_id", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}},
        {"$limit": 50}
    ]))

    if not results:
        await message.answer("No group data yet. Add me to some groups and let people react!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines  = ["🌍 <b>Global Group Leaderboard</b>\n", "<blockquote expandable>"]

    for i, r in enumerate(results):
        chat_id  = r["_id"]
        total    = r["total"]
        doc      = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
        
        # Fallback to API if not cached
        if not doc:
            try:
                chat = await bot.get_chat(chat_id)
                save_chat_meta(chat)
                doc = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
            except Exception:
                pass
                
        medal    = medals[i] if i < 3 else f"{i + 1}."

        if doc:
            title    = html.escape(doc.get("title", str(chat_id)))
            username = doc.get("username")
            invite   = doc.get("invite_link")
            if username:
                name_part = f'<a href="https://t.me/{username}">{title}</a>'
            elif invite:
                name_part = f'<a href="{invite}">{title}</a>'
            else:
                name_part = title
        else:
            name_part = str(chat_id)

        lines.append(f"{medal} {name_part} — {total} reactions")
    
    lines.append("</blockquote>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("mood"))
async def cmd_mood(message: types.Message):
    """Show global or group mood."""
    if col_reactions is None:
        await message.answer("Database not configured.")
        return

    is_pm = message.chat.type == "private"
    
    if is_pm:
        emoji_results = list(col_reactions.aggregate([
            {"$match": {"user_id": "GLOBAL", "count": {"$gt": 0}}},
            {"$group": {"_id": "$reaction", "count": {"$sum": "$count"}}}
        ]))
        title_text = "🌍 <b>GLOBAL COMMUNITY PULSE</b>"
    else:
        emoji_results = list(col_reactions.aggregate([
            {"$match": {"chat_id": message.chat.id, "user_id": "GLOBAL", "count": {"$gt": 0}}},
            {"$group": {"_id": "$reaction", "count": {"$sum": "$count"}}}
        ]))
        title_text = f"📊 <b>COMMUNITY PULSE FOR {html.escape(message.chat.title or 'THIS GROUP').upper()}</b>"
        
    if not emoji_results:
        await message.answer(f"╭─ {title_text} ─╮\n\nNo reactions recorded yet!\n╰───────────────────────╯", parse_mode="HTML")
        return

    # Group by labels for the bar chart
    grouped = {}
    for r in emoji_results:
        emoji = r["_id"]
        count = r["count"]
        label = EMOJI_LABELS.get(emoji, "REACT")
        if label not in grouped:
            grouped[label] = {"count": 0, "emoji": emoji}
        grouped[label]["count"] += count
        
    sorted_items = sorted(grouped.items(), key=lambda x: x[1]["count"], reverse=True)
    total_votes = sum(x[1]["count"] for x in sorted_items)
    
    lines = [f"╭─ {title_text} ─╮", "<blockquote><code>"]
    
    # Show top 5 labels
    for label, data in sorted_items[:5]:
        pct = (data["count"] / total_votes) * 100
        # 100% -> 12 blocks max
        bar_len = round(pct / (100/12))
        bar = ("█" * bar_len).ljust(12, " ")
        lbl = label.ljust(9, " ")
        pct_str = f"{int(pct)}%".rjust(4, " ")
        lines.append(f"  {data['emoji']}  {lbl} {bar} {pct_str}")
        
    lines.append("</code></blockquote>")
    
    # Overall Vibe
    pos = sum(r["count"] for r in emoji_results if r["_id"] in POSITIVE_EMOJIS)
    neg = sum(r["count"] for r in emoji_results if r["_id"] in NEGATIVE_EMOJIS)
    total_sentiment = pos + neg
    score = (pos / total_sentiment * 100) if total_sentiment > 0 else 0
    
    if score >= 80:
        vibe = "HIGHLY POSITIVE ✨"
    elif score >= 50:
        vibe = "MIXED / NEUTRAL ⚖️"
    elif total_sentiment == 0:
        vibe = "NEUTRAL 😐"
    else:
        vibe = "NEGATIVE ⚠️"
        
    lines.append(f"  ✦ Overall vibe: {vibe}")
    lines.append("╰────────────────────────────────╯")
    
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("audit"))
async def cmd_audit(message: types.Message):
    """Audit the engagement of a group/channel."""
    if col_reactions is None:
        await message.answer("Database not configured.")
        return

    chat_id = None
    target_name = "this group"
    
    parts = message.text.split()
    if message.chat.type == "private":
        if len(parts) < 2:
            await message.answer("Please provide a group username or ID to audit.\nExample: <code>/audit @mygroup</code>", parse_mode="HTML")
            return
        target = parts[1]
        
        if target.startswith("@"):
            chat_doc = col_chats.find_one({"username": {"$regex": f"^{target.replace('@', '')}$", "$options": "i"}})
            if not chat_doc:
                await message.answer(f"I don't have any data for {target}. Make sure I am an admin in that group/channel!")
                return
            chat_id = chat_doc["chat_id"]
            target_name = target
        elif target.startswith("http"):
            chat_doc = col_chats.find_one({"invite_link": target})
            if not chat_doc:
                await message.answer("I don't have any data for that invite link. The admin must run <code>/setinvite</code> in the group first!", parse_mode="HTML")
                return
            chat_id = chat_doc["chat_id"]
            target_name = chat_doc.get("title", str(chat_id))
        else:
            try:
                chat_id = int(target)
                chat_doc = col_chats.find_one({"chat_id": chat_id})
                if chat_doc:
                    target_name = chat_doc.get("title", str(chat_id))
            except ValueError:
                await message.answer("Invalid chat ID or username.")
                return
    else:
        chat_id = message.chat.id
        target_name = message.chat.title

    if not chat_id:
        await message.answer("Could not resolve the group.")
        return

    pipeline = [
        {"$match": {"chat_id": chat_id, "user_id": {"$ne": "GLOBAL"}, "count": {"$gt": 0}}},
        {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}}
    ]
    
    user_stats = list(col_reactions.aggregate(pipeline))
    
    if not user_stats:
        await message.answer(f"No reaction data found for {html.escape(target_name)}.")
        return
        
    total_organic_reactions = sum(u["total"] for u in user_stats)
    unique_users = len(user_stats)
    
    top_user = user_stats[0]
    dominance = (top_user["total"] / total_organic_reactions) * 100 if total_organic_reactions > 0 else 0
    
    if unique_users < 3:
        health_emoji = "🔴"
        health_text = "Poor (Too few participants)"
        trust_score = 30
    elif dominance > 50:
        health_emoji = "🟡"
        health_text = "Suspicious (One user dominates)"
        trust_score = 50
    elif dominance > 30:
        health_emoji = "🟢"
        health_text = "Fair (Moderate distribution)"
        trust_score = 75
    else:
        health_emoji = "🌟"
        health_text = "Excellent (Organic & highly distributed)"
        trust_score = 98

    lines = [
        f"🛡️ <b>ENGAGEMENT AUDIT REPORT</b>",
        f"<b>Target:</b> {html.escape(target_name)}",
        "",
        f"👥 <b>Unique Active Humans:</b> {unique_users:,}",
        f"❤️ <b>Total Organic Reactions:</b> {total_organic_reactions:,}",
        f"📊 <b>Avg Reactions/User:</b> {round(total_organic_reactions / unique_users, 1) if unique_users > 0 else 0}",
        "",
        f"<b>Audit Health:</b> {health_emoji} {health_text}",
        f"<b>Trust Score:</b> {trust_score}/100",
        "",
        "<i>Note: Bots and automated accounts are strictly excluded from these metrics to ensure fair auditing for advertisers.</i>"
    ]
    
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("forcewrapped"))
async def cmd_forcewrapped(message: types.Message):
    """Admin command to manually trigger the Weekly Wrapped report for testing."""
    if message.chat.type == "private":
        await message.answer("Use this inside a group to force trigger the weekly wrapped.")
        return
        
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.answer("Only admins can force-trigger wrapped.")
        return
        
    try:
        await cron_wrapped()
    except Exception as e:
        await message.answer(f"Error: {e}")


@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    """Show the Top Post of the day."""
    if message.chat.type == "private":
        await message.answer("Use this inside a group.")
        return
        
    chat_id = message.chat.id
    one_day_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat()
    
    pipeline = [
        {"$match": {"chat_id": chat_id, "active": True, "date": {"$gte": one_day_ago}}},
        {"$group": {"_id": "$message_id", "total": {"$sum": 1}}},
        {"$sort": {"total": -1}},
        {"$limit": 1}
    ]
    
    results = list(col_msg_reactions.aggregate(pipeline))
    if not results:
        await message.answer("No reactions recorded in the last 24 hours.")
        return
        
    top_msg_id = results[0]["_id"]
    total_rxn = results[0]["total"]
    
    chat_doc = col_chats.find_one({"chat_id": chat_id}) if col_chats is not None else None
    if chat_doc and chat_doc.get("username"):
        link = f"https://t.me/{chat_doc['username']}/{top_msg_id}"
    else:
        clean_chat_id = str(chat_id).replace("-100", "")
        link = f"https://t.me/c/{clean_chat_id}/{top_msg_id}"
        
    lines = [
        "🏆 <b>Top Post of the Day</b> 🏆\n",
        f"This <a href='{link}'>message</a> is on fire today with <b>{total_rxn}</b> reactions! 🔥"
    ]
    
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("setinvite"))
async def cmd_setinvite(message: types.Message):
    """Allow private group admins to set an invite link for the global leaderboard."""
    if message.chat.type == "private":
        await message.answer("Use this command inside your private group, not here.")
        return

    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.answer("Only group admins can set an invite link.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().startswith("https://t.me/"):
        await message.answer(
            "Usage: <code>/setinvite https://t.me/+yourlink</code>\n\nThis link will appear next to your group in the Global Leaderboard.",
            parse_mode="HTML"
        )
        return

    invite_link = parts[1].strip()
    if col_chats is not None:
        col_chats.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"invite_link": invite_link}},
            upsert=True
        )
    await message.answer("Invite link saved! Your group now appears as a clickable link in the Global Leaderboard.")


@dp.message(Command("roles"))
async def cmd_roles(message: types.Message):
    """List all gamification titles."""
    chat_doc = col_chats.find_one({"chat_id": message.chat.id}, {"_id": 0}) if col_chats is not None else None
    roles = get_roles_for_chat(chat_doc)
    
    lines = [
        "🎖️ <b>Reaction Roles & Titles</b>",
        "React to messages in this group to level up and unlock exclusive titles!\n"
    ]
    for threshold, title in reversed(roles):
        lines.append(f"• <b>{title}</b> : {threshold}+ reactions")
    lines.append("\nGroup Admins can change this list with <code>/themes</code> or <code>/setrole</code>.")
    lines.append("Check your current title by typing /stats!")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("themes"))
async def cmd_themes(message: types.Message):
    """List available gamification themes."""
    lines = ["🎨 <b>Available Gamification Themes</b>\n"]
    for k in THEMES.keys():
        lines.append(f"• <code>{k}</code>")
    lines.append("\nSet a theme using <code>/settheme &lt;theme_name&gt;</code>")
    lines.append("Or create a custom role using <code>/setrole &lt;count&gt; &lt;Title Name&gt;</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("settheme"))
async def cmd_settheme(message: types.Message):
    if message.chat.type == "private":
        await message.answer("Use this in a group.")
        return
        
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.answer("❌ Only group admins can change the theme.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/settheme &lt;theme_name&gt;</code>\nCheck /themes for a list.", parse_mode="HTML")
        return
        
    theme_name = parts[1].strip().lower()
    if theme_name not in THEMES:
        await message.answer(f"❌ Theme '{theme_name}' not found. Check /themes.")
        return
        
    if col_chats is not None:
        col_chats.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"theme": theme_name}, "$unset": {"custom_roles": ""}},
            upsert=True
        )
        
    await message.answer(f"✅ Theme set to <b>{theme_name}</b>!\nCheck /roles to see the new titles.", parse_mode="HTML")


@dp.message(Command("setrole"))
async def cmd_setrole(message: types.Message):
    if message.chat.type == "private":
        return
        
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.answer("❌ Only group admins can set custom roles.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Usage: <code>/setrole &lt;reactions_needed&gt; &lt;Title Name&gt;</code>\nExample: <code>/setrole 100 🌟 Super Fan</code>", parse_mode="HTML")
        return
        
    threshold = int(parts[1])
    title = parts[2].strip()
    
    if col_chats is not None:
        chat_doc = col_chats.find_one({"chat_id": message.chat.id}) or {}
        custom_roles = chat_doc.get("custom_roles", [])
        
        updated = False
        for r in custom_roles:
            if r["threshold"] == threshold:
                r["title"] = title
                updated = True
                break
        if not updated:
            custom_roles.append({"threshold": threshold, "title": title})
            
        col_chats.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"custom_roles": custom_roles}},
            upsert=True
        )
        
    await message.answer(f"✅ Custom role added: <b>{title}</b> at {threshold}+ reactions.\nCheck /roles to see your custom list.", parse_mode="HTML")


@dp.message(Command("uncover"))
async def cmd_uncover(message: types.Message):
    """Pick a random winner from reactions on a replied message."""
    if message.chat.type == "private":
        await message.answer("This command must be used in a group.")
        return

    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.answer("❌ Only group admins can run uncover.")
        return

    if not message.reply_to_message:
        await message.answer("❌ You must reply to the giveaway message with <code>/uncover</code>.", parse_mode="HTML")
        return

    if col_msg_reactions is None:
        await message.answer("Database is not configured.")
        return

    # Parse args: /uncover [count] [emoji]
    parts = message.text.split()
    count = 1
    target_emoji = None
    
    for part in parts[1:]:
        if part.isdigit():
            count = min(int(part), 50)
        else:
            target_emoji = part

    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id

    query = {"chat_id": chat_id, "message_id": msg_id, "active": True}
    if target_emoji:
        query["reaction"] = target_emoji
        
    pipeline = [
        {"$match": query},
        {"$sample": {"size": count}}
    ]
    winners_docs = list(col_msg_reactions.aggregate(pipeline))
    
    if not winners_docs:
        if target_emoji:
            await message.answer(f"No one has reacted with {target_emoji} to that message yet!")
        else:
            await message.answer("No one has reacted to that message yet!")
        return

    lines = ["🎉 <b>Giveaway Winner(s)!</b> 🎉\n"]
    for doc in winners_docs:
        w_id = doc["user_id"]
        w_react = doc["reaction"]
        info = await resolve_user(w_id, bot)
        display = html.escape(info.get("display_name", str(w_id)))
        uname = info.get("username")
        
        if uname:
            name_part = f'<a href="https://t.me/{uname}">{display}</a>'
        else:
            name_part = f'<a href="tg://user?id={w_id}">{display}</a>'
            
        lines.append(f"🏆 {name_part} (Reacted with {w_react})")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message_reaction()
async def on_reaction(reaction: types.MessageReactionUpdated):
    if col_reactions is None:
        return

    user = reaction.user

    # Golden Rule #1: Skip bot accounts entirely
    if is_bot_account(user):
        return

    chat_id = reaction.chat.id
    user_id = user.id

    # Cache metadata for leaderboard display
    save_chat_meta(reaction.chat)
    save_user_meta(user)

    def get_key(r):
        return r.emoji if r.type == "emoji" else f"custom_{r.custom_emoji_id}"

    new_r   = [get_key(r) for r in reaction.new_reaction]
    old_r   = [get_key(r) for r in reaction.old_reaction]
    added   = [r for r in new_r if r not in old_r]
    removed = [r for r in old_r if r not in new_r]

    for r in added:
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": "GLOBAL"},
            {"$inc": {"count": 1}}, upsert=True
        )
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": user_id},
            {"$inc": {"count": 1}}, upsert=True
        )
        # Store per-message reaction for raffles and mood graph
        if col_msg_reactions is not None:
            col_msg_reactions.update_one(
                {"chat_id": chat_id, "message_id": reaction.message_id, "user_id": user_id, "reaction": r},
                {"$set": {"active": True, "date": reaction.date.isoformat()}}, upsert=True
            )
            
            # Sentiment Alert Check
            if r in NEGATIVE_EMOJIS:
                neg_count = col_msg_reactions.count_documents({
                    "chat_id": chat_id, 
                    "message_id": reaction.message_id, 
                    "reaction": {"$in": list(NEGATIVE_EMOJIS)},
                    "active": True
                })
                # Alert at exactly 10 to avoid spamming
                if neg_count == 10:
                    alert_text = (
                        "⚠️ <b>Admin Alert: High Negative Sentiment</b>\n"
                        "A message in this group has suddenly received a high number of negative reactions.\n"
                        f"<a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{reaction.message_id}'>Go to message</a>"
                    )
                    try:
                        await bot.send_message(chat_id, alert_text, parse_mode="HTML")
                    except Exception:
                        pass

    if added and col_milestones is not None:
        try:
            total_cursor = col_reactions.aggregate([
                {"$match": {"chat_id": chat_id, "user_id": user_id}},
                {"$group": {"_id": None, "total": {"$sum": "$count"}}}
            ])
            user_total = 0
            for doc in total_cursor:
                user_total = doc["total"]
                
            if user_total > 0:
                chat_doc = col_chats.find_one({"chat_id": chat_id}, {"_id": 0}) if col_chats is not None else None
                roles = get_roles_for_chat(chat_doc)
                
                thresholds = [r[0] for r in roles if r[0] > 0]
                if user_total in thresholds:
                    doc_id = f"{chat_id}_{user_id}_{user_total}"
                    if not col_milestones.find_one({"_id": doc_id}):
                        col_milestones.insert_one({"_id": doc_id, "date": datetime.datetime.utcnow().isoformat()})
                        
                        new_title = get_title(user_total, roles)
                        info = await resolve_user(user_id, bot)
                        display = html.escape(info.get("display_name", str(user_id)))
                        uname = info.get("username")
                        
                        if uname:
                            user_link = f'<a href="https://t.me/{uname}">{display}</a>'
                        else:
                            user_link = f'<a href="tg://user?id={user_id}">{display}</a>'
                            
                        group_name = html.escape(reaction.chat.title or "the group")
                        
                        group_msg = f"🎉 <b>Level Up!</b>\n{user_link} just reached <b>{user_total}</b> reactions and unlocked the title:\n\n🏆 <b>{new_title}</b>"
                        try:
                            await bot.send_message(chat_id, group_msg, parse_mode="HTML")
                        except Exception:
                            pass
                            
                        pm_msg = f"🎉 <b>Congratulations!</b>\nYou just reached <b>{user_total}</b> reactions in <b>{group_name}</b> and unlocked a new role!\n\n🏆 <b>{new_title}</b>"
                        try:
                            await bot.send_message(user_id, pm_msg, parse_mode="HTML")
                        except Exception:
                            pass
        except Exception as e:
            print(f"Error processing milestones: {e}")

    for r in removed:
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": "GLOBAL"},
            {"$inc": {"count": -1}}
        )
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": user_id},
            {"$inc": {"count": -1}}
        )
        # Deactivate per-message reaction
        if col_msg_reactions is not None:
            col_msg_reactions.update_one(
                {"chat_id": chat_id, "message_id": reaction.message_id, "user_id": user_id, "reaction": r},
                {"$set": {"active": False}}
            )


# ── Webhook & Utility Endpoints ───────────────────────────────────────────────

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        if db is not None:
            try:
                db.debug_logs.insert_one({"log": update_data})
            except Exception:
                pass
        update = Update(**update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        import traceback
        error_msg = f"Error: {e}\n{traceback.format_exc()}"
        if db is not None:
            try:
                db.debug_logs.insert_one({"log": {"ERROR": error_msg}})
            except Exception:
                pass
        print(error_msg)
    return {"status": "ok"}


@app.get("/api/debug_logs")
async def debug_logs():
    if db is None:
        return {"error": "DB not connected"}
    logs = list(db.debug_logs.find({}, {"_id": 0}).sort("_id", -1).limit(5))
    return {"logs": logs}


@app.get("/api/setup_webhook")
async def setup_webhook(request: Request):
    webhook_url = f"https://{request.headers.get('host')}/api/webhook"
    allowed_updates = [
        "message", "edited_message", "callback_query",
        "inline_query", "message_reaction", "message_reaction_count"
    ]
    success = await bot.set_webhook(
        url=webhook_url,
        allowed_updates=allowed_updates,
        drop_pending_updates=True
    )
    if success:
        return {"status": "success", "message": f"Webhook set to {webhook_url} with reactions enabled!"}
    return {"status": "error", "message": "Failed. Check BOT_TOKEN."}


# ── API Data Endpoints (same data as bot — Golden Rule #2) ────────────────────

@app.get("/api/global_data")
async def api_global_data():
    """Global group leaderboard — mirrors /show command."""
    if col_reactions is None or col_chats is None:
        return {"error": "Database not configured"}

    results = list(col_reactions.aggregate([
        {"$match": {"user_id": "GLOBAL", "count": {"$gt": 0}}},
        {"$group": {"_id": "$chat_id", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}},
        {"$limit": 20}
    ]))

    groups = []
    for r in results:
        chat_id = r["_id"]
        doc     = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
        
        if not doc:
            try:
                chat = await bot.get_chat(chat_id)
                save_chat_meta(chat)
                doc = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
            except Exception:
                pass
                
        entry   = {"chat_id": chat_id, "total": r["total"], "title": str(chat_id), "url": None}
        if doc:
            entry["title"]    = doc.get("title", str(chat_id))
            username          = doc.get("username")
            invite            = doc.get("invite_link")
            entry["url"]      = f"https://t.me/{username}" if username else invite
        groups.append(entry)

    return {"groups": groups}


@app.get("/api/group_data/{chat_id}")
async def api_group_data(chat_id: int):
    """Per-group emoji + user leaderboard — mirrors /stats command."""
    if col_reactions is None:
        return {"error": "Database not configured"}

    emoji_results = list(col_reactions.aggregate([
        {"$match": {"chat_id": chat_id, "user_id": "GLOBAL", "count": {"$gt": 0}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]))

    user_results = list(col_reactions.aggregate([
        {"$match": {"chat_id": chat_id, "user_id": {"$ne": "GLOBAL"}, "count": {"$gt": 0}}},
        {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}},
        {"$limit": 10}
    ]))

    chat_doc   = col_chats.find_one({"chat_id": chat_id}, {"_id": 0}) if col_chats is not None else None
    
    # Fallback to API if not cached
    if not chat_doc and col_chats is not None:
        try:
            chat = await bot.get_chat(chat_id)
            save_chat_meta(chat)
            chat_doc = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
        except Exception:
            pass
            
    title = chat_doc.get("title", str(chat_id)) if chat_doc else str(chat_id)
    roles = get_roles_for_chat(chat_doc)

    users = []
    for u in user_results:
        info = await resolve_user(u["_id"], bot)
        users.append({
            "user_id":      u["_id"],
            "display_name": info.get("display_name", str(u["_id"])),
            "username":     info.get("username"),
            "total":        u["total"],
            "role":         get_title(u["total"], roles)
        })

    return {
        "title":  title,
        "emojis": [{"emoji": r["reaction"], "count": r["count"]} for r in emoji_results],
        "users":  users
    }


# ── Web Dashboard & Cron ─────────────────────────────────────────────────────────────

@app.get("/api/cron/wrapped")
async def cron_wrapped():
    if col_msg_reactions is None:
        return {"error": "DB not configured"}
        
    # Last 7 days
    seven_days_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    
    # 1. Total reactions per chat
    total_cur = col_msg_reactions.aggregate([
        {"$match": {"active": True, "date": {"$gte": seven_days_ago}}},
        {"$group": {"_id": "$chat_id", "total": {"$sum": 1}}}
    ])
    totals = {doc["_id"]: doc["total"] for doc in total_cur}
    
    if not totals:
        return {"status": "no data"}
        
    # 2. MVP per chat (user with most reactions)
    mvp_cur = col_msg_reactions.aggregate([
        {"$match": {"active": True, "date": {"$gte": seven_days_ago}}},
        {"$group": {"_id": {"chat_id": "$chat_id", "user_id": "$user_id"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$group": {"_id": "$_id.chat_id", "mvp": {"$first": "$_id.user_id"}, "mvp_count": {"$first": "$count"}}}
    ])
    mvps = {doc["_id"]: {"user_id": doc["mvp"], "count": doc["mvp_count"]} for doc in mvp_cur}
    
    # 3. Fav emoji per chat
    fav_cur = col_msg_reactions.aggregate([
        {"$match": {"active": True, "date": {"$gte": seven_days_ago}}},
        {"$group": {"_id": {"chat_id": "$chat_id", "reaction": "$reaction"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$group": {"_id": "$_id.chat_id", "fav": {"$first": "$_id.reaction"}}}
    ])
    favs = {doc["_id"]: doc["fav"] for doc in fav_cur}
    
    results = []
    
    for chat_id, total_rxn in totals.items():
        if chat_id not in mvps or chat_id not in favs:
            continue
            
        mvp_data = mvps[chat_id]
        fav_emoji = favs[chat_id]
        
        # Get MVP display
        info = await resolve_user(mvp_data["user_id"], bot)
        display = html.escape(info.get("display_name", str(mvp_data["user_id"])))
        uname = info.get("username")
        mvp_link = f'<a href="https://t.me/{uname}">{display}</a>' if uname else f'<a href="tg://user?id={mvp_data["user_id"]}">{display}</a>'
        
        # Get Chat Title
        chat_doc = col_chats.find_one({"chat_id": chat_id}) if col_chats is not None else None
        chat_title = html.escape(chat_doc.get("title", "this group")) if chat_doc else "this group"
        
        msg = (
            "🎁 <b>WEEKLY WRAPPED</b> 🎁\n\n"
            f"This week, <b>{chat_title}</b> had <b>{total_rxn:,}</b> reactions!\n"
            f"👑 <b>The MVP was {mvp_link}</b> ({mvp_data['count']} reactions).\n"
            f"🔥 <b>Our favorite emoji this week was {fav_emoji}!</b>\n\n"
            "<i>Keep reacting to climb the leaderboards next week!</i>"
        )
        
        try:
            await bot.send_message(chat_id, msg, parse_mode="HTML")
            results.append({"chat_id": chat_id, "status": "sent"})
        except Exception as e:
            results.append({"chat_id": chat_id, "status": f"failed: {e}"})
            
    return {"status": "ok", "processed": len(totals), "results": results}


@app.get("/")
async def serve_ui():
    html = r"""<!DOCTYPE html>

<html class="dark" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>TelePulse Analytics - Reaction Tracker Global Leaderboard</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@100..900&family=Plus+Jakarta+Sans:wght@100..900&family=Space+Grotesk:wght@100..900&display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
    tailwind.config = {
      darkMode: "class",
      theme: {
        extend: {
          "colors": {
            "on-primary-container": "#340080",
            "error": "#ffb4ab",
            "secondary-fixed": "#e1e0ff",
            "on-secondary-fixed-variant": "#2f2ebe",
            "tertiary-fixed": "#f0dbff",
            "primary-fixed-dim": "#d0bcff",
            "surface": "#101321",
            "surface-container-high": "#262938",
            "primary-fixed": "#e9ddff",
            "surface-bright": "#363848",
            "on-primary-fixed-variant": "#5516be",
            "on-primary": "#3c0091",
            "surface-container": "#1c1f2d",
            "surface-container-low": "#181b29",
            "on-tertiary-fixed": "#2c0051",
            "surface-container-lowest": "#0a0d1b",
            "primary": "#d0bcff",
            "on-tertiary-container": "#400071",
            "surface-dim": "#101321",
            "inverse-primary": "#6d3bd7",
            "on-secondary": "#1000a9",
            "background": "#101321",
            "on-secondary-container": "#b0b2ff",
            "on-error": "#690005",
            "on-tertiary": "#490080",
            "outline": "#958ea0",
            "on-tertiary-fixed-variant": "#6900b3",
            "on-background": "#e0e1f5",
            "secondary": "#c0c1ff",
            "on-error-container": "#ffdad6",
            "error-container": "#93000a",
            "tertiary": "#ddb7ff",
            "surface-tint": "#d0bcff",
            "primary-container": "#a078ff",
            "inverse-surface": "#e0e1f5",
            "secondary-fixed-dim": "#c0c1ff",
            "surface-variant": "#313443",
            "on-surface-variant": "#cbc3d7",
            "tertiary-container": "#b76dff",
            "on-primary-fixed": "#23005c",
            "outline-variant": "#494454",
            "on-secondary-fixed": "#07006c",
            "on-surface": "#e0e1f5",
            "inverse-on-surface": "#2d303f",
            "secondary-container": "#3131c0",
            "surface-container-highest": "#313443",
            "tertiary-fixed-dim": "#ddb7ff"
          },
          "borderRadius": {
            "DEFAULT": "0.25rem",
            "lg": "0.5rem",
            "xl": "0.75rem",
            "full": "9999px"
          },
          "spacing": {
            "space-md": "1rem",
            "space-lg": "1.5rem",
            "space-xs": "0.25rem",
            "space-sm": "0.5rem",
            "gutter": "1.25rem",
            "margin": "2rem",
            "space-xl": "2.5rem",
            "margin-mobile": "1rem",
            "gutter-mobile": "0.75rem"
          },
          "fontFamily": {
            "headline-lg-mobile": ["Space Grotesk"],
            "body-lg": ["Plus Jakarta Sans"],
            "headline-sm": ["Space Grotesk"],
            "display-xl-mobile": ["Space Grotesk"],
            "body-sm": ["Plus Jakarta Sans"],
            "headline-md": ["Space Grotesk"],
            "headline-lg": ["Space Grotesk"],
            "display-xl": ["Space Grotesk"],
            "metric-display": ["JetBrains Mono"],
            "metric-sub": ["JetBrains Mono"],
            "label-md": ["JetBrains Mono"],
            "body-md": ["Plus Jakarta Sans"],
            "label-sm": ["JetBrains Mono"]
          },
          "fontSize": {
            "headline-lg-mobile": ["26px", { "lineHeight": "32px", "letterSpacing": "-0.01em", "fontWeight": "600" }],
            "body-lg": ["16px", { "lineHeight": "24px", "fontWeight": "400" }],
            "headline-sm": ["20px", { "lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "600" }],
            "display-xl-mobile": ["36px", { "lineHeight": "44px", "letterSpacing": "-0.02em", "fontWeight": "700" }],
            "body-sm": ["12px", { "lineHeight": "18px", "fontWeight": "400" }],
            "headline-md": ["24px", { "lineHeight": "32px", "letterSpacing": "-0.015em", "fontWeight": "600" }],
            "headline-lg": ["36px", { "lineHeight": "44px", "letterSpacing": "-0.02em", "fontWeight": "600" }],
            "display-xl": ["56px", { "lineHeight": "64px", "letterSpacing": "-0.03em", "fontWeight": "700" }],
            "metric-display": ["32px", { "lineHeight": "36px", "letterSpacing": "-0.02em", "fontWeight": "700" }],
            "metric-sub": ["18px", { "lineHeight": "24px", "fontWeight": "600" }],
            "label-md": ["12px", { "lineHeight": "16px", "letterSpacing": "0.05em", "fontWeight": "500" }],
            "body-md": ["14px", { "lineHeight": "20px", "fontWeight": "400" }],
            "label-sm": ["10px", { "lineHeight": "14px", "letterSpacing": "0.08em", "fontWeight": "600" }]
          }
        },
      },
    }
  </script>
<style>
    .material-symbols-outlined {
      font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
      display: inline-block;
      vertical-align: middle;
      line-height: 1;
    }
    .custom-scroll::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: rgba(10, 13, 27, 0.6);
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: rgba(149, 142, 160, 0.25);
      border-radius: 9999px;
    }
    .custom-scroll::-webkit-scrollbar-thumb:hover {
      background: rgba(208, 188, 255, 0.4);
    }
  </style>
</head>
<body class="bg-[#0B0D14] text-on-surface font-body-md antialiased min-h-screen selection:bg-primary-container selection:text-on-primary-container overflow-x-hidden relative">
<!-- Atmospheric Glow Backgrounds -->
<div class="fixed inset-0 pointer-events-none z-0 overflow-hidden">
<div class="absolute -top-[15%] left-[20%] w-[680px] h-[680px] bg-[#6366F1]/10 rounded-full blur-[140px]"></div>
<div class="absolute top-[35%] -right-[10%] w-[550px] h-[550px] bg-[#8B5CF6]/10 rounded-full blur-[160px]"></div>
<div class="absolute bottom-[5%] left-[10%] w-[500px] h-[500px] bg-[#4338CA]/10 rounded-full blur-[130px]"></div>
<div class="absolute inset-0 bg-[radial-gradient(#1e1b4b_1px,transparent_1px)] [background-size:32px_32px] opacity-15"></div>
</div>
<!-- App Wrapper (SideNav + Content) -->
<div class="flex min-h-screen relative z-10">
<!-- JSON Anchor: SideNavBar -->
<aside class="fixed top-0 left-0 h-screen w-64 flex flex-col z-40 bg-surface-container-lowest border-r border-outline-variant/20 shadow-[4px_0_24px_rgba(0,0,0,0.4)] hidden xl:flex">
<div class="flex flex-col justify-between h-full p-space-md">
<!-- Brand Header -->
<div class="space-y-6">
<div class="flex items-center gap-3 px-2 py-1">
<div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-primary-container to-tertiary-container flex items-center justify-center shadow-[0_0_20px_rgba(160,120,255,0.35)]">
<span class="material-symbols-outlined text-surface-container-lowest font-bold text-2xl" data-icon="bolt">bolt</span>
</div>
<div>
<div class="text-headline-sm font-headline-sm font-bold text-on-surface tracking-tight leading-none">TelePulse OS</div>
<div class="text-label-sm font-label-sm text-primary tracking-widest mt-1">V2.4 Enterprise</div>
</div>
</div>
<!-- Quick CTA -->
<button class="w-full py-2.5 px-3 rounded-lg bg-gradient-to-r from-primary-container to-inverse-primary text-on-surface font-label-md text-label-md flex items-center justify-center gap-2 shadow-[0_4px_16px_rgba(109,59,215,0.4)] hover:shadow-[0_0_24px_rgba(160,120,255,0.6)] active:scale-[0.99] transition-all duration-150">
<span class="material-symbols-outlined text-lg" data-icon="rocket_launch">rocket_launch</span>
            Deploy Bot
          </button>
<!-- Navigation Links -->
<nav class="space-y-1.5 pt-2">
<!-- Active: Leaderboard -->
<a class="bg-surface-container-high text-primary border-l-2 border-primary rounded-r-lg font-label-md text-label-md px-3 py-2 flex items-center gap-3" href="#">
<span class="material-symbols-outlined text-lg text-primary" data-icon="leaderboard" style="font-variation-settings: 'FILL' 1;">leaderboard</span>
<span>Leaderboard</span>
</a>
<a class="text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high font-label-md text-label-md px-3 py-2 flex items-center gap-3 rounded-r-lg transition-all duration-150" href="#">
<span class="material-symbols-outlined text-lg" data-icon="speed">speed</span>
<span>Velocity Radar</span>
</a>
<a class="text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high font-label-md text-label-md px-3 py-2 flex items-center gap-3 rounded-r-lg transition-all duration-150" href="#">
<span class="material-symbols-outlined text-lg" data-icon="forum">forum</span>
<span>Channel Feed</span>
</a>
<a class="text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high font-label-md text-label-md px-3 py-2 flex items-center gap-3 rounded-r-lg transition-all duration-150" href="#">
<span class="material-symbols-outlined text-lg" data-icon="insights">insights</span>
<span>Reaction Matrix</span>
</a>
<a class="text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high font-label-md text-label-md px-3 py-2 flex items-center gap-3 rounded-r-lg transition-all duration-150" href="#">
<span class="material-symbols-outlined text-lg" data-icon="settings">settings</span>
<span>Settings</span>
</a>
</nav>
</div>
<!-- Footer Tab Links -->
<div class="border-t border-outline-variant/20 pt-4 space-y-1">
<div class="px-3 py-2 rounded-lg bg-surface-container/60 border border-outline-variant/30 mb-3 flex items-center justify-between">
<div class="flex items-center gap-2">
<div class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></div>
<span class="text-label-sm font-label-sm text-on-surface-variant">Cluster SYNC</span>
</div>
<span class="text-label-sm font-label-sm text-primary font-bold">99.98%</span>
</div>
<a class="text-on-surface-variant hover:text-on-surface font-label-md text-label-md px-3 py-2 flex items-center gap-2.5 rounded-lg hover:bg-surface-container-high transition-colors" href="#">
<span class="material-symbols-outlined text-base" data-icon="menu_book">menu_book</span>
<span>Docs</span>
</a>
<a class="text-on-surface-variant hover:text-on-surface font-label-md text-label-md px-3 py-2 flex items-center gap-2.5 rounded-lg hover:bg-surface-container-high transition-colors" href="#">
<span class="material-symbols-outlined text-base" data-icon="sensors">sensors</span>
<span>API Status</span>
</a>
</div>
</div>
</aside>
<!-- Main Content Canvas -->
<div class="flex-1 xl:ml-64 flex flex-col min-w-0">
<!-- JSON Anchor: TopNavBar -->
<header class="docked full-width top-0 sticky z-50 bg-surface-container-lowest/80 backdrop-blur-xl border-b border-outline-variant/30 shadow-[0_4px_24px_rgba(0,0,0,0.5)]">
<div class="flex justify-between items-center w-full px-space-lg py-space-sm max-w-full">
<!-- Left: Search Bar & Mobile Brand -->
<div class="flex items-center gap-4 flex-1 max-w-xl">
<div class="xl:hidden flex items-center gap-2">
<div class="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center">
<span class="material-symbols-outlined text-surface-container-lowest text-lg" data-icon="bolt">bolt</span>
</div>
<span class="text-headline-sm font-headline-sm tracking-tight text-on-surface font-bold">TelePulse</span>
</div>
<!-- Instant Search Bar -->
<div class="relative w-full max-w-md hidden sm:block">
<span class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-outline">
<span class="material-symbols-outlined text-lg" data-icon="search">search</span>
</span>
<input class="w-full pl-10 pr-12 py-1.5 bg-surface-container-low border border-outline-variant/30 focus:border-primary-container focus:ring-1 focus:ring-primary-container rounded-lg text-body-md font-body-md placeholder:text-outline/70 text-on-surface transition-all" placeholder="Search channels, topics, or @handles..." type="text"/>
<kbd class="absolute right-2.5 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[10px] font-label-sm bg-surface-container-high text-outline rounded border border-outline-variant/40">⌘K</kbd>
</div>
</div>
<!-- Middle Navigation Links (Web) -->
<div class="hidden lg:flex items-center space-x-6">
<a class="text-primary border-b-2 border-primary font-label-md text-label-md pb-1 flex items-center gap-1.5" href="#">
<span>Leaderboard</span>
</a>
<a class="text-on-surface-variant font-label-md text-label-md hover:text-on-surface hover:text-primary transition-colors duration-150" href="#">
<span>Telemetry</span>
</a>
<a class="text-on-surface-variant font-label-md text-label-md hover:text-on-surface hover:text-primary transition-colors duration-150" href="#">
<span>Intelligence</span>
</a>
<a class="text-on-surface-variant font-label-md text-label-md hover:text-on-surface hover:text-primary transition-colors duration-150 flex items-center gap-1" href="#">
<span>Alerts</span>
<span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
</a>
</div>
<!-- Right Trailing Actions -->
<div class="flex items-center gap-3">
<button class="p-2 text-on-surface-variant hover:text-primary hover:bg-surface-container-high/50 rounded-lg transition-colors duration-150 relative">
<span class="material-symbols-outlined text-xl" data-icon="notifications">notifications</span>
<span class="absolute top-1.5 right-1.5 w-2 h-2 bg-error rounded-full ring-2 ring-surface-container-lowest"></span>
</button>
<button class="p-2 text-on-surface-variant hover:text-primary hover:bg-surface-container-high/50 rounded-lg transition-colors duration-150">
<span class="material-symbols-outlined text-xl" data-icon="tune">tune</span>
</button>
<button class="hidden md:flex items-center gap-1.5 px-3 py-1.5 text-label-md font-label-md text-on-surface border border-outline-variant/40 rounded-lg hover:border-primary-container hover:bg-surface-container-high/50 active:scale-[0.98] transition-all duration-100">
<span class="material-symbols-outlined text-base" data-icon="ios_share">ios_share</span>
              Export Data
            </button>
<button class="flex items-center gap-1.5 px-3.5 py-1.5 text-label-md font-label-md bg-gradient-to-r from-primary-container to-secondary-container text-on-surface font-semibold rounded-lg shadow-[0_0_16px_rgba(160,120,255,0.35)] hover:shadow-[0_0_24px_rgba(160,120,255,0.5)] active:scale-[0.98] transition-all duration-100">
<span class="material-symbols-outlined text-base" data-icon="near_me">near_me</span>
              Connect Telegram
            </button>
<div class="w-8 h-8 rounded-full ring-2 ring-outline-variant/40 overflow-hidden ml-1">
<img class="w-full h-full object-cover" data-alt="Executive user profile avatar with crisp ambient violet backlighting and professional portrait framing against deep graphite backdrop." src="https://lh3.googleusercontent.com/aida-public/AB6AXuAaw-byPrZrXPVfrkiOIB6qLz5cunpcSYdcjxKB32A3y6gx0HkERLlPus2_Viaypon3b1gMt0sBoYU7ahzs3d5Zi4rbQsnjtmdiRkLD-Y5pBZ326RW2AqVJZsZ-C6qzQU7OBCtk2fu6lLijz56I40Y3dsyQWoMp0Nd_wBHnlVwT0zTT4eUHSX1MEAfhvBTpI8KviKgGxvyzIFsWiVJM4iP8ReMZ2ROpYat4VBESiSJ6U9YI_Og6tiTY0cC9Z9XCn3NjDUCkISvjvfX5"/>
</div>
</div>
</div>
</header>
<!-- Page Main Canvas -->
<main class="p-space-md sm:p-space-lg space-y-6 max-w-7xl w-full mx-auto">
<!-- Title & Live Telemetry Ribbon -->
<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-outline-variant/20 pb-4">
<div>
<div class="flex items-center gap-3">
<h1 class="text-headline-lg font-headline-lg text-on-surface tracking-tight">Reaction Tracker - Global Leaderboard</h1>
</div>
<p class="text-body-md font-body-md text-on-surface-variant mt-1">High-frequency real-time sentiment velocity across high-impact verified Telegram channels.</p>
</div>
<div class="flex items-center gap-2 self-start md:self-auto bg-surface-container-low px-3.5 py-1.5 rounded-full border border-emerald-500/30 shadow-[0_0_16px_rgba(16,185,129,0.15)]">
<span class="relative flex h-2.5 w-2.5">
<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
</span>
<span class="text-label-md font-label-md text-emerald-300 font-semibold tracking-wide">Live Sync • 4,821 Channels Tracked</span>
</div>
</div>
<!-- Top Stats Row -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
<!-- Stat 1 -->
<div class="bg-surface-container-low/70 backdrop-blur-md p-space-md rounded-xl border border-outline-variant/30 hover:border-primary/40 transition-all duration-200">
<div class="flex items-center justify-between text-outline text-label-md font-label-md">
<span>Total Reactions (24h)</span>
<span class="material-symbols-outlined text-primary text-lg" data-icon="electric_bolt">electric_bolt</span>
</div>
<div class="mt-2 text-metric-display font-metric-display text-on-surface font-bold">48.9M</div>
<div class="mt-1 flex items-center gap-1.5 text-label-sm font-label-sm text-emerald-400 font-semibold">
<span class="material-symbols-outlined text-sm" data-icon="trending_up">trending_up</span>
<span>+18.3% vs previous cycle</span>
</div>
</div>
<!-- Stat 2 -->
<div class="bg-surface-container-low/70 backdrop-blur-md p-space-md rounded-xl border border-outline-variant/30 hover:border-primary/40 transition-all duration-200">
<div class="flex items-center justify-between text-outline text-label-md font-label-md">
<span>Most Active Group</span>
<span class="material-symbols-outlined text-secondary text-lg" data-icon="stars">stars</span>
</div>
<div class="mt-2 text-headline-sm font-headline-sm text-on-surface truncate font-semibold" title="TON Developers Community">TON Developers</div>
<div class="mt-1 text-label-sm font-label-sm text-on-surface-variant flex items-center gap-1">
<span class="text-primary font-bold">8.4M reactions</span>
<span>• @ton_devs</span>
</div>
</div>
<!-- Stat 3 -->
<div class="bg-surface-container-low/70 backdrop-blur-md p-space-md rounded-xl border border-outline-variant/30 hover:border-primary/40 transition-all duration-200">
<div class="flex items-center justify-between text-outline text-label-md font-label-md">
<span>Top Reaction</span>
<span class="material-symbols-outlined text-amber-400 text-lg" data-icon="local_fire_department">local_fire_department</span>
</div>
<div class="mt-2 text-metric-display font-metric-display text-amber-300 font-bold flex items-center gap-2">
<span>🔥 Fire</span>
<span class="text-label-md font-label-md text-amber-400/80 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">38.4%</span>
</div>
<div class="mt-1 text-label-sm font-label-sm text-outline">18.7M fire stamps recorded</div>
</div>
<!-- Stat 4 -->
<div class="bg-surface-container-low/70 backdrop-blur-md p-space-md rounded-xl border border-outline-variant/30 hover:border-primary/40 transition-all duration-200">
<div class="flex items-center justify-between text-outline text-label-md font-label-md">
<span>Active Telegram Groups</span>
<span class="material-symbols-outlined text-primary text-lg" data-icon="hub">hub</span>
</div>
<div class="mt-2 text-metric-display font-metric-display text-on-surface font-bold">12,480</div>
<div class="mt-1 flex items-center gap-1 text-label-sm font-label-sm text-primary">
<span class="w-1.5 h-1.5 rounded-full bg-primary"></span>
<span>1,240 nodes added this week</span>
</div>
</div>
</div>
<!-- Filter & Search Command Strip -->
<div class="bg-surface-container-low/60 backdrop-blur-md p-space-sm sm:p-space-md rounded-xl border border-outline-variant/30 flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4">
<!-- Categories Filter Pills -->
<div class="flex items-center gap-1.5 overflow-x-auto custom-scroll pb-1 lg:pb-0">
<button class="px-3.5 py-1.5 rounded-lg text-label-md font-label-md bg-primary-container text-on-primary font-semibold shadow-[0_0_12px_rgba(160,120,255,0.4)] whitespace-nowrap">
              All Categories
            </button>
<button class="px-3.5 py-1.5 rounded-lg text-label-md font-label-md bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors whitespace-nowrap border border-outline-variant/20">
              Crypto & Web3
            </button>
<button class="px-3.5 py-1.5 rounded-lg text-label-md font-label-md bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors whitespace-nowrap border border-outline-variant/20">
              AI & Tech
            </button>
<button class="px-3.5 py-1.5 rounded-lg text-label-md font-label-md bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors whitespace-nowrap border border-outline-variant/20">
              Trading Alpha
            </button>
<button class="px-3.5 py-1.5 rounded-lg text-label-md font-label-md bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors whitespace-nowrap border border-outline-variant/20">
              Gaming & Meme
            </button>
</div>
<!-- Time Range Selector -->
<div class="flex items-center bg-surface-container-lowest p-1 rounded-lg border border-outline-variant/30 self-end lg:self-auto">
<button class="px-3 py-1 rounded text-label-sm font-label-sm bg-primary/20 text-primary font-bold shadow-inner">24 Hours</button>
<button class="px-3 py-1 rounded text-label-sm font-label-sm text-on-surface-variant hover:text-on-surface transition-colors">7 Days</button>
<button class="px-3 py-1 rounded text-label-sm font-label-sm text-on-surface-variant hover:text-on-surface transition-colors">30 Days</button>
<button class="px-3 py-1 rounded text-label-sm font-label-sm text-on-surface-variant hover:text-on-surface transition-colors">All Time</button>
</div>
</div>
<!-- Section 2: Top 3 Podium Spotlight -->
<section class="pt-4">
<div class="flex items-center justify-between mb-4">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-amber-400" data-icon="trophy" style="font-variation-settings: 'FILL' 1;">trophy</span>
<h2 class="text-headline-sm font-headline-sm text-on-surface font-bold">Podium Apex Nodes</h2>
</div>
<span class="text-label-sm font-label-sm text-outline">Real-Time Algorithmic Weighting</span>
</div>
<div class="grid grid-cols-1 md:grid-cols-3 gap-5 items-end">
<!-- 2nd Place: Silver (Left) -->
<div class="order-2 md:order-1 bg-surface-container-low/80 backdrop-blur-xl rounded-2xl p-space-lg border border-slate-400/30 relative overflow-hidden shadow-[0_12px_36px_-8px_rgba(0,0,0,0.7),0_0_24px_rgba(148,163,184,0.12)] hover:-translate-y-1 transition-transform duration-200">
<!-- Metallic Ambient Light -->
<div class="absolute -top-12 -right-12 w-36 h-36 bg-slate-300/10 rounded-full blur-2xl pointer-events-none"></div>
<div class="flex items-start justify-between">
<!-- Refined Silver Rank Badge -->
<div class="flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-400/15 border border-slate-300/40 text-slate-200 shadow-[0_0_12px_rgba(248,250,252,0.2)]">
<span class="material-symbols-outlined text-base" data-icon="workspace_premium" style="font-variation-settings: 'FILL' 1;">workspace_premium</span>
<span class="font-metric-sub text-metric-sub font-bold">#2 SILVER</span>
</div>
<!-- Private Capsule Badge -->
<div class="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-container-lowest/80 border border-outline-variant/40 text-on-surface-variant text-label-sm font-label-sm">
<span class="material-symbols-outlined text-xs text-amber-400" data-icon="lock" style="font-variation-settings: 'FILL' 1;">lock</span>
<span>Private</span>
</div>
</div>
<!-- Community Header -->
<div class="mt-4 flex items-center gap-3">
<div class="w-14 h-14 rounded-xl ring-2 ring-slate-400/50 overflow-hidden shadow-lg flex-shrink-0">
<img class="w-full h-full object-cover" data-alt="High tech financial trading node avatar with glowing silver laser charts and mathematical graphs on dark glass surface." src="https://lh3.googleusercontent.com/aida-public/AB6AXuA5ZfOkVPjaIFlnemD9GX1ncwou5Q0nKm4xT4L-ksK6iukotRheuixdi355vJw3ISJk4UUoK_yNPZ1ALy1b2jOTp0x0zM3yfFTnspz6Ikx6YPJeAIgzlpAqYhWkCEYHMzodMGuq9U90qWbn8g-9aGzMSo70dRq4QJGqUycAMhUBdxYQsUxXXTZWPfs0eELAxYCt5zQmL3ap0mcGoRBkUHu-MVB934WSalCo2zuIiGdICPAir8HCdgZILBt1bZvyFscJJfBuq8T9vtC2"/>
</div>
<div class="min-w-0">
<div class="flex items-center gap-1.5">
<h3 class="text-headline-sm font-headline-sm text-on-surface font-bold truncate">Alpha Signal Syndicate</h3>
<span class="material-symbols-outlined text-primary text-base" data-icon="verified" style="font-variation-settings: 'FILL' 1;">verified</span>
</div>
<div class="text-label-md font-label-md text-primary">@alphasignals</div>
</div>
</div>
<!-- Velocity Metric -->
<div class="mt-4 pt-3 border-t border-outline-variant/20 flex items-center justify-between">
<div>
<div class="text-label-sm font-label-sm text-outline">TOTAL REACTIONS</div>
<div class="text-metric-display font-metric-display text-slate-100 font-bold">6.2M</div>
</div>
<div class="text-right">
<div class="text-label-sm font-label-sm text-outline">VELOCITY</div>
<div class="text-label-md font-label-md text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">+19.8% 24h</div>
</div>
</div>
<!-- Mini Emojis Breakdown -->
<div class="mt-4 flex items-center gap-2">
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">🚀 2.4M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">⚡ 1.9M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">💎 1.2M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">🔥 0.7M</span>
</div>
</div>
<!-- 1st Place: Gold (Center / Elevated) -->
<div class="order-1 md:order-2 bg-gradient-to-b from-[#1C1A27] via-surface-container-low to-surface-container-lowest rounded-2xl p-space-lg border-2 border-amber-400/60 relative overflow-hidden shadow-[0_20px_50px_-10px_rgba(245,158,11,0.25),0_0_36px_rgba(245,158,11,0.2)] md:-translate-y-4 hover:-translate-y-5 transition-transform duration-200">
<!-- Golden Apex Halo Glow -->
<div class="absolute -top-16 left-1/2 -translate-x-1/2 w-56 h-56 bg-amber-400/15 rounded-full blur-3xl pointer-events-none"></div>
<div class="flex items-start justify-between relative z-10">
<!-- Apex Gold Rank Badge -->
<div class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-gradient-to-r from-amber-500/20 via-amber-400/30 to-amber-600/20 border border-amber-300 text-amber-200 shadow-[0_0_20px_rgba(245,158,11,0.4)]">
<span class="material-symbols-outlined text-lg text-amber-300 animate-bounce" data-icon="crown" style="font-variation-settings: 'FILL' 1;">crown</span>
<span class="font-metric-sub text-metric-sub font-extrabold tracking-wide">#1 APEX CHAMPION</span>
</div>
<!-- Public Capsule Badge -->
<div class="flex items-center gap-1 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-400/40 text-emerald-300 text-label-sm font-label-sm font-semibold shadow-[0_0_12px_rgba(16,185,129,0.2)]">
<span class="material-symbols-outlined text-xs" data-icon="public">public</span>
<span>Public</span>
</div>
</div>
<!-- Community Header -->
<div class="mt-5 flex items-center gap-3.5 relative z-10">
<div class="w-16 h-16 rounded-xl ring-2 ring-amber-400 overflow-hidden shadow-[0_0_20px_rgba(245,158,11,0.4)] flex-shrink-0">
<img class="w-full h-full object-cover" data-alt="Futuristic glowing golden blockchain cryptocurrency token emblem suspended inside dark holographic void with vibrant particle streams." src="https://lh3.googleusercontent.com/aida-public/AB6AXuCrX9WYVDwkBEQLDbkHBozVl8882wSO0hiwjceJtkOhWy8JCt8aPmNU2pWY6G1tx3vLT_bq7S0ZqFL5Iptmm-YRULODsusT0vBrhRM0RzzRjuDE2ySmUm2H_owYEFeHM0wmFyj4go_Atv0WQGQrm4hNbyPs5frQqOROmnq8ux_0uMfDg9sJBxCf0RagqckMOpf-EVo3p1o4fofnGgmxnXWvFwldPh3_lUfpjOw3Xd8URTH37GaHWDUby4JAR5lIWRlKz0dQnb55Wh7M"/>
</div>
<div class="min-w-0">
<div class="flex items-center gap-2">
<h3 class="text-headline-md font-headline-md text-amber-100 font-bold truncate">TON Innovators Hub</h3>
<span class="material-symbols-outlined text-amber-400 text-lg" data-icon="verified" style="font-variation-settings: 'FILL' 1;">verified</span>
</div>
<div class="text-label-md font-label-md text-amber-300/90 font-semibold">@ton_innovators</div>
</div>
</div>
<!-- Velocity Metric -->
<div class="mt-5 pt-3.5 border-t border-amber-400/20 flex items-center justify-between relative z-10">
<div>
<div class="text-label-sm font-label-sm text-amber-200/60 font-semibold tracking-wider">TOTAL REACTIONS</div>
<div class="text-metric-display font-metric-display text-white font-extrabold tracking-tight text-3xl">8.4M</div>
</div>
<div class="text-right">
<div class="text-label-sm font-label-sm text-amber-200/60 font-semibold">24H VELOCITY</div>
<div class="text-label-md font-label-md text-emerald-300 font-bold bg-emerald-500/20 px-2.5 py-1 rounded-md border border-emerald-400/40 shadow-[0_0_12px_rgba(16,185,129,0.3)]">
                    +24.5%
                  </div>
</div>
</div>
<!-- Mini Emojis Breakdown -->
<div class="mt-4 grid grid-cols-4 gap-1.5 relative z-10">
<div class="px-2 py-1.5 rounded-lg bg-surface-container-high/80 border border-outline-variant/30 text-center">
<div class="text-xs">🔥</div>
<div class="font-metric-sub text-label-sm font-bold text-on-surface">3.2M</div>
</div>
<div class="px-2 py-1.5 rounded-lg bg-surface-container-high/80 border border-outline-variant/30 text-center">
<div class="text-xs">🚀</div>
<div class="font-metric-sub text-label-sm font-bold text-on-surface">2.8M</div>
</div>
<div class="px-2 py-1.5 rounded-lg bg-surface-container-high/80 border border-outline-variant/30 text-center">
<div class="text-xs">⚡</div>
<div class="font-metric-sub text-label-sm font-bold text-on-surface">1.4M</div>
</div>
<div class="px-2 py-1.5 rounded-lg bg-surface-container-high/80 border border-outline-variant/30 text-center">
<div class="text-xs">❤️</div>
<div class="font-metric-sub text-label-sm font-bold text-on-surface">1.0M</div>
</div>
</div>
</div>
<!-- 3rd Place: Bronze (Right) -->
<div class="order-3 md:order-3 bg-surface-container-low/80 backdrop-blur-xl rounded-2xl p-space-lg border border-amber-700/40 relative overflow-hidden shadow-[0_12px_36px_-8px_rgba(0,0,0,0.7),0_0_24px_rgba(180,83,9,0.15)] hover:-translate-y-1 transition-transform duration-200">
<!-- Bronze Warm Light -->
<div class="absolute -top-12 -left-12 w-36 h-36 bg-amber-700/15 rounded-full blur-2xl pointer-events-none"></div>
<div class="flex items-start justify-between">
<!-- Raw Bronze Rank Badge -->
<div class="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-800/20 border border-amber-600/40 text-amber-200 shadow-[0_0_12px_rgba(180,83,9,0.2)]">
<span class="material-symbols-outlined text-base" data-icon="military_tech" style="font-variation-settings: 'FILL' 1;">military_tech</span>
<span class="font-metric-sub text-metric-sub font-bold">#3 BRONZE</span>
</div>
<!-- Public Capsule Badge -->
<div class="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-400/30 text-emerald-300 text-label-sm font-label-sm">
<span class="material-symbols-outlined text-xs" data-icon="public">public</span>
<span>Public</span>
</div>
</div>
<!-- Community Header -->
<div class="mt-4 flex items-center gap-3">
<div class="w-14 h-14 rounded-xl ring-2 ring-amber-700/60 overflow-hidden shadow-lg flex-shrink-0">
<img class="w-full h-full object-cover" data-alt="Stylized virtual game coin mascot rendered in liquid copper and dark bronze tones with dynamic cyber spark reflections." src="https://lh3.googleusercontent.com/aida-public/AB6AXuCjjfI1hF-gy7qbQ6eoKz7layQb6ZgvFu_CvSjUbV1rrsmx2lwsAR-amgOaNNCYxgy927VO8Sw6d0Oy8nDgzuXXetRqmGNoBO-PaqfCqCjD6rocMotjodW9agR2nNtW6QaiKgA4sbXUvdHNiJifWzsAZ1jxHNmCWs2Ovk8jpS5gzOVirsqE5Tlrpj0sUMJ_u6rHog-Pd7xJkggc4VRc7UIKOJ2q_ASShDuWpwfOiHqVBCHJ47KtEqxYIKku4q_G8CQMDvWCoMlv7tOD"/>
</div>
<div class="min-w-0">
<div class="flex items-center gap-1.5">
<h3 class="text-headline-sm font-headline-sm text-on-surface font-bold truncate">Notcoin Army Global</h3>
<span class="material-symbols-outlined text-primary text-base" data-icon="verified" style="font-variation-settings: 'FILL' 1;">verified</span>
</div>
<div class="text-label-md font-label-md text-primary">@notcoin_army</div>
</div>
</div>
<!-- Velocity Metric -->
<div class="mt-4 pt-3 border-t border-outline-variant/20 flex items-center justify-between">
<div>
<div class="text-label-sm font-label-sm text-outline">TOTAL REACTIONS</div>
<div class="text-metric-display font-metric-display text-amber-100 font-bold">5.1M</div>
</div>
<div class="text-right">
<div class="text-label-sm font-label-sm text-outline">VELOCITY</div>
<div class="text-label-md font-label-md text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">+14.2% 24h</div>
</div>
</div>
<!-- Mini Emojis Breakdown -->
<div class="mt-4 flex items-center gap-2">
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">💎 2.2M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">🔥 1.5M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">🚀 0.9M</span>
<span class="px-2 py-1 rounded bg-surface-container text-body-sm font-metric-sub">❤️ 0.5M</span>
</div>
</div>
</div>
</section>
<!-- Section 3: Interactive Leaderboard Table -->
<section class="space-y-4 pt-2">
<div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
<div>
<h2 class="text-headline-sm font-headline-sm text-on-surface font-bold">Live Community Index</h2>
<p class="text-body-sm font-body-sm text-outline">Ordered by dynamic sentiment velocity algorithm over the selected time slice.</p>
</div>
<div class="flex items-center gap-2">
<span class="text-label-sm font-label-sm text-outline">Table Density:</span>
<button class="px-2.5 py-1 text-label-sm font-label-sm bg-surface-container-high rounded text-on-surface font-semibold border border-outline-variant/30">Expanded</button>
<button class="px-2.5 py-1 text-label-sm font-label-sm bg-surface-container rounded text-outline hover:text-on-surface transition-colors">Compact</button>
</div>
</div>
<!-- Glassmorphism Table Container -->
<div class="bg-surface-container-low/70 backdrop-blur-xl rounded-2xl border border-outline-variant/30 overflow-hidden shadow-[0_16px_40px_rgba(0,0,0,0.6)]">
<div class="overflow-x-auto custom-scroll">
<table class="w-full text-left border-collapse">
<thead>
<tr class="border-b border-outline-variant/20 bg-surface-container-lowest/60 text-outline text-label-sm font-label-sm uppercase tracking-wider">
<th class="py-3.5 px-4 text-center w-16" scope="col">Rank</th>
<th class="py-3.5 px-4 min-w-[260px]" scope="col">Telegram Community</th>
<th class="py-3.5 px-4" scope="col">Status / Type</th>
<th class="py-3.5 px-4" scope="col">Member Count</th>
<th class="py-3.5 px-4" scope="col">Reaction Velocity (24h)</th>
<th class="py-3.5 px-4 min-w-[220px]" scope="col">Emoji Breakdown</th>
<th class="py-3.5 px-4 text-right" scope="col">Total Reactions</th>
<th class="py-3.5 px-4 text-center" scope="col">Actions</th>
</tr>
</thead>
<tbody class="divide-y divide-outline-variant/15 text-body-md font-body-md"></tbody>
</table>
</div>
<!-- Table Pagination & Summary Bar -->
<div class="p-space-md bg-surface-container-lowest/80 border-t border-outline-variant/20 flex flex-col sm:flex-row items-center justify-between gap-4 text-label-sm font-label-sm text-outline">
<div>
                Showing <span class="text-on-surface font-semibold">1 - 10</span> of <span class="text-on-surface font-semibold">4,821</span> monitored Telegram channels
              </div>
<div class="flex items-center gap-2">
<button class="px-3 py-1.5 rounded-lg bg-surface-container border border-outline-variant/30 text-outline hover:text-on-surface disabled:opacity-50" disabled="">
                  Previous
                </button>
<div class="flex items-center gap-1">
<button class="w-8 h-8 rounded-lg bg-primary-container text-on-primary font-bold">1</button>
<button class="w-8 h-8 rounded-lg bg-surface-container text-outline hover:text-on-surface transition-colors">2</button>
<button class="w-8 h-8 rounded-lg bg-surface-container text-outline hover:text-on-surface transition-colors">3</button>
<span class="px-1 text-outline">...</span>
<button class="w-8 h-8 rounded-lg bg-surface-container text-outline hover:text-on-surface transition-colors">482</button>
</div>
<button class="px-3 py-1.5 rounded-lg bg-surface-container border border-outline-variant/30 text-outline hover:text-on-surface transition-colors">
                  Next
                </button>
</div>
</div>
</div>
</section>
</main>
<!-- Sub-footer Operational telemetry -->
<footer class="mt-auto border-t border-outline-variant/20 bg-surface-container-lowest/50 py-4 px-space-lg text-center md:text-left flex flex-col md:flex-row items-center justify-between gap-3 text-label-sm font-label-sm text-outline">
<div class="flex items-center gap-3">
<span class="flex items-center gap-1.5">
<span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            Ingestion Pipeline Active
          </span>
<span>•</span>
<span>Latency: 142ms</span>
<span>•</span>
<span>WebSocket Feeds: Connected (6 Node Clusters)</span>
</div>
<div class="text-outline/70">
          TelePulse Analytics © 2025 Enterprise Intelligence System. All data cryptographic signatures intact.
        </div>
</footer>
</div>
</div>

<script>
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  async function loadGlobal() {
    const el = document.querySelector('tbody');
    try {
      const data = await fetch('/api/global_data').then(r=>r.json());
      if (!data.groups || data.groups.length === 0) {
        el.innerHTML = '<tr><td colspan="8" class="text-center py-10">No data found. Add the bot to a group!</td></tr>';
        return;
      }
      
      const rows = data.groups.map((g, i) => {
        let rankBadge = `<div class="w-8 h-8 mx-auto rounded-lg bg-surface-container border border-outline-variant/40 text-on-surface-variant flex items-center justify-center font-metric-sub text-metric-sub font-bold">${i+1}</div>`;
        if (i===0) rankBadge = `<div class="w-8 h-8 mx-auto rounded-lg bg-gradient-to-tr from-amber-500/20 to-amber-300/30 border border-amber-400 text-amber-300 flex items-center justify-center font-metric-sub text-metric-sub font-bold shadow-[0_0_12px_rgba(245,158,11,0.3)]">1</div>`;
        if (i===1) rankBadge = `<div class="w-8 h-8 mx-auto rounded-lg bg-slate-300/15 border border-slate-300/40 text-slate-200 flex items-center justify-center font-metric-sub text-metric-sub font-bold shadow-[0_0_10px_rgba(248,250,252,0.15)]">2</div>`;
        if (i===2) rankBadge = `<div class="w-8 h-8 mx-auto rounded-lg bg-amber-700/20 border border-amber-600/40 text-amber-200 flex items-center justify-center font-metric-sub text-metric-sub font-bold shadow-[0_0_10px_rgba(180,83,9,0.2)]">3</div>`;
        
        let titleHtml = g.url ? `<a href="${g.url}" target="_blank" class="hover:underline">${esc(g.title)}</a>` : esc(g.title);
        let pubBadge = g.url ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-400/30 text-label-sm font-label-sm font-semibold">Public</span>` : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-400/30 text-label-sm font-label-sm font-semibold">Private</span>`;
        
        return `<tr class="hover:bg-surface-container-high/40 transition-colors border-b border-outline-variant/10">
          <td class="py-4 px-4 text-center">${rankBadge}</td>
          <td class="py-4 px-4 font-bold text-on-surface">${titleHtml}</td>
          <td class="py-4 px-4">${pubBadge}</td>
          <td class="py-4 px-4 font-metric-sub text-label-md font-semibold text-on-surface">--</td>
          <td class="py-4 px-4"><div class="flex items-center gap-1.5 text-emerald-400 font-label-md font-bold">+Active</div></td>
          <td class="py-4 px-4 text-outline">Use /stats</td>
          <td class="py-4 px-4 text-right"><span class="inline-block px-3 py-1 rounded-lg bg-gradient-to-r from-primary-container to-secondary-container text-white font-metric-sub text-metric-sub font-bold shadow-[0_0_16px_rgba(160,120,255,0.4)]">${g.total.toLocaleString()}</span></td>
          <td class="py-4 px-4 text-center"></td>
        </tr>`;
      });
      el.innerHTML = rows.join('');
    } catch(e) {}
  }
  document.addEventListener("DOMContentLoaded", () => {
    loadGlobal();
    setInterval(loadGlobal, 10000);
  });
</script>
</body></html>"""
    return HTMLResponse(content=html)
