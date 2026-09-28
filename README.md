# Telegram Group Reaction Counter Bot for Bots.Business

## 1. Architecture Overview

This bot leverages the Bots.Business (BJS) environment to efficiently track Telegram group reactions without slowing down or polluting a single JSON property.

### Reaction Parsing Strategy
The Bot relies entirely on the raw `tgUpdate` object provided by Bots.Business since Telegram delivers reactions via `message_reaction` and `message_reaction_count` updates. We use the master handler `*` to intercept these raw updates. We compute the exact difference between `old_reaction` and `new_reaction` arrays to safely increment and decrement counters.

### Data Model & Storage Strategy
To avoid a massive, ever-growing JSON array (which would eventually exceed Bots.Business property limits and cause severe lag), the bot uses a decentralized key-value schema via `Bot.setProp()`:
- **Group Totals:** `grp_tot_<chatId>_<epoch>`
- **User Totals:** `usr_tot_<chatId>_<epoch>_<userId>`
- **Message Totals:** `msg_tot_<chatId>_<epoch>_<msgId>`

**Epochs:** To make the `/reset` command instantaneous and O(1), the bot uses an `epoch` counter. When an admin resets the group, the epoch increments. All new data writes to a new epoch prefix, instantly invalidating the old data without requiring an expensive database scan.

**Why not `List` for aggregates?**
The prompt suggests using `List` for large datasets. While `List` is perfect for *append-only event logs* (e.g., logging every single reaction ever made for an audit trail), using `List` for fast counters would require O(N) database scans for every `/stats` command, which violates the performance requirement. Therefore, `Bot.setProp` with decentralized keys is the scientifically correct approach for O(1) counters.

## 2. Prerequisites & Bot Setup

1. **Telegram Bot API Configuration:**
   Your bot MUST be configured to receive reaction updates. By default, standard webhooks might not receive them. If you don't receive reaction updates, you must use the Telegram API `setWebhook` method and explicitly include `"message_reaction"` and `"message_reaction_count"` in the `allowed_updates` array.
2. **Add Bot to Group:** Add the bot to a supergroup and ensure it has necessary permissions (read messages).
3. **Bots.Business App:** Create a new project in Bots.Business.

## 3. Installation Instructions

Create the following commands in Bots.Business exactly as specified in the provided files. Set the command names exactly as shown (e.g., `*`, `@`, `/start`).

### Command Settings
- **`need_reply`**: Keep FALSE for all commands unless using wait-state inputs.
- **Auto Retry**: Keep Disabled.
- **BJS Only**: For `@` and `*`, this is inherently BJS. For other commands, you can just paste the code into the BJS tab.
- **Wait State**: The `/reset` command uses a wait state to confirm the reset action.

## 4. Test Checklist

- [ ] Add the bot to a Telegram Supergroup.
- [ ] Send a message and react to it.
- [ ] Run `/stats` and ensure the reaction is counted.
- [ ] Remove your reaction. Run `/stats` again and ensure the count decreases.
- [ ] Run `/mystats` to verify individual user tracking.
- [ ] Reply to the reacted message with `/message_stats` to verify message-specific counting.
- [ ] Run `/reset` as a non-admin to ensure it is blocked.
- [ ] Run `/reset` as an admin, confirm it, and verify that `/stats` now shows empty counts.

## 5. Troubleshooting & Limitations

- **"I don't see any reaction updates in the bot!"**
  Telegram does not send reaction updates by default for standard privacy mode bots on basic webhooks. Ensure the bot is an admin in the group or privacy mode is disabled. Most importantly, `allowed_updates` in the webhook config must include `message_reaction`.
- **"Anonymous channel reactions aren't showing user stats."**
  This is a Telegram limitation. When users react anonymously (or if the group hides members), Telegram sends `message_reaction_count` instead of `message_reaction`. The bot handles this gracefully by updating the group and message totals, but `userId` is unavailable.
- **Top Users Limitation:**
  Maintaining a globally sorted leaderboard of users requires scanning all user properties, which is highly inefficient in BJS. The provided `/top` command uses a smart approximation: it maintains a localized `TopUsers` cache for the group that updates on every reaction, preventing database scans.
