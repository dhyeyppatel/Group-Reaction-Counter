// Command Name: /settings
// BJS Only

if (!requireGroup(chat)) return;
Api.getChatMember({
    chat_id: chat.chatid,
    user_id: user.telegramid,
    on_result: "/settings_check_result"
});
