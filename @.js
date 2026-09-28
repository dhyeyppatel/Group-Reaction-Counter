// Command Name: @
// BJS Only

function getEpoch(chatId) {
    var epoch = Bot.getProperty("grp_epoch_" + chatId);
    return epoch ? epoch : 1;
}

function getReactionKey(r) {
    if (!r) return "?";
    if (r.type === 'emoji') return r.emoji;
    if (r.type === 'custom_emoji') return 'custom_' + r.custom_emoji_id;
    return 'unknown_' + r.type;
}

function formatStats(statsObj) {
    if (!statsObj || Object.keys(statsObj).length === 0) return "No reactions yet.";
    var msg = "";
    var total = 0;
    for (var key in statsObj) {
        var displayKey = key.indexOf("custom_") === 0 ? "Custom Emoji" : key;
        msg += displayKey + " : " + statsObj[key] + "\n";
        total += statsObj[key];
    }
    msg += "\nTotal Reactions: " + total;
    return msg;
}

// Simple group check wrapper
function requireGroup(currentChat) {
    if (!currentChat) return false;
    if (currentChat.chat_type === "private") {
        Bot.sendMessage("This command can only be used in groups.");
        return false;
    }
    return true;
}
