// Command Name: /set_toggle_result
// BJS Only

if (!options || !options.result || !options.result.status) return;
var status = options.result.status;
if (status !== "administrator" && status !== "creator") {
    // Cannot send message easily, but we can answer the callback query if BB supports it.
    // BB automatically handles some callback alerts, but we just return.
    return;
}

var param = Bot.getProperty("tmp_toggle_" + user.telegramid);
var settings = Bot.getProperty("grp_settings_" + chat.chatid) || {};

if (param === "tracking") settings.disabled = !settings.disabled;
if (param === "message") settings.disableMessageStats = !settings.disableMessageStats;
if (param === "user") settings.disableUserStats = !settings.disableUserStats;

Bot.setProperty("grp_settings_" + chat.chatid, settings, "json");

var btnTrack = settings.disabled ? "🔴 Tracking: OFF" : "🟢 Tracking: ON";
var btnMsg = settings.disableMessageStats ? "🔴 Message Stats: OFF" : "🟢 Message Stats: ON";
var btnUser = settings.disableUserStats ? "🔴 User Stats: OFF" : "🟢 User Stats: ON";

var buttons = [
    [{ title: btnTrack, command: "/set_toggle tracking" }],
    [{ title: btnMsg, command: "/set_toggle message" }],
    [{ title: btnUser, command: "/set_toggle user" }]
];

Bot.editMessage("⚙️ **Group Reaction Settings**", request.message.message_id);
Bot.editInlineKeyboard(buttons, request.message.message_id);
