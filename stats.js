// Command Name: /stats
// BJS Only

if (!requireGroup(chat)) return;
var epoch = getEpoch(chat.chatid);
var prop = "grp_tot_" + chat.chatid + "_" + epoch;
var stats = Bot.getProperty(prop);
var msg = "📊 **Group Reaction Stats**\n\n" + formatStats(stats);
Bot.sendMessage(msg);
