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

### 👥 Group Commands
These commands are meant to be used inside your group or channel.

#### 1. /stats (User Leaderboard)
*Shows your personal standing in the group.*
- **Output:** Displays the current group's Top 3 Reactors and your personal rank.

#### 2. /show (Group Leaderboard)
*Shows the absolute top 50 most active members in the group!*
- **Output:** A densely packed, highly formatted `<blockquote expandable>` containing the top 50 users and their reaction counts.

#### 3. /uncover <emoji> (Giveaways)
*Randomly picks a winner from people who reacted to the message you reply to!*
- **How to use:** Reply to a message with `/uncover 🎉` to pick a random user who reacted with 🎉 to that message.

#### 4. /roles (Gamification)
*Lists all the unlockable reaction titles.*
- **Auto-Announcements:** When you hit a milestone, the bot will automatically drop a celebratory message in the group AND send you a private PM to congratulate you on your new role!

#### 5. /themes (Admin Command)
*Lists all available Gamification themes (e.g., Anime, Gaming, Crypto).*

#### 6. /settheme <name> (Admin Command)
*Changes the group's theme for the `/stats` output.*

#### 7. /setrole <count> <Title> (Admin Command)
*Lets group admins create custom unlockable titles.*

#### 8. /mood (Analytics)
*Shows a visual breakdown of the group's emotional pulse as a beautiful bar graph.*

#### 9. /top (Content Discovery)
*Highlights the most highly reacted message of the day in the group.*

#### 10. /setinvite <url> (Admin Command)
*Attaches a join link to a private group so it can be clicked on the Global Leaderboard.*

#### 11. /forcewrapped (Admin Command)
*Manually triggers the Weekly Wrapped report for testing.*

### 👤 Private Message (PM) Commands
These commands are meant to be used in a direct message with the bot.

#### 1. /start
*Standard onboarding message.*
- Displays a beautiful inline menu to navigate commands and features.

#### 2. /audit [group] (Analytics)
*Provides a fair and comprehensive engagement audit for advertisers.*
- **How to use:** `/audit @my_channel` or `/audit https://t.me/+xyz` (if private).
- **Output:** A trust score and health check on the group's engagement. Bot reactions are strictly ignored.

#### 3. /mood (Analytics)
*When used in PM, it shows the **Global** mood across all tracked groups!*

---

## 🛠 Technical Details

- **Tech Stack:** Python 3.9+, FastAPI, aiogram v3, Motor/PyMongo.
- **Database:** MongoDB Atlas (4 collections: eactions, chats, users, msg_reactions).
- **Serverless:** Built to handle the stateless, spin-down nature of Vercel. Global connections are cached, and the Webhook endpoint securely parses Telegram updates and feeds them directly into the aiogram Dispatcher.
- **Data Caching:** The bot aggressively caches chat and user metadata. If the cache is wiped or missing, it gracefully falls back to wait bot.get_chat() to fetch the real-time display name and username before rendering leaderboards.
