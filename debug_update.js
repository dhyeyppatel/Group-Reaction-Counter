// Command Name: /debug_update
// BJS Only

if (!requireGroup(chat)) return;
Api.getChatMember({
    chat_id: chat.chatid,
    user_id: user.telegramid,
    on_result: "/debug_update_result"
});
