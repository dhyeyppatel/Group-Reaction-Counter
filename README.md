# ⚡ React Meter Bot

A real-time Telegram engagement leaderboard bot that tracks user reactions, ranks groups and channels, and powers giveaways. Built with FastAPI, MongoDB, and aiogram, designed specifically to run in serverless environments (like Vercel).

**Developer Credits:** [@commonthread](https://t.me/commonthread)

## 🚀 Core Features

1. **Global & Local Leaderboards**
   - Ranks the most active users within a single group (Local).
   - Ranks the most active communities against each other based on total reactions (Global).

2. **Web Dashboard Integration**
   - A stunning, live-updating "Data-Dense" web dashboard (`ui.html`).
   - Shows the Global Leaderboard combining Top Groups and Top Channels seamlessly.
   - Optimistically caches data locally for instant, zero-delay load times.

3. **Reaction Giveaways (The Uncover Feature)**
   - Admins can host giveaways by asking users to react to a specific message.
   - The bot accurately tracks per-message reactions and can fairly pick 1 or more random winners directly from the people who reacted.

4. **Gamification & Custom Titles**
   - Users unlock exclusive titles based on their total reaction count (e.g., 100+ = Trend Setter 💫).
   - Titles are proudly displayed in the `/stats` Telegram leaderboard.
   - Admins can customize the theme using `/themes` (e.g., Space, Gaming, Chaotic) or create custom roles with `/setrole`.

5. **Sentiment Analysis & Mood Tracking**
   - Automatically categorizes emojis into Positive (❤️, 🔥), Negative (👎, 🤬), and Neutral.
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

Here is a complete list of every command available in the bot.

### 👥 Group Commands
These commands are meant to be used inside your group or channel.

#### 1. /stats
*Shows your personal standing in the group.*
- **Output:** Displays the current group's Top 3 Reactors and your personal rank.

#### 2. /show
*Shows the absolute top 50 most active members in the group!*
- **Output:** A densely packed, highly formatted `<blockquote expandable>` containing the top 50 users and their reaction counts.

#### 3. /uncover <emoji>
*Randomly picks a winner from people who reacted to the message you reply to!*
- **How to use:** Reply to a message with `/uncover 🎉` to pick a random user who reacted with 🎉 to that message.

#### 4. /roles
*Lists all the unlockable reaction titles.*
- **Auto-Announcements:** When you hit a milestone, the bot will automatically drop a celebratory message in the group AND send you a private PM to congratulate you on your new role!

#### 5. /themes
*Lists all available Gamification themes (e.g., Anime, Gaming, Crypto).* (Admin Command)

#### 6. /settheme <name>
*Changes the group's theme for the `/stats` output.* (Admin Command)

#### 7. /setrole <count> <Title>
*Lets group admins create custom unlockable titles.* (Admin Command)

#### 8. /mood
*Shows a visual breakdown of the group's emotional pulse as a beautiful bar graph.*

#### 9. /top
*Highlights the top 10 most highly reacted messages of the day in the group.*

#### 10. /setinvite <url>
*Attaches a join link to a private group so it can be clicked on the Global Web Leaderboard.* (Admin Command)

#### 11. /forcewrapped
*Manually triggers the Weekly Wrapped report for testing.* (Admin Command)

#### 12. /settings
*Manage group-specific features via an interactive menu (Announcements, Weekly Wrapped, Leaderboard Privacy, Sentiment Alerts, Minimal Mode, Language).* (Admin Command)

### 👤 Private Message (PM) Commands
These commands are meant to be used in a direct message with the bot.

#### 1. /start
*Standard onboarding message.*
- Displays a beautiful inline menu to navigate commands and features, along with Developer Credits.

#### 2. /audit [group]
*Provides a fair and comprehensive engagement audit for advertisers.*
- **How to use:** `/audit @my_group` or `/audit https://t.me/+xyz` (if private).
- **Note:** This feature only works for **Groups**. Channels are explicitly rejected because Telegram Channel reactions are fundamentally anonymous.
- **Output:** A trust score and health check on the group's engagement. Bot reactions are strictly ignored.

#### 3. /mood
*When used in PM, it shows the **Global** mood across all tracked groups!*

### 👑 Global Admin Commands
These commands are restricted to the bot owner (configured via the `ADMIN_ID` environment variable on Vercel).

#### 1. /reset_db
*Danger zone: Completely formats the MongoDB database.*
- Wipes all reactions, chats, messages, and user history globally across all communities.

---

## 🛠 Technical Details

- **Tech Stack:** Python 3.9+, FastAPI, aiogram v3, Motor/PyMongo.
- **Database:** MongoDB Atlas (4 collections: reactions, chats, users, msg_reactions).
- **Serverless:** Built to handle the stateless, spin-down nature of Vercel. Global connections are cached, and the Webhook endpoint securely parses Telegram updates and feeds them directly into the aiogram Dispatcher.
- **Data Caching:** The bot aggressively caches chat and user metadata. If the cache is wiped or missing, it gracefully falls back to `await bot.get_chat()` to fetch the real-time display name and username before rendering leaderboards.
