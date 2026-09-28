// Command Name: /mystats
// BJS Only

if (!requireGroup(chat)) return;
var epoch = getEpoch(chat.chatid);
var prop = "usr_tot_" + chat.chatid + "_" + epoch + "_" + user.telegramid;
var stats = Bot.getProperty(prop);
var msg = "👤 **Your Reaction Stats**\n\n" + formatStats(stats);
Bot.sendMessage(msg);
