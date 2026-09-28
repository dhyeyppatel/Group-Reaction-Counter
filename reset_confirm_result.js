// Command Name: /reset_confirm_result
// BJS Only

if (!options || !options.result || !options.result.status) {
    return Bot.sendMessage("Error checking admin status. Ensure the bot is an admin in this group.");
}
var status = options.result.status;
if (status !== "administrator" && status !== "creator") {
    return Bot.sendMessage("❌ Only administrators can reset group statistics.");
}
var epoch = getEpoch(chat.chatid);
Bot.setProperty("grp_epoch_" + chat.chatid, epoch + 1, "integer");
Bot.sendMessage("✅ Group reaction statistics have been successfully reset. All previous data for this group has been invalidated.");
