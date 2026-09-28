// Command Name: /start
// BJS Only

if (chat.chat_type !== "private") {
    Bot.sendMessage("Hello! I track reactions in this group.\nUse /stats to see overall reactions, /top to see top reactors, and /mystats for your own stats.");
} else {
    Bot.sendMessage("Hello! I am a Group Reaction Counter Bot.\n\nAdd me to a supergroup to start tracking reactions!\n\nCommands in groups:\n/stats - Group totals\n/mystats - Your totals\n/top - Top reactors\n/message_stats - Reply to a message for its stats\n/settings - Admin configuration\n/reset - Admin reset");
}
