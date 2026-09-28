# Telegram Group Reaction Tracker (Vercel + MongoDB)

This is a modern, fast, and serverless Telegram bot built with **Python**, **aiogram**, **FastAPI**, and **MongoDB**. It is designed specifically to be hosted on **Vercel** for free.

## Features
- ✅ Tracks all group reactions.
- ✅ Tracks who added/removed what reactions.
- ✅ Fast, serverless deployment (sleeps when idle, costing $0).
- ✅ Persistent storage using MongoDB Atlas.

## Deployment Instructions

### 1. Set up MongoDB Atlas (Database)
1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) and create a free shared cluster.
2. Under "Database Access", create a Database User with a password.
3. Under "Network Access", allow access from anywhere (`0.0.0.0/0`).
4. Go to your Cluster -> **Connect** -> **Connect your application**.
5. Copy your connection string (it looks like `mongodb+srv://<user>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority`).
6. Replace `<user>` and `<password>` with the credentials you just created. This is your `MONGO_URI`.

### 2. Deploy to Vercel
1. Push this repository to GitHub.
2. Go to [Vercel](https://vercel.com/) and click **Add New... -> Project**.
3. Import your GitHub repository.
4. Open the **Environment Variables** section and add the following:
   - `BOT_TOKEN`: Your Telegram Bot Token from @BotFather.
   - `MONGO_URI`: The connection string from MongoDB Atlas.
5. Click **Deploy**.

### 3. Connect Telegram to Vercel
Once Vercel finishes deploying, you will get a URL (e.g., `https://my-reaction-bot.vercel.app`).
1. Open your browser.
2. Go to `https://<YOUR_VERCEL_APP_URL>/api/setup_webhook`
3. You should see a success message: `{"status": "success", "message": "Webhook securely set..."}`

Your bot is now fully operational! Add it to a group as an Admin and try reacting to a message.
