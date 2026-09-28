# ⚡ Reaction Tracker Bot

A real-time Telegram engagement leaderboard bot that tracks user reactions, ranks groups, and powers giveaways. Built with FastAPI, MongoDB, and aiogram, designed specifically to run in serverless environments (like Vercel).

## 🚀 Core Features

1. **Global & Local Leaderboards**
   - Ranks the most active users within a single group (Local).
   - Ranks the most active communities against each other based on total reactions (Global).

2. **Web Dashboard Integration**
   - A stunning, live-updating Glassmorphism web dashboard.
   - Shows both the Global Group Leaderboard and detailed per-group stats (Emoji bar charts + Top Users).
   - Data is perfectly synced 1:1 with the Telegram bot.

3. **Reaction Giveaways (The Uncover Feature)**
   - Admins can host giveaways by asking users to react to a specific message.
   - The bot accurately tracks per-message reactions and can fairly pick 1 or more random winners directly from the people who reacted.

4. **Gamification & Custom Titles**
   - Users unlock exclusive titles based on their total reaction count (e.g., 100+ = Trend Setter 💫).
   - Titles are proudly displayed in both the `/stats` Telegram leaderboard and the web dashboard!
   - Admins can customize the theme using `/themes` (e.g., Space, Gaming, Chaotic) or create custom roles with `/setrole`.

5. **Sentiment Analysis & Mood Tracking**
   - Automatically categorizes emojis into Positive (❤️, 🔥), Negative (👎, 🤬), and Neutral.
   - The Web Dashboard displays a beautiful **Mood Graph** over time and an overall sentiment score.
   - **Admin Alerts:** If a specific message receives a sudden spike in negative reactions, the bot automatically warns the group admins.

6. **Anti-Bot & Clean Data**
   - **Golden Rule:** Any user account ending in "bot" (e.g., GroupHelpBot) or flagged as a bot by Telegram is completely ignored. Bot reactions will never pollute the leaderboards.

7. **Smart Name Resolution & UI/UX**
   - Converts raw IDs into hyperlinked names.
   - Users without a @username are linked using native `tg://user?id=` deep links.
   - Uses Telegram's native `<blockquote expandable>` to pack up to 50 users into a tiny, collapsible 3-line UI, preventing chat spam.

8. **Automated Weekly "Wrapped" Reports**
   - Think "Spotify Wrapped" but for Telegram communities!
   - Every Sunday night, the bot automatically broadcasts a gorgeous summary to the group.
   - Highlights the Total Weekly Reactions, crowns the Weekly MVP, and reveals the group's Favorite Emoji!

---

## 🤖 Bot Commands

### 1. /stats (Group Command)
*Displays the engagement statistics for the current group.*
- **Who can use it:** Anyone in the group.
- **Output:** 
  - **Emoji Leaderboard:** Shows the top emojis used in the group and their counts.
  - **Top Reactors:** Shows a ranked leaderboard (🥇, 🥈, 🥉) of the top 50 most active human users in the group.
- **Note:** Displays inside an expandable blockquote to prevent long scrolling.

### 2. /show (PM Command)
*Displays the Global Leaderboard of all communities tracked by the bot.*
- **Who can use it:** Anyone (best used in private messages with the bot).
- **Output:** Ranks up to 50 different Telegram groups/channels by their total reaction count. Public groups and private groups with invite links will be rendered as clickable hyperlinks.

### 3. /uncover (Admin Giveaways)
*Randomly picks a winner from the users who reacted to a specific message.*
- **Who can use it:** Group Admins only.
- **How to use:** You **must reply** to the target message (e.g., the giveaway announcement).
- **Syntax Options:**
  - /uncover : Picks 1 random winner from *any* reaction on the message.
  - /uncover 🎉 : Picks 1 random winner exclusively from the people who reacted with 🎉.
  - /uncover 3 : Picks 3 random winners.
  - /uncover 5 ❤️ : Picks 5 random winners who reacted with ❤️.

### 4. /roles (Gamification)
*Lists all the unlockable reaction titles.*
- **Who can use it:** Anyone.
- **Output:** A beautiful list of requirements to reach the next tier (e.g., 500+ for Community Pillar 🏛️).
- **Auto-Announcements:** When you hit a milestone, the bot will automatically drop a celebratory message in the group AND send you a private PM to congratulate you on your new role!

### 5. /themes (Group Command)
*Lists all available Gamification themes (e.g., Anime, Gaming, Crypto).*
- **Who can use it:** Anyone in the group.

### 6. /settheme <theme_name> (Admin Command)
*Changes the group's Gamification theme.*
- **Who can use it:** Group Admins only.
- **Example:** `/settheme cyberpunk`

### 7. /setrole <count> <title> (Admin Command)
*Creates a completely custom role for your group at a specific reaction threshold.*
- **Who can use it:** Group Admins only.
- **Example:** `/setrole 500 Super VIP 👑`

### 8. /mood (Analytics)
*Shows a visual breakdown of the community's emotional pulse!*
- **Who can use it:** Anyone.
- **Output:** If used in a group, it displays that group's emotional breakdown as a gorgeous bar graph. If used in the bot's private messages, it shows the **Global** mood across all tracked groups!
  ```text
  ╭─ 📊 COMMUNITY PULSE ─╮
  >   ❤️  LOVE      ████████  42%
  >   😂  FUN       ██████    31%
  >   🔥  HYPE      ████      19%
  >   😮  SURPRISE  ██         8%
    ✦ Overall vibe: HIGHLY POSITIVE ✨
  ╰───────────────────────╯
  ```

### 9. /audit [group] (Analytics)
*Provides a fair and comprehensive engagement audit for advertisers.*
- **Who can use it:** Anyone.
- **Output:** A trust score and health check on the group's engagement. It calculates the total *organic* unique users (bot reactions are strictly ignored) and checks if engagement is suspiciously concentrated (e.g., a few people spamming reactions) vs naturally distributed.
- **Example Use:** An advertiser can PM the bot `/audit @my_channel` to instantly verify how legitimate a channel's engagement is before buying ads!
- **Private Channels:** Advertisers can also audit private channels by using the invite link! (e.g. `/audit https://t.me/+xyz`). *Note: the channel admin must have saved their invite link to the bot using `/setinvite` first.*

### 10. /setinvite <url> (Admin Command)
*Attaches a join link to a private group so it can be clicked on the Global Leaderboard.*
- **Who can use it:** Group Admins only.
- **How to use:** `/setinvite https://t.me/+your_private_link`
- **Why use it?** If your group is private, the bot doesn't know how to link to it in the `/show` global dashboard. This command securely saves your invite link so others can discover and join your community from the leaderboard.

### 11. /start
*Standard onboarding message.*
- Explains basic bot functionality and reminds admins to give the bot admin privileges.

---

## 🛠 Technical Details

- **Tech Stack:** Python 3.9+, FastAPI, aiogram v3, Motor/PyMongo.
- **Database:** MongoDB Atlas (4 collections: eactions, chats, users, msg_reactions).
- **Serverless:** Built to handle the stateless, spin-down nature of Vercel. Global connections are cached, and the Webhook endpoint securely parses Telegram updates and feeds them directly into the aiogram Dispatcher.
- **Data Caching:** The bot aggressively caches chat and user metadata. If the cache is wiped or missing, it gracefully falls back to wait bot.get_chat() to fetch the real-time display name and username before rendering leaderboards.
