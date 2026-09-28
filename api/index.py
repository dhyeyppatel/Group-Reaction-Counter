import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update
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
        "👋 Hello! I am a <b>Reaction Tracker Bot</b>.\n\n"
        "📌 <i>In a group:</i> Use /stats to see that group's emoji leaderboard + top reactors.\n"
        "📌 <i>In PM:</i> Use /show to see the Global Leaderboard of all groups.\n"
        "📌 <i>Roles & Titles:</i> Use /themes to customize roles or /roles to see them!\n"
        "📌 <i>Private group admin:</i> Use <code>/setinvite https://t.me/+yourlink</code> to add your invite link.\n\n"
        "Make sure I am an <b>Admin</b> in your groups so I can see reactions!",
        parse_mode="HTML"
    )


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
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reaction Tracker - Live Leaderboards</title>
  <meta name="description" content="Live Telegram group reaction leaderboards and top reactor rankings.">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:      #080c18;
      --surface: rgba(255,255,255,0.04);
      --border:  rgba(255,255,255,0.08);
      --indigo:  #6366f1;
      --purple:  #a855f7;
      --text:    #f1f5f9;
      --muted:   #64748b;
    }
    body {
      font-family: 'Outfit', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      background-image:
        radial-gradient(ellipse 80% 50% at 20% -10%, rgba(99,102,241,0.15) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 80% 110%, rgba(168,85,247,0.12) 0%, transparent 60%);
    }
    .page { max-width: 1000px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
    header { text-align: center; padding: 3rem 0 2.5rem; }
    header h1 {
      font-size: clamp(2rem, 5vw, 3.25rem);
      font-weight: 800;
      background: linear-gradient(135deg, #818cf8 0%, #c084fc 50%, #f472b6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      letter-spacing: -0.02em;
    }
    header p { color: var(--muted); margin-top: .6rem; font-size: 1.05rem; }

    .tabs {
      display: flex; gap: .5rem; margin-bottom: 2rem;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: .35rem;
    }
    .tab-btn {
      flex: 1; padding: .65rem 1rem; border: none; border-radius: 10px;
      background: transparent; color: var(--muted);
      font-family: 'Outfit', sans-serif; font-size: .95rem; font-weight: 600;
      cursor: pointer; transition: all .25s ease;
    }
    .tab-btn.active {
      background: linear-gradient(135deg, var(--indigo), var(--purple));
      color: #fff; box-shadow: 0 4px 20px rgba(99,102,241,.35);
    }
    .panel { display: none; }
    .panel.active { display: block; }

    .group-list { display: flex; flex-direction: column; gap: .75rem; }
    .group-row {
      display: flex; align-items: center; gap: 1rem;
      padding: 1rem 1.25rem; border-radius: 14px;
      background: var(--surface); border: 1px solid var(--border);
      cursor: pointer; transition: all .2s ease; text-decoration: none; color: inherit;
    }
    .group-row:hover { border-color: var(--indigo); background: rgba(99,102,241,.08); transform: translateX(4px); }

    .rank-badge {
      min-width: 2.2rem; height: 2.2rem; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: .85rem; flex-shrink: 0;
    }
    .rank-1 { background: linear-gradient(135deg, #f59e0b, #fbbf24); color: #1c1400; }
    .rank-2 { background: linear-gradient(135deg, #94a3b8, #cbd5e1); color: #1e293b; }
    .rank-3 { background: linear-gradient(135deg, #b45309, #d97706); color: #fff; }
    .rank-n { background: rgba(255,255,255,.07); color: var(--muted); }

    .group-info { flex: 1; min-width: 0; }
    .group-title { font-weight: 600; font-size: 1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .group-title a { color: var(--indigo); text-decoration: none; }
    .group-title a:hover { text-decoration: underline; }
    .group-sub { font-size: .78rem; color: var(--muted); margin-top: .15rem; }
    .group-total { font-size: 1.25rem; font-weight: 700; color: var(--purple); flex-shrink: 0; }

    .detail-header { display: flex; align-items: center; gap: .75rem; margin-bottom: 1.5rem; }
    .back-btn {
      background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
      padding: .45rem .9rem; color: var(--text); font-family: 'Outfit', sans-serif;
      font-weight: 600; cursor: pointer; font-size: .9rem; transition: all .2s;
    }
    .back-btn:hover { border-color: var(--indigo); }

    .section-title {
      font-size: .8rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .1em; color: var(--muted); margin-bottom: .75rem;
    }
    .emoji-row { margin-bottom: .6rem; }
    .emoji-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: .3rem; }
    .emoji-label { font-size: 1.5rem; }
    .emoji-count { font-weight: 700; color: var(--purple); font-size: 1.1rem; }
    .bar-track { height: 8px; border-radius: 99px; background: rgba(255,255,255,.06); overflow: hidden; }
    .bar-fill {
      height: 100%; border-radius: 99px;
      background: linear-gradient(90deg, var(--indigo), var(--purple));
      box-shadow: 0 0 12px rgba(168,85,247,.4);
      width: 0; transition: width 0.8s cubic-bezier(.4,0,.2,1);
    }
    .user-row {
      display: flex; align-items: center; gap: .9rem; padding: .8rem 1rem;
      border-radius: 12px; background: var(--surface); border: 1px solid var(--border);
      margin-bottom: .5rem; transition: all .2s;
    }
    .user-row:hover { border-color: rgba(99,102,241,.4); }
    .user-avatar {
      width: 2rem; height: 2rem; border-radius: 50%;
      background: linear-gradient(135deg, var(--indigo), var(--purple));
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: .8rem; flex-shrink: 0;
    }
    .user-name { flex: 1; font-weight: 600; font-size: .95rem; }
    .user-count { font-weight: 700; color: var(--indigo); }

    .spinner {
      width: 40px; height: 40px;
      border: 3px solid rgba(255,255,255,.1); border-top-color: var(--purple);
      border-radius: 50%; animation: spin .8s linear infinite; margin: 3rem auto;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .empty { text-align: center; color: var(--muted); padding: 3rem 1rem; font-size: .95rem; line-height: 1.6; }
    .refresh-note { text-align: center; color: var(--muted); font-size: .78rem; margin-top: 2rem; }
    .mb-6 { margin-bottom: 1.5rem; }
  </style>
</head>
<body>
<div class="page">
  <header>
    <h1>Reaction Tracker</h1>
    <p>Live Telegram engagement leaderboards - powered by real reactions</p>
  </header>

  <div class="tabs">
    <button class="tab-btn active" id="tab-global" onclick="switchTab('global')">Global Group Leaderboard</button>
    <button class="tab-btn"        id="tab-group"  onclick="switchTab('group')">Group Detail</button>
  </div>

  <div class="panel active" id="panel-global">
    <div id="global-list"><div class="spinner"></div></div>
  </div>

  <div class="panel" id="panel-group">
    <div class="detail-header">
      <button class="back-btn" onclick="switchTab('global')">Back</button>
      <span id="detail-title" style="font-weight:700;font-size:1.1rem;"></span>
    </div>
    <div id="detail-content"><div class="spinner"></div></div>
  </div>

  <p class="refresh-note">Auto-refreshes every 10 seconds - Same data as the bot</p>
</div>

<script>
  let activeTab = 'global';
  let refreshTimer;

  function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('panel-' + tab).classList.add('active');
    document.getElementById('tab-'   + tab).classList.add('active');
    clearInterval(refreshTimer);
    if (tab === 'global') {
      loadGlobal();
      refreshTimer = setInterval(loadGlobal, 10000);
    }
  }

  function rankClass(i) { return ['rank-1','rank-2','rank-3'][i] || 'rank-n'; }
  function rankLabel(i) { return ['#1','#2','#3'][i] || (i+1); }
  function initials(t)  { return String(t).split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase() || '?'; }
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  async function loadGlobal() {
    const el = document.getElementById('global-list');
    try {
      const data = await fetch('/api/global_data').then(r=>r.json());
      if (data.error || !data.groups || data.groups.length === 0) {
        el.innerHTML = '<div class="empty">No groups tracked yet.<br>Add the bot to a group, make it admin, and start reacting!</div>';
        return;
      }
      const medals = ['🥇','🥈','🥉'];
      el.innerHTML = '<div class="group-list">' +
        data.groups.map((g,i) => {
          const titleHtml = g.url
            ? '<a href="'+g.url+'" target="_blank" rel="noopener">'+esc(g.title)+'</a>'
            : esc(g.title);
          return '<div class="group-row" onclick="loadGroup('+g.chat_id+',\''+esc(g.title)+'\')">'+
            '<div class="rank-badge '+rankClass(i)+'">'+(medals[i]||rankLabel(i))+'</div>'+
            '<div class="group-info">'+
              '<div class="group-title">'+titleHtml+'</div>'+
              '<div class="group-sub">'+(g.url ? 'Public - click name to join' : 'Private group')+'</div>'+
            '</div>'+
            '<div class="group-total">'+g.total.toLocaleString()+' rxn</div>'+
          '</div>';
        }).join('') + '</div>';
    } catch(e) {
      el.innerHTML = '<div class="empty">Failed to load. Please refresh.</div>';
    }
  }

  async function loadGroup(chatId, title) {
    switchTab('group');
    document.getElementById('detail-title').textContent = title;
    const el = document.getElementById('detail-content');
    el.innerHTML = '<div class="spinner"></div>';
    try {
      const data = await fetch('/api/group_data/'+chatId).then(r=>r.json());
      if (data.error) { el.innerHTML = '<div class="empty">Error loading group data.</div>'; return; }

      let html = '';
      if (data.emojis && data.emojis.length > 0) {
        const maxC = Math.max(...data.emojis.map(e=>e.count));
        html += '<p class="section-title">Emoji Leaderboard</p><div class="mb-6">';
        data.emojis.forEach(e => {
          const pct   = (e.count / maxC * 100).toFixed(1);
          const emoji = e.emoji.startsWith('custom_') ? '🌟' : e.emoji;
          html += '<div class="emoji-row">'+
            '<div class="emoji-meta"><span class="emoji-label">'+emoji+'</span><span class="emoji-count">'+e.count.toLocaleString()+'</span></div>'+
            '<div class="bar-track"><div class="bar-fill" data-pct="'+pct+'"></div></div>'+
          '</div>';
        });
        html += '</div>';
      }

      // Sentiment Section
      if (data.sentiment && (data.sentiment.positive > 0 || data.sentiment.negative > 0)) {
        html += '<p class="section-title">Community Mood</p>';
        html += '<div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 15px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between;">';
        
        let scoreColor = data.sentiment.score >= 80 ? '#4ade80' : (data.sentiment.score >= 50 ? '#fbbf24' : '#ef4444');
        
        html += '<div>';
        html += '<div style="font-size: 0.9rem; color: var(--muted);">Positivity Score</div>';
        html += '<div style="font-size: 1.8rem; font-weight: 700; color: '+scoreColor+';">' + data.sentiment.score + '%</div>';
        html += '</div>';
        
        html += '<div style="text-align: right;">';
        html += '<div style="font-size: 0.85rem; color: var(--muted); margin-bottom: 4px;">❤️ Positive: <span style="color:#fff;">'+data.sentiment.positive+'</span></div>';
        html += '<div style="font-size: 0.85rem; color: var(--muted); margin-bottom: 4px;">🤬 Negative: <span style="color:#fff;">'+data.sentiment.negative+'</span></div>';
        html += '<div style="font-size: 0.85rem; color: var(--muted);">😐 Neutral: <span style="color:#fff;">'+data.sentiment.neutral+'</span></div>';
        html += '</div>';
        html += '</div>';
      }

      // Mood Chart
      if (data.mood_chart && data.mood_chart.length > 0) {
        html += '<p class="section-title">Mood Over Time (Last 7 Days)</p>';
        html += '<div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 15px; margin-bottom: 20px;">';
        html += '<canvas id="moodChart" height="150"></canvas>';
        html += '</div>';
      }

      if (data.users && data.users.length > 0) {
        const medals = ['🥇','🥈','🥉'];
        html += '<p class="section-title">Top Reactors</p>';
        data.users.forEach((u,i) => {
          const display = u.username ? '@'+u.username : u.display_name;
          const userUrl = u.username ? 'https://t.me/'+u.username : 'tg://user?id='+u.user_id;
          const av      = initials(u.display_name || String(u.user_id));
          html += '<div class="user-row">'+
            '<div class="rank-badge '+rankClass(i)+'">'+(medals[i]||rankLabel(i))+'</div>'+
            '<div class="user-avatar">'+av+'</div>'+
            '<div class="user-name"><a href="'+userUrl+'" style="color:inherit; text-decoration:none;">'+esc(display)+'</a> <span style="color:var(--muted); font-size:0.85rem; font-weight:400; margin-left:6px;">• '+esc(u.role)+'</span></div>'+
            '<div class="user-count">'+u.total.toLocaleString()+' rxn</div>'+
          '</div>';
        });
      }

      if (!html) { el.innerHTML = '<div class="empty">No reactions yet in this group.</div>'; return; }
      el.innerHTML = html;
      
      // Render Chart
      if (data.mood_chart && data.mood_chart.length > 0) {
        const ctx = document.getElementById('moodChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.mood_chart.map(d => d.date.substring(5)),
                datasets: [
                    {
                        label: 'Positive',
                        data: data.mood_chart.map(d => d.positive),
                        borderColor: '#4ade80',
                        backgroundColor: 'rgba(74, 222, 128, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Negative',
                        data: data.mood_chart.map(d => d.negative),
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        tension: 0.4,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: { legend: { labels: { color: 'rgba(255,255,255,0.7)' } } },
                scales: {
                    x: { ticks: { color: 'rgba(255,255,255,0.5)' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y: { ticks: { color: 'rgba(255,255,255,0.5)' }, grid: { color: 'rgba(255,255,255,0.05)' } }
                }
            }
        });
      }

      requestAnimationFrame(() => {
        document.querySelectorAll('.bar-fill[data-pct]').forEach((b,i) => {
          setTimeout(() => { b.style.width = b.dataset.pct + '%'; }, 60 * i);
        });
      });
    } catch(e) {
      el.innerHTML = '<div class="empty">Failed to load group data.</div>';
    }
  }

  loadGlobal();
  refreshTimer = setInterval(loadGlobal, 10000);
</script>
</body>
</html>"""
    return HTMLResponse(content=html)
