// Command Name: /top
// BJS Only

if (!requireGroup(chat)) return;
var epoch = getEpoch(chat.chatid);
var prop = "grp_top_" + chat.chatid + "_" + epoch;
var topUsers = Bot.getProperty(prop) || {};

var sorted = [];
for (var uid in topUsers) {
    sorted.push({ id: uid, score: topUsers[uid] });
}
sorted.sort(function(a, b) { return b.score - a.score; });

if (sorted.length === 0) {
    return Bot.sendMessage("No reaction data yet for top users.");
}

var msg = "🏆 **Top Reactors**\n\n";
var max = sorted.length > 10 ? 10 : sorted.length;
for (var i=0; i<max; i++) {
    var uid = sorted[i].id;
    var score = sorted[i].score;
    var name = Bot.getProperty("usr_name_" + uid) || "User " + uid;
    msg += (i+1) + ". " + name + " : " + score + "\n";
}
Bot.sendMessage(msg);
