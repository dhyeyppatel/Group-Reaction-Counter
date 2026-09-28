// Command Name: /set_toggle
// BJS Only

if (!requireGroup(chat)) return;

Bot.setProperty("tmp_toggle_" + user.telegramid, params, "string");

Api.getChatMember({
    chat_id: chat.chatid,
    user_id: user.telegramid,
    on_result: "/set_toggle_result"
});
