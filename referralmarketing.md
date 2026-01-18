# Referral Marketing Guide

This document explains how to run referral campaigns using the Spredd Markets Bot admin commands.

---

## Quick Reference - Admin Commands

| Command | Description |
|---------|-------------|
| `/getfees` | View current global commission rates |
| `/setfee <tier> <percent>` | Set global tier rate (affects ALL users) |
| `/resetfees` | Reset global rates to defaults (25/5/3%) |
| `/checkuser <telegram_id>` | View user's referral stats & current rate |
| `/setuserrate <telegram_id> <percent>` | Give user a custom VIP rate |
| `/clearuserrate <telegram_id>` | Remove user's custom rate |

---

## How Referral Commissions Work

When a user trades, we take a 2% fee. This fee is distributed to referrers:

- **Tier 1 (Direct Referrer):** Default 25% of fee (0.5% of trade)
- **Tier 2 (Referrer's Referrer):** Default 5% of fee (0.1% of trade)
- **Tier 3:** Default 3% of fee (0.06% of trade)

**Example:** User trades $100
- Fee collected: $2.00
- Tier 1 referrer earns: $0.50 (25% of $2)
- Tier 2 referrer earns: $0.10 (5% of $2)
- Tier 3 referrer earns: $0.06 (3% of $2)

---

## Campaign Type 1: "Invite 3 Friends, Get 50% Commission"

This is a **manual VIP upgrade** campaign. Users who invite 3+ friends get upgraded to a higher rate.

### Step-by-Step Process

1. **Announce the campaign** on your socials:
   > "Invite 3 friends to Spredd Markets and earn 50% commission on their trades! (normally 25%)"

2. **When users claim they've hit 3 referrals**, verify with:
   ```
   /checkuser 123456789
   ```
   Look for: `Direct Referrals: X` - must be 3 or more

3. **If verified, upgrade them:**
   ```
   /setuserrate 123456789 50
   ```

4. **User now earns 50%** on all future trades from their referrals

### Finding User's Telegram ID

Users can find their Telegram ID by:
- Using @userinfobot on Telegram
- Forwarding a message to @JsonDumpBot
- Or have them send you a message and check the logs

### Tracking VIP Users

Keep a spreadsheet of VIP users:
| Telegram ID | Username | Referrals | Rate | Date Upgraded |
|-------------|----------|-----------|------|---------------|
| 123456789 | @john | 5 | 50% | 2024-01-15 |
| 987654321 | @jane | 3 | 50% | 2024-01-16 |

---

## Campaign Type 2: "This Week Only: 50% Referral Bonus"

This is a **global rate increase** - everyone gets the boosted rate temporarily.

### Running the Campaign

1. **Start the promo:**
   ```
   /setfee 1 50
   ```
   Now ALL Tier 1 referrers earn 50%

2. **Announce it:**
   > "This week only: Earn 50% referral commission! Invite friends now!"

3. **End the promo:**
   ```
   /resetfees
   ```
   Rates return to 25/5/3%

### Warning
This affects ALL users globally, including any VIP users you've set up. VIP users will keep their custom rate since per-user rates override global rates.

---

## Campaign Type 3: "Top Referrer Contest"

Run a competition for who can refer the most users in a week.

### Setup

1. Note the start date
2. Announce the contest with prizes:
   > "Top 3 referrers this week win:
   > 1st: Permanent 60% commission
   > 2nd: Permanent 50% commission
   > 3rd: Permanent 40% commission"

3. At end of week, check top referrers:
   ```
   /analytics
   → Top Referrers
   ```

4. Award winners:
   ```
   /setuserrate <winner1_id> 60
   /setuserrate <winner2_id> 50
   /setuserrate <winner3_id> 40
   ```

---

## Removing VIP Status

If a user violates terms or you need to revoke their VIP rate:

```
/clearuserrate 123456789
```

They'll go back to earning the default global rate (25%).

---

## Best Practices

1. **Document everything** - Keep records of who you've upgraded and why
2. **Set clear rules** - Define what counts as a "valid" referral (must trade? must deposit?)
3. **Time-limit promos** - Global rate increases should be temporary
4. **Verify before upgrading** - Always check `/checkuser` before giving VIP rates
5. **Communicate clearly** - Tell users their new rate when you upgrade them

---

## Example Campaign Announcement

```
🚀 REFERRAL BONUS CAMPAIGN 🚀

Invite 3 friends to Spredd Markets and unlock VIP status!

Normal rate: 25% of trading fees
VIP rate: 50% of trading fees (2x earnings!)

How to qualify:
1. Share your referral link (get it with /referral)
2. Have 3 friends sign up AND make a trade
3. DM us proof of 3 referrals
4. Get upgraded to VIP!

Campaign ends: [DATE]
```

---

## Troubleshooting

**"User not found" error**
- Make sure you're using their Telegram ID (numbers only), not username
- User must have started the bot at least once

**User says they have 3 referrals but /checkuser shows fewer**
- Referrals only count if the referred user has started the bot
- Check if their friends actually used the referral link

**VIP user not getting higher rate**
- Verify with `/checkuser` that custom rate is set
- Rate only applies to NEW trades after the upgrade

---

## Summary

| Want to... | Use this command |
|------------|------------------|
| Check a user's referrals | `/checkuser <telegram_id>` |
| Give one user VIP rate | `/setuserrate <telegram_id> <percent>` |
| Remove VIP from one user | `/clearuserrate <telegram_id>` |
| Boost ALL users temporarily | `/setfee 1 <percent>` |
| Reset global rates | `/resetfees` |
| View current rates | `/getfees` |
