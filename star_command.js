// Command Name: *
// BJS Only

if (!tgUpdate) return; // Exit if no update

var update = tgUpdate;
var mr = update.message_reaction;
var mrc = update.message_reaction_count;

if (mr) {
    var chatId = mr.chat.id;
    var msgId = mr.message_id;
    
    // Check if tracking is disabled
    var settings = Bot.getProperty("grp_settings_" + chatId);
    if (settings && settings.disabled) return;

    var epoch = getEpoch(chatId);
    var actUser = mr.user || mr.actor_chat; 
    var userId = actUser ? actUser.id : "anonymous";
    var userName = actUser ? (actUser.first_name || actUser.title || "User") : "Anonymous";
    
    var oldR = mr.old_reaction || [];
    var newR = mr.new_reaction || [];
    
    var oldKeys = [];
    for (var i=0; i<oldR.length; i++) oldKeys.push(getReactionKey(oldR[i]));
    
    var newKeys = [];
    for (var i=0; i<newR.length; i++) newKeys.push(getReactionKey(newR[i]));
    
    var removed = [];
    for (var i=0; i<oldKeys.length; i++) {
        if (newKeys.indexOf(oldKeys[i]) === -1) removed.push(oldKeys[i]);
    }
    
    var added = [];
    for (var i=0; i<newKeys.length; i++) {
        if (oldKeys.indexOf(newKeys[i]) === -1) added.push(newKeys[i]);
    }
    
    if (added.length === 0 && removed.length === 0) return;

    // 1. Group Totals
    var groupProp = "grp_tot_" + chatId + "_" + epoch;
    var groupTotals = Bot.getProperty(groupProp) || {};
    for (var i=0; i<removed.length; i++) {
        var k = removed[i];
        if (groupTotals[k]) groupTotals[k]--;
        if (groupTotals[k] <= 0) delete groupTotals[k];
    }
    for (var i=0; i<added.length; i++) {
        var k = added[i];
        groupTotals[k] = (groupTotals[k] || 0) + 1;
    }
    Bot.setProperty(groupProp, groupTotals, "json");
    
    // 2. Message Totals
    if (!settings || !settings.disableMessageStats) {
        var msgProp = "msg_tot_" + chatId + "_" + epoch + "_" + msgId;
        var msgTotals = Bot.getProperty(msgProp) || {};
        for (var i=0; i<removed.length; i++) {
            var k = removed[i];
            if (msgTotals[k]) msgTotals[k]--;
            if (msgTotals[k] <= 0) delete msgTotals[k];
        }
        for (var i=0; i<added.length; i++) {
            var k = added[i];
            msgTotals[k] = (msgTotals[k] || 0) + 1;
        }
        Bot.setProperty(msgProp, msgTotals, "json");
    }

    // 3. User Totals & Top Cache
    if (userId !== "anonymous" && (!settings || !settings.disableUserStats)) {
        var userProp = "usr_tot_" + chatId + "_" + epoch + "_" + userId;
        var userTotals = Bot.getProperty(userProp) || {};
        var userNetActivity = 0; // for top leaderboard
        
        for (var i=0; i<removed.length; i++) {
            var k = removed[i];
            if (userTotals[k]) {
                userTotals[k]--;
                userNetActivity--;
            }
            if (userTotals[k] <= 0) delete userTotals[k];
        }
        for (var i=0; i<added.length; i++) {
            var k = added[i];
            userTotals[k] = (userTotals[k] || 0) + 1;
            userNetActivity++;
        }
        Bot.setProperty(userProp, userTotals, "json");
        Bot.setProperty("usr_name_" + userId, userName, "string"); // cache name
        
        // Update top users leaderboard efficiently
        if (userNetActivity !== 0) {
            var topProp = "grp_top_" + chatId + "_" + epoch;
            var topUsers = Bot.getProperty(topProp) || {};
            var currentScore = topUsers[userId] || 0;
            topUsers[userId] = currentScore + userNetActivity;
            if (topUsers[userId] <= 0) delete topUsers[userId];
            Bot.setProperty(topProp, topUsers, "json");
        }
    }
}

if (mrc) {
    var chatId = mrc.chat.id;
    var msgId = mrc.message_id;
    
    var settings = Bot.getProperty("grp_settings_" + chatId);
    if (settings && settings.disabled) return;
    
    var epoch = getEpoch(chatId);
    
    var newCounts = {};
    if (mrc.reactions) {
        for (var i=0; i<mrc.reactions.length; i++) {
            var r = mrc.reactions[i];
            var rKey = getReactionKey(r.type);
            newCounts[rKey] = r.total_count;
        }
    }
    
    var msgProp = "msg_tot_" + chatId + "_" + epoch + "_" + msgId;
    var oldCounts = Bot.getProperty(msgProp) || {};
    
    var diff = {};
    for (var k in oldCounts) {
        var delta = (newCounts[k] || 0) - oldCounts[k];
        if (delta !== 0) diff[k] = delta;
    }
    for (var k in newCounts) {
        if (oldCounts[k] === undefined) diff[k] = newCounts[k];
    }
    
    if (!settings || !settings.disableMessageStats) {
        Bot.setProperty(msgProp, newCounts, "json");
    }
    
    var groupProp = "grp_tot_" + chatId + "_" + epoch;
    var groupTotals = Bot.getProperty(groupProp) || {};
    var groupChanged = false;
    for (var k in diff) {
        groupTotals[k] = (groupTotals[k] || 0) + diff[k];
        if (groupTotals[k] <= 0) delete groupTotals[k];
        groupChanged = true;
    }
    
    if (groupChanged) {
        Bot.setProperty(groupProp, groupTotals, "json");
    }
}
