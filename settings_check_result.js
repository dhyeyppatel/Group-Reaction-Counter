// Command Name: /settings_check_result
// BJS Only

if (!options || !options.result || !options.result.status) {
    return Bot.sendMessage("Error checking admin status. Ensure the bot is an admin.");
}
var status = options.result.status;
if (status !== "administrator" && status !== "creator") {
    return Bot.sendMessage("❌ Only administrators can modify settings.");
}

var settings = Bot.getProperty("grp_settings_" + chat.chatid) || {};
var btnTrack = settings.disabled ? "🔴 Tracking: OFF" : "🟢 Tracking: ON";
var btnMsg = settings.disableMessageStats ? "🔴 Message Stats: OFF" : "🟢 Message Stats: ON";
var btnUser = settings.disableUserStats ? "🔴 User Stats: OFF" : "🟢 User Stats: ON";

var buttons = [
    [{ title: btnTrack, command: "/set_toggle tracking" }],
    [{ title: btnMsg, command: "/set_toggle message" }],
    [{ title: btnUser, command: "/set_toggle user" }]
];

Bot.sendInlineKeyboard(buttons, "⚙️ **Group Reaction Settings**");
