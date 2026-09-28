// Command Name: /reset_check_result
// BJS Only

if (!options || !options.result || !options.result.status) {
    return Bot.sendMessage("Error checking admin status. Ensure the bot is an admin in this group.");
}
var status = options.result.status;
if (status !== "administrator" && status !== "creator") {
    return Bot.sendMessage("❌ Only administrators can reset group statistics.");
}
Bot.sendMessage("⚠️ **WARNING**\nThis will permanently reset all reaction statistics (group, user, and message totals) for this group.\n\nReply with `/reset_confirm` to proceed.");
