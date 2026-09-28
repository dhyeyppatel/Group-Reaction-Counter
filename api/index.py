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
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Reaction Tracker - Global Leaderboard</title>
<!-- Third-party script: Tailwind CSS CDN -->
<script src="https://cdn.tailwindcss.com"></script>
<!-- Third-party script: Lucide Icons -->
<script src="https://unpkg.com/lucide@latest"></script>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; background-color: #050505; color: #ededed; }
  .glass-card { background: rgba(20, 20, 20, 0.6); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }
  .gradient-text { background: linear-gradient(to right, #a855f7, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .custom-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
  .custom-scroll::-webkit-scrollbar-track { background: transparent; }
  .custom-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 9999px; }
  .custom-scroll::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
</style>
</head>
<body class="antialiased min-h-screen overflow-x-hidden flex flex-col relative">

<!-- Background Ambient Glow -->
<div class="fixed inset-0 pointer-events-none z-0 overflow-hidden">
  <div class="absolute -top-[10%] left-[20%] w-[500px] h-[500px] bg-purple-600/10 rounded-full blur-[120px]"></div>
  <div class="absolute bottom-[10%] -right-[10%] w-[600px] h-[600px] bg-blue-600/10 rounded-full blur-[150px]"></div>
</div>

<header class="border-b border-white/10 glass-card sticky top-0 z-50">
  <div class="max-w-6xl mx-auto px-6 py-5 flex flex-col sm:flex-row justify-between items-center gap-4">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-blue-500 flex items-center justify-center shadow-lg shadow-purple-500/20">
        <i data-lucide="zap" class="text-white w-5 h-5"></i>
      </div>
      <h1 class="text-2xl font-bold tracking-tight text-white">TelePulse</h1>
    </div>
    <div>
      <a href="http://t.me/dhyeyautofilterbot?startgroup=start" target="_blank" class="flex items-center gap-2 bg-white/10 hover:bg-white/20 border border-white/10 text-white px-5 py-2.5 rounded-lg font-medium transition-all">
        <i data-lucide="plus-circle" class="w-4 h-4"></i> Add to Telegram
      </a>
    </div>
  </div>
</header>

<main class="flex-1 max-w-6xl mx-auto w-full px-6 py-12 space-y-10 relative z-10">
  <div class="flex flex-col md:flex-row md:items-end justify-between gap-4">
    <div>
      <h2 class="text-4xl font-extrabold text-white mb-3 tracking-tight">Global <span class="gradient-text">Leaderboard</span></h2>
      <p class="text-gray-400 text-lg">Real-time engagement index of the most active communities.</p>
    </div>
    <div class="flex items-center gap-2 bg-emerald-500/10 px-4 py-2 rounded-full border border-emerald-500/20">
      <div class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
      <span class="text-sm font-semibold text-emerald-400">Live Sync</span>
    </div>
  </div>

  <div class="glass-card rounded-2xl overflow-hidden shadow-2xl">
    <div class="overflow-x-auto custom-scroll">
      <table class="w-full text-left border-collapse whitespace-nowrap">
        <thead>
          <tr class="border-b border-white/5 bg-white/5 text-gray-400 text-xs uppercase tracking-wider font-semibold">
            <th class="py-5 px-6 text-center w-20">Rank</th>
            <th class="py-5 px-6">Community</th>
            <th class="py-5 px-6">Status</th>
            <th class="py-5 px-6 text-right">Reactions</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-white/5 text-sm" id="leaderboard-body">
          <tr><td colspan="4" class="text-center py-16 text-gray-500"><div class="flex flex-col items-center gap-3 justify-center"><i data-lucide="loader-2" class="w-6 h-6 animate-spin"></i> Loading telemetry...</div></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</main>

<footer class="border-t border-white/10 glass-card py-10 mt-12 relative z-10">
  <div class="max-w-6xl mx-auto px-6 flex flex-col md:flex-row justify-between items-center gap-6">
    <div class="text-sm text-gray-500 flex items-center gap-2">
      <i data-lucide="shield-check" class="w-4 h-4"></i> &copy; 2026 TelePulse. Audited & Secure.
    </div>
    <div class="flex flex-wrap gap-6 text-sm">
      <a href="/privacy" class="text-gray-400 hover:text-white transition-colors flex items-center gap-1.5"><i data-lucide="file-text" class="w-4 h-4"></i> Privacy</a>
      <a href="/terms" class="text-gray-400 hover:text-white transition-colors flex items-center gap-1.5"><i data-lucide="scale" class="w-4 h-4"></i> Terms</a>
      <a href="/data" class="text-gray-400 hover:text-white transition-colors flex items-center gap-1.5"><i data-lucide="database" class="w-4 h-4"></i> Data Collection</a>
    </div>
  </div>
</footer>

<script>
  lucide.createIcons();
  
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  
  async function loadGlobal() {
    const el = document.getElementById('leaderboard-body');
    try {
      const data = await fetch('/api/global_data').then(r=>r.json());
      if (!data.groups || data.groups.length === 0) {
        el.innerHTML = '<tr><td colspan="4" class="text-center py-16 text-gray-500"><div class="flex flex-col items-center gap-3 justify-center"><i data-lucide="inbox" class="w-6 h-6"></i> No data found. Add the bot to a group!</div></td></tr>';
        lucide.createIcons();
        return;
      }
      
      const rows = data.groups.map((g, i) => {
        let rankClass = "w-10 h-10 mx-auto rounded-xl bg-white/5 border border-white/10 text-gray-300 flex items-center justify-center font-bold text-lg";
        if (i===0) rankClass = "w-10 h-10 mx-auto rounded-xl bg-gradient-to-tr from-yellow-600/30 to-yellow-400/20 border border-yellow-500/50 text-yellow-400 flex items-center justify-center font-bold text-lg shadow-[0_0_20px_rgba(234,179,8,0.3)]";
        if (i===1) rankClass = "w-10 h-10 mx-auto rounded-xl bg-gradient-to-tr from-slate-400/30 to-slate-300/20 border border-slate-400/50 text-slate-300 flex items-center justify-center font-bold text-lg shadow-[0_0_20px_rgba(148,163,184,0.3)]";
        if (i===2) rankClass = "w-10 h-10 mx-auto rounded-xl bg-gradient-to-tr from-orange-700/30 to-orange-500/20 border border-orange-500/50 text-orange-400 flex items-center justify-center font-bold text-lg shadow-[0_0_20px_rgba(249,115,22,0.3)]";
        
        let rankBadge = `<div class="${rankClass}">${i+1}</div>`;
        let titleHtml = g.url ? `<a href="${g.url}" target="_blank" class="font-bold text-lg text-white hover:text-blue-400 transition-colors flex items-center gap-2">${esc(g.title)} <i data-lucide="external-link" class="w-4 h-4 text-gray-500"></i></a>` : `<span class="font-bold text-lg text-white">${esc(g.title)}</span>`;
        let pubBadge = g.url ? `<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><i data-lucide="globe" class="w-3 h-3"></i> Public</span>` : `<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-white/5 text-gray-400 border border-white/10"><i data-lucide="lock" class="w-3 h-3"></i> Private</span>`;
        
        return `<tr class="hover:bg-white/5 transition-colors group">
          <td class="py-5 px-6 text-center">${rankBadge}</td>
          <td class="py-5 px-6">${titleHtml}</td>
          <td class="py-5 px-6">${pubBadge}</td>
          <td class="py-5 px-6 text-right">
            <span class="inline-flex items-center gap-2 px-4 py-1.5 rounded-lg bg-white/5 text-white font-mono text-base font-medium border border-white/10 group-hover:bg-purple-500/20 group-hover:border-purple-500/30 group-hover:text-purple-300 transition-colors">
              <i data-lucide="activity" class="w-4 h-4"></i> ${g.total.toLocaleString()}
            </span>
          </td>
        </tr>`;
      });
      el.innerHTML = rows.join('');
      lucide.createIcons();
    } catch(e) {
      console.error(e);
      el.innerHTML = '<tr><td colspan="4" class="text-center py-16 text-red-400"><div class="flex flex-col items-center gap-3 justify-center"><i data-lucide="alert-triangle" class="w-6 h-6"></i> Failed to load telemetry.</div></td></tr>';
      lucide.createIcons();
    }
  }
  document.addEventListener("DOMContentLoaded", () => {
    loadGlobal();
    setInterval(loadGlobal, 30000); // 30s refresh
  });
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/privacy")
async def privacy_policy():
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>Privacy Policy - Reaction Tracker</title>
<style>body{font-family:system-ui,sans-serif; background:#0f172a; color:#f8fafc; padding:2rem; max-width:800px; margin:auto;} a{color:#818cf8;}</style>
</head>
<body>
  <h1>Privacy Policy</h1>
  <p>Last Updated: Today</p>
  <p>We take your privacy seriously. This bot only tracks numeric reaction data to generate leaderboards.</p>
  <ul>
    <li>We do not read or store the contents of your messages.</li>
    <li>We only store: your Telegram User ID, your Telegram Display Name, and the Message ID that was reacted to.</li>
    <li>No marketing emails are sent, and no financial data is collected.</li>
  </ul>
  <p><a href="/">Back to Leaderboard</a></p>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/terms")
async def terms_conditions():
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>Terms & Conditions - Reaction Tracker</title>
<style>body{font-family:system-ui,sans-serif; background:#0f172a; color:#f8fafc; padding:2rem; max-width:800px; margin:auto;} a{color:#818cf8;}</style>
</head>
<body>
  <h1>Terms and Conditions</h1>
  <p>Last Updated: Today</p>
  <p>By adding this bot to your Telegram group, you agree to allow it to read message reactions for the purpose of maintaining a leaderboard.</p>
  <p>This service is provided "as is" without warranty. We reserve the right to remove groups from the global leaderboard for spamming fake reactions.</p>
  <p><a href="/">Back to Leaderboard</a></p>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/data")
async def data_collection():
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>Data Collection - Reaction Tracker</title>
<style>body{font-family:system-ui,sans-serif; background:#0f172a; color:#f8fafc; padding:2rem; max-width:800px; margin:auto;} a{color:#818cf8;}</style>
</head>
<body>
  <h1>Data Collection & Cookie Policy</h1>
  <p>Our website uses <strong>0 cookies</strong>. There is no tracking, session replay, or advertising SDK installed.</p>
  <h2>Third-Party Subprocessors</h2>
  <ul>
    <li><strong>Tailwind CSS (cdn.tailwindcss.com)</strong> - Used to style the web dashboard. May receive your IP address and User-Agent when your browser fetches the CSS.</li>
    <li><strong>Lucide Icons (unpkg.com)</strong> - Used to load UI icons. May receive your IP address and User-Agent when your browser fetches the JS.</li>
    <li><strong>Vercel</strong> - Hosts the bot API and web dashboard.</li>
    <li><strong>MongoDB Atlas</strong> - Stores the reaction counts securely.</li>
    <li><strong>Telegram API</strong> - Our core integration.</li>
  </ul>
  <p><a href="/">Back to Leaderboard</a></p>
</body>
</html>"""
    return HTMLResponse(content=html)
