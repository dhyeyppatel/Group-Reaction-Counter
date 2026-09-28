import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update
from aiogram.filters import Command
from pymongo import MongoClient

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


def resolve_user(uid) -> dict:
    """Return display info for a user_id from cache."""
    if col_users is None:
        return {"display_name": str(uid), "username": None}
    doc = col_users.find_one({"user_id": uid}, {"_id": 0})
    if doc:
        return doc
    return {"display_name": str(uid), "username": None}


# ── Bot Handlers ─────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I am a **Reaction Tracker Bot**.\n\n"
        "📌 *In a group:* Use `/stats` to see that group's emoji leaderboard + top reactors.\n"
        "📌 *In PM:* Use `/show` to see the Global Leaderboard of all groups.\n"
        "📌 *Private group admin:* Use `/setinvite https://t.me/+yourlink` to add your invite link.\n\n"
        "Make sure I am an **Admin** in your groups so I can see reactions!",
        parse_mode="Markdown"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if col_reactions is None:
        await message.answer("Database is not configured.")
        return

    if message.chat.type == "private":
        await message.answer(
            "ℹ️ `/stats` shows a specific group's stats.\nUse `/show` here to see the Global Leaderboard!",
            parse_mode="Markdown"
        )
        return

    save_chat_meta(message.chat)

    chat_id    = message.chat.id
    chat_title = message.chat.title or str(chat_id)

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

    if not emoji_results and not user_results:
        await message.answer("No reactions recorded yet in this group. React to some messages first!")
        return

    lines = [f"📊 **{chat_title} — Reaction Stats**\n"]

    if emoji_results:
        total = sum(r["count"] for r in emoji_results)
        lines.append("🎭 **Emoji Leaderboard:**")
        for r in emoji_results:
            lines.append(f"  {r['reaction']}  {r['count']}")
        lines.append(f"  ┄ Total: **{total}**\n")

    if user_results:
        medals = ["🥇", "🥈", "🥉"]
        lines.append("🏆 **Top Reactors in this Group:**")
        for i, u in enumerate(user_results):
            info    = resolve_user(u["_id"])
            uname   = info.get("username")
            display = f"@{uname}" if uname else info.get("display_name", str(u["_id"]))
            medal   = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"  {medal} {display} — {u['total']}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


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
        {"$limit": 20}
    ]))

    if not results:
        await message.answer("No group data yet. Add me to some groups and let people react!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines  = ["🌍 **Global Group Leaderboard**\n"]

    for i, r in enumerate(results):
        chat_id  = r["_id"]
        total    = r["total"]
        doc      = col_chats.find_one({"chat_id": chat_id}, {"_id": 0})
        medal    = medals[i] if i < 3 else f"{i + 1}."

        if doc:
            title    = doc.get("title", str(chat_id))
            username = doc.get("username")
            invite   = doc.get("invite_link")
            if username:
                name_part = f"[{title}](https://t.me/{username})"
            elif invite:
                name_part = f"[{title}]({invite})"
            else:
                name_part = title
        else:
            name_part = str(chat_id)

        lines.append(f"{medal} {name_part} — {total} reactions")

    await message.answer("\n".join(lines), parse_mode="Markdown")


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
            "Usage: `/setinvite https://t.me/+yourlink`\n\nThis link will appear next to your group in the Global Leaderboard.",
            parse_mode="Markdown"
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

    for r in removed:
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": "GLOBAL"},
            {"$inc": {"count": -1}}
        )
        col_reactions.update_one(
            {"chat_id": chat_id, "reaction": r, "user_id": user_id},
            {"$inc": {"count": -1}}
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

    doc   = col_chats.find_one({"chat_id": chat_id}, {"_id": 0}) if col_chats is not None else None
    title = doc.get("title", str(chat_id)) if doc else str(chat_id)

    users = []
    for u in user_results:
        info = resolve_user(u["_id"])
        users.append({
            "user_id":      u["_id"],
            "display_name": info.get("display_name", str(u["_id"])),
            "username":     info.get("username"),
            "total":        u["total"]
        })

    return {
        "title":  title,
        "emojis": [{"emoji": r["reaction"], "count": r["count"]} for r in emoji_results],
        "users":  users
    }


# ── Web Dashboard ─────────────────────────────────────────────────────────────

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

      if (data.users && data.users.length > 0) {
        const medals = ['🥇','🥈','🥉'];
        html += '<p class="section-title">Top Reactors</p>';
        data.users.forEach((u,i) => {
          const display = u.username ? '@'+u.username : u.display_name;
          const av      = initials(u.display_name || String(u.user_id));
          html += '<div class="user-row">'+
            '<div class="rank-badge '+rankClass(i)+'">'+(medals[i]||rankLabel(i))+'</div>'+
            '<div class="user-avatar">'+av+'</div>'+
            '<div class="user-name">'+esc(display)+'</div>'+
            '<div class="user-count">'+u.total.toLocaleString()+' rxn</div>'+
          '</div>';
        });
      }

      if (!html) { el.innerHTML = '<div class="empty">No reactions yet in this group.</div>'; return; }
      el.innerHTML = html;

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
