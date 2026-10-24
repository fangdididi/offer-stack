---
name: offer-stack
description: Work out whether a pile of coupons, spend-X-save-Y deals, bundles, wallet discounts and cashback really makes a basket cheaper, which combination is legal and best, whether topping up the cart is worth it, and whether the real checkout total matches the math. Use for any store, delivery app or online shop when someone asks "how do I pay the least for this", "is this coupon worth using", or "should I add something to reach the threshold".
---

# Offer Stack

[中文版](SKILL.zh-CN.md)

## What this is

Offer Stack is a method for answering one question honestly: **for the things I actually want, what is the least I can pay today, and is the deal real?**

Shops layer their promotions: a price cut on one item, a two-for-a-price bundle, "spend 80, save 12", a payment-wallet discount, cashback that arrives next month, points. Each offer looks generous on its own. Together they interact: one coupon can block a better one, a threshold may be measured after item discounts, padding the cart to reach a tier can cost more than it saves, and the "original price" may have been raised last week. People (and language models) are bad at this arithmetic, so the skill splits the job:

- **You (the agent)** gather the basket and the offer terms, write them down precisely, and explain the result.
- **`scripts/stackcalc.py`** does every sum, exhaustively and in integer cents.
- **The real checkout** has the final word. Nothing is "the cheapest" until a checkout screen shows the same number.

The skill never places an order or pays. It plans; the person decides.

## When to use it

- "I have five coupons for this shop. Which ones should I use?"
- "I'm 9 short of the spend-60 deal. Should I add something?"
- "Is the 30%-off coffee actually a good price?"
- "The app says 63.40 but I expected 57.40. What went wrong?"
- "We are splitting one discounted order between three people. Who owes what?"
- "If I return one item, how much will I get back?"

