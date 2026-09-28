// Command Name: /debug_update_result
// BJS Only

if (!options || !options.result || !options.result.status) return;
var status = options.result.status;
if (status !== "administrator" && status !== "creator") {
    return Bot.sendMessage("❌ Only administrators can use this command.");
}

// Dump the tgUpdate to chat for debugging
// Since this is triggered by the /debug_update message itself, it will dump the Message update.
// To debug reactions, developers should check the Bots.Business "Errors / Logs" tab.
var debugInfo = JSON.stringify(tgUpdate, null, 2);
Bot.sendMessage("🛠 **Debug Info (Current Update):**\n```json\n" + debugInfo + "\n```");
