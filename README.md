# Stars & Premium shop

Production: Python/aiogram + Supabase, deployed from `main` to Render `stars-premium-shop`. This repository is independent of the local experimental Telegram Serverless rewrite.

## Release 2026-10-23

- One inclusive 5% service fee for new purchases. Provider delivery gas and markup are covered by this fee; payable totals are rounded **down** to four decimal places so rounding never increases the fee above 5%. Trailing zeros are omitted. Existing invoices keep their original amounts. The customer's wallet determines its own outgoing transfer fee.
- Marketapp Stars/Premium recipient preflight runs before the invoice is created. Rejected/frozen recipients and active Premium are blocked; incomplete responses do not create an invoice. Eligibility can change after preflight, so later delivery failure requires support.
- Purchase navigation shows exact total/page counts, uses one custom icon per button, and uses custom emoji `5260416304224936047` for completed purchases. Documents are hidden in Settings.
- GRNT referral rules from `durovson/nothing`: 10% of the service fee, 20% after 500 TON turnover, 30% after 1000 TON; Holder 30%, Special 50%. Rewards are credited atomically once on completion. USDT does not count toward TON tier turnover. Currently checkout issues TON invoices only, as before this release; USDT ledger support does not enable USDT checkout.
- Separate reward balance and withdrawal reserves; minimum 0.1 TON / 1 USDT. New ledger tables and privileged RPCs have RLS and no public access. Referral reserves are excluded from service profit sweeps.

## Deployment and migration

Apply `supabase/migrations/20261022205742_grnt_referral_rewards.sql` **before** deploying this release. The migration adds tables/functions/a completion trigger, preserves existing orders, and does not backfill old purchases or change historical paid rewards. The old `bot_settings.referral_reward_rate` must remain zero: the new reward ledger handles commissions.

Render builds with `pip install -r requirements.txt` and starts `python main.py`. Pushes to `main` auto-deploy. `/health` reports database and worker readiness. Required secrets remain managed by Render; do not commit `.env` or wallet seeds.

## Referral operations

Payouts are **operator-settled**, not automatically signed. A request reserves funds in `creating`; the operator sends the payment, checks it on-chain and records transitions. `submitted` never means confirmed. Hash must match the submitted transfer for confirmation/bounce. Failed/bounced releases the reserve; never mark an ambiguous broadcast failed and send again.

Admin-only commands:

```
/ref_queue
/ref_status <id> prepared
/ref_status <id> submitted <tx_hash>
/ref_status <id> confirmed <same_tx_hash>
/ref_status <id> bounced <same_tx_hash>
/ref_status <id> failed
/ref_profile <user_id> special
/ref_profile <user_id> holder <telegram_chat_id>
/ref_profile <user_id> normal
```

Holder status requires a configured community and successful Bot API membership checks. The bot must have access to that chat. Confirmation is fresh for one hour; opening Referrals refreshes it. Custom community percentages and automatic community discovery from the complete GRNT system are not included; default Holder share is 30%.

## Validation

`python -m unittest discover -s tests -v`; `python -m compileall -q app`. Migration additionally verified with rollback-only database fixtures covering completion reward, tier threshold, minimum withdrawal, reservation and bounced release. No test sends money.
