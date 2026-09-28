// Command Name: /message_stats
// BJS Only

if (!requireGroup(chat)) return;
if (!request.reply_to_message) {
    return Bot.sendMessage("Please reply to a message with /message_stats to see its reactions.");
}
var epoch = getEpoch(chat.chatid);
var msgId = request.reply_to_message.message_id;
var prop = "msg_tot_" + chat.chatid + "_" + epoch + "_" + msgId;
var stats = Bot.getProperty(prop);
var msg = "💬 **Message Reaction Stats**\n\n" + formatStats(stats);
Bot.sendMessage(msg);