Not for: comparing the same product across different shops (do that first, then bring the winning shop's offers here), or deciding whether to buy at all.

## The five layers

Promotions are applied in a fixed order. Write every offer into one of these layers:

| Layer | Types in `stackcalc` | Typical wording |
|---|---|---|
| 1. Item | `bundle`, `item_price`, `percent`, `amount_off` | "Coffee 30% off", "any two for 45", "milk 3 off" |
| 2. Order | `threshold`, `order_percent` | "Spend 80, save 12", "10% off the order" |
| 3. Shipping | `shipping_fee`, `free_shipping_over` settings | "Free delivery over 59" |
| 4. Payment | `payment` | "Pay with wallet: 5 off over 50" |
| 5. Later | `cashback`, `points` | "3% back", "earn 200 points" |

Rules the tool enforces:

- One unit of an item takes at most one item-layer offer. Bundles claim their units first, taking the priciest eligible ones.
- Offers that share a `group` exclude each other (most shops allow only one store-wide threshold). An `exclusive` offer cannot be combined with anything.
- Thresholds are measured on the subtotal **after item discounts** by default (`threshold_base: after_item`). Switch to `list` only when the shop's terms say so in writing.
- Payment offers look at the amount you would actually pay, including delivery.
- Cashback and points never reduce today's cash. They are counted at a haircut (`cashback_haircut`, default 0.8) because they can be delayed, capped or forfeited. Points with no known cash value count as zero.
- An offer that does nothing in a plan makes the plan invalid, so every plan lists only offers that pull their weight.

## Step by step

### 1. Write the basket

List what the person wants, one line per product, with `price` (current shelf price), `qty`, and `want`:

- `need`: they are buying it regardless.
- `maybe`: they would buy it within the next few weeks anyway. Only `maybe` items may be used to reach a threshold.

Anything that is neither is not in the basket. Padding with things nobody wants is spending, not saving, and the tool will not do it.

If the person knows a recent low price (price-history extension, last receipt, the shop's own "lowest in 30 days" label), add `low_30d`.

### 2. Write the offers exactly as the terms say

For each offer record the type, the amount, `min_spend`, `cap`, `max_units`, `applies_to` or bundle `slots`, `group`, `exclusive`, `expires`, `starts`, `channels` (app, web, in-store). Read the small print: "cannot be combined with other coupons" means `exclusive: true`; "one per order" usually means a shared `group`.

If you cannot tell how an offer works, set `verified: false`. It is then left out of the math and listed as such. Never guess a value to make a plan look better.

Set `today` and the `channel` you will check out on, so expired and wrong-channel offers drop out with a reason.

### 3. Run the search

```bash
python3 scripts/stackcalc.py best basket.json --top 3
```

It tries every legal combination of live offers (up to 12) and every set of `maybe` items (up to 6), and ranks plans by **effective cost** = cash today − later value (after haircut) − credit for `maybe` items (at `maybe_credit`, default 0.8 of their price, because you might have found them cheaper later).

Read two numbers, not one:

- **Best without padding**: the honest saving on what they came for.
- **Plan #1**: may add `maybe` items. Present it as "if you would buy the tea within a month anyway, adding it now saves another X".

### 4. Audit the coupons

```bash
python3 scripts/stackcalc.py audit basket.json
```

Each offer gets a verdict:

- `USE`: it is in the best plan.
- `SKIP`: it works, but the best plan without it is cheaper. The opportunity cost says by how much.
- `TRAP`: using it costs more than its face value, usually because it blocks a bigger offer.
- `DEAD`: it cannot apply to this basket, even with padding.
- `OUT`: expired, not started, wrong channel, or unverified.

The face value printed on a coupon is marketing. The real value is what the basket saves with it, and the price of using it is what it pushes out.

### 5. Check the price anchor

If `low_30d` is below the listed price, say so: "the coffee is 42 now but was 36 this month, so the 30% off is really about 18% below its usual low." A discount from an inflated price is still a discount, just a smaller one.

### 6. Confirm with the real checkout

Have the person (or the shop's own tool) put the chosen plan into the cart and read the total before paying. Then:

```bash
python3 scripts/stackcalc.py quote basket.json --plan T60,C30,WALLET --paid 63.40
```

- `MATCH`: proceed.
- `MISMATCH`: the checkout is higher. The tool tries removing each offer and names the one whose absence explains the gap. Do not pay; fix the term or re-plan.
- `LOWER`: it is cheaper than expected. Good, but find out why before trusting the model next time.

### 7. Shares for refunds and splitting

```bash
python3 scripts/stackcalc.py shares basket.json --plan T60,C30,WALLET
```

Many shops prorate order discounts when you return an item, and some take back the whole threshold discount if the remaining order falls below it. The per-item paid share is the fair number for both refunds and splitting a group order. Warn before a return that would drop the order under a threshold.

### 8. Report

Keep it short: the plan to use, the cash today, the saving on the needs alone, any padding suggestion with its condition, offers to skip and why, anchor warnings, and the reminder to compare with the checkout total.

## Example

Basket: coffee 42 (30-day low 36), oats 15, two oat milks at 12, maybe dish soap 9.90, maybe tea 18. Offers: spend 80 save 12 and spend 60 save 6 (same group), coffee 30% off, coffee + oats for 45, wallet 5 off over 50, 3% cashback, an expired milk coupon, a web-only 10%. Checkout in the app, free delivery over 59.

`best` says: baseline 81.00; best without padding is 57.40 today using coffee 30% off, spend-60 save 6 and the wallet offer, plus cashback, a 23.60 saving. Adding the tea reaches spend-80 save 12; that only wins if tea was on next month's list. The expired and web-only offers are left out with reasons. The coffee's 30-day low was 36, so the true saving on it is smaller than it looks.

`audit` says the coffee+oats bundle is `SKIP`: it works, but it blocks the 30% coffee coupon and costs 0.58 more overall.

If the app shows 63.40, `quote` reports the spend-60 deal did not apply: the after-discount subtotal (68.40) qualifies, so check whether the shop measures it on a different set of items.

## Tips

- Ask for the exact wording of each offer, or a screenshot. Most mistakes come from guessing the stacking rule.
- When unsure whether two offers combine, model them as the same `group`. Under-promising is cheaper than a surprise at checkout.
- A delivery fee can flip the result. Always set `shipping_fee` and `free_shipping_over` for online orders.
- Do not count cashback you are not sure to receive. Lower `cashback_haircut` for slow or capped programs.
- Two separate orders can beat one when each reaches a lower tier. Model each order as its own basket and compare the totals.
- For more than 12 live offers, first remove offers that are clearly worse versions of others in the same group.
- Prices change. Re-run when the basket sits in the cart overnight.
