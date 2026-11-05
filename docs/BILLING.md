# Plans, usage metering and payments

## Plans

| Plan | Default monthly MOTH Cloud tokens | Default price |
| --- | --- | --- |
| Free | 200,000 | $0 |
| Pro | 5,000,000 | $15/month |
| Max | 20,000,000 (+ priority) | $40/month |
| Owner (LK5T) | unlimited; usage is recorded but never charged | — |

All names, prices, allowances, priority and features are editable in **Owner Dashboard →
Plans**. Changes are audited. Prices display to users, but **checkout stays disabled** until
all three of these are true:

- Stripe credentials are configured on the server;
- the plan has a Stripe price id;
- *Checkout* is switched on for that plan.

## Metering

Every MOTH Cloud request goes through the server and is metered in four steps:

1. **Reserve.** Before generation, the server reserves `prompt tokens + max new tokens`
   atomically from the monthly allowance first, then from earned credits. If the user can't
   cover the reservation, the request is refused with HTTP 402.
2. **Settle.** After generation, the actual input + output token count is charged and the
   unused reservation is returned.
3. **Idempotency.** Each request carries a unique request id. A reused id is refused with
   HTTP 409, so a request can never be charged twice or served twice for free.
4. **No negative balances.** Balances change only through conditional updates
   (`… WHERE balance >= n`), so they never go negative, even under concurrency. A test runs
   25 simultaneous requests against a 10-request budget.

Earned credits (referral rewards, admin grants) live in an append-only ledger with
`balance_after`. The sum of a user's ledger always equals their credit balance.

## Stripe setup

1. In Stripe, create a Product with a recurring monthly Price for Pro and for Max. Enter
   each price id (`price_…`) in Owner Dashboard → Plans.
2. Create a webhook endpoint at `https://<your server>/v1/billing/webhook` with these events:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `charge.refunded`
   - `charge.dispute.created`
3. Set `MOTH_STRIPE_SECRET_KEY` and `MOTH_STRIPE_WEBHOOK_SECRET` on the server and restart.
4. Enable *Checkout* for each plan.

Checkout and the billing portal are hosted by Stripe, so card data never touches MOTH
servers. Webhooks are verified (HMAC-SHA256, 5-minute timestamp tolerance) and processed
exactly once, de-duplicated by event id.

| Event | Effect |
| --- | --- |
| `customer.subscription.*` | Plan entitlement, cancel-at-period-end, cancellation → Free |
| `invoice.paid` | New usage period with the plan's allowance (renewal); may qualify a referral |
| `invoice.payment_failed` | `past_due` (access kept during the provider's retry window) |
| `charge.refunded` / `charge.dispute.created` | Reverses related referral rewards |

## Referral rewards

See the Referrals section of the Owner Dashboard. Rewards are usage credits only:

- created by verified qualifying events (a first paid invoice, or verified GPU training jobs);
- held for a pending period;
- subject to monthly and lifetime caps;
- reversible on refund or dispute, with a ledger clawback that never goes negative;
- same-IP referrals are held for Owner review.
