# Offer Stack

**English** | [中文](README.zh-CN.md)

An agent skill that works out how to pay the least for the things you actually want, when a shop throws coupons, spend-X-save-Y tiers, bundles, wallet discounts, cashback and points at you all at once. It finds the cheapest legal combination, tells you which coupons are traps, says whether topping up the cart is worth it, and checks the real checkout total against the math before you pay.

It works for any supermarket, delivery app or online store. It plans only; it never orders or pays.

## Why

Promotions interact. A small coupon can block a bigger bundle. A spend-60 threshold may be measured after item discounts. Adding a 9.90 item to reach a tier can save money or waste it. The "original price" may have been raised last week. These are combinatorial sums that people and language models routinely get wrong, so Offer Stack lets the agent collect and explain, a small script do all of the arithmetic exhaustively in integer cents, and the checkout screen have the final word.

## Features

- **Five-layer model** in a fixed order: item offers, order thresholds, shipping, payment-method discounts, and later value (cashback and points).
- **Exhaustive search** over up to 12 live offers and up to 6 optional items, with group exclusivity, exclusive coupons, caps, unit limits and minimum spend.
- **Honest padding**: only items you marked `maybe` (would buy soon anyway) can be added to reach a threshold, and the saving without padding is always shown separately.
- **Coupon audit** with verdicts `USE`, `SKIP`, `TRAP`, `DEAD`, `OUT`, comparing face value, real saving and opportunity cost.
- **Price anchor check** against a 30-day low when you have one.
- **Checkout quote check** that names the offer that most likely failed to apply.
- **Per-item paid shares** for refunds and splitting a group order fairly.
- Expired, not-yet-started, wrong-channel and unverified offers are left out with a reason, never guessed.
- One Python file, standard library only, with 40 tests.

## Install

The skill is the folder itself: `SKILL.md` (English), `SKILL.zh-CN.md` (Chinese), and `scripts/stackcalc.py`.

**Claude Code**

```bash
git clone https://github.com/fangdididi/offer-stack.git ~/.claude/skills/offer-stack
```

**Codex CLI**

```bash
git clone https://github.com/fangdididi/offer-stack.git ~/.codex/skills/offer-stack
```

**Cursor**: clone into your project's `.cursor/skills/offer-stack`, or reference `SKILL.md` from a project rule.

**Any other agent**: put the folder where the agent can read it and tell it to follow `SKILL.md` when a shopping-deal question comes up. The script needs Python 3.8 or newer.

## Usage

Ask the agent naturally:

> I'm buying coffee, oats and two oat milks in the app. I have a spend-80-save-12, a spend-60-save-6, coffee 30% off, a coffee+oats bundle for 45 and a wallet discount. What should I use?

The agent writes a basket file (see [`examples/weekly-shop.json`](examples/weekly-shop.json)) and runs:

```bash
python3 scripts/stackcalc.py best  basket.json --top 3     # cheapest plans
python3 scripts/stackcalc.py audit basket.json             # verdict for every coupon
python3 scripts/stackcalc.py quote basket.json --plan T60,C30,WALLET --paid 57.40   # compare with checkout
python3 scripts/stackcalc.py shares basket.json --plan T60,C30,WALLET               # refund / split shares
```

Add `--json` to any command for machine-readable output. `quote` exits with code 2 when the checkout does not match.

## Example

```text
$ python3 scripts/stackcalc.py audit examples/weekly-shop.json
best plan uses: C30, CB, T80, WALLET
  USE   T80: nominal 12.00, real alone 12.00, opportunity cost 0.00
  SKIP  T60: nominal 6.00, real alone 6.00, opportunity cost 2.68
  USE   C30: nominal 12.60, real alone 12.60, opportunity cost 0.00
  SKIP  PAIR: nominal 12.00, real alone 12.00, opportunity cost 0.58
  USE   WALLET: nominal 5.00, real alone 5.00, opportunity cost 0.00
  USE   CB: nominal 2.43, real alone 1.94, opportunity cost 0.00
  OUT   OLD: expired 2026-10-20
  OUT   WEB: channel app not in ['web']
```

Here the best overall plan adds the optional tea to reach the spend-80 tier. `best` also reports the plan without padding: 57.40 today, 23.60 below the 81.00 baseline. The bundle works but blocks the 30% coffee coupon, so it is skipped.

## Basket file at a glance

```json
{
  "settings": {"today": "2026-10-24", "channel": "app", "threshold_base": "after_item",
               "cashback_haircut": 0.8, "point_value": 0.01, "maybe_credit": 0.8,
               "shipping_fee": 6, "free_shipping_over": 59},
  "items":  [{"id": "coffee", "price": 42, "want": "need", "low_30d": 36}],
  "offers": [{"id": "T80", "type": "threshold", "min_spend": 80, "value": 12, "group": "store"}]
}
```

Offer types: `bundle`, `item_price`, `percent`, `amount_off`, `threshold`, `order_percent`, `payment`, `cashback` (`percent` or fixed `value`), `points`. Optional fields: `applies_to`, `slots`, `price`, `min_spend`, `cap`, `max_units`, `group`, `exclusive`, `starts`, `expires`, `channels`, `verified`.

## File structure

```text
offer-stack/
├── SKILL.md               # skill instructions (English)
├── SKILL.zh-CN.md         # skill instructions (Chinese)
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/
│   └── stackcalc.py       # best / audit / quote / shares
├── examples/
│   └── weekly-shop.json
└── tests/
    └── test_stackcalc.py  # python3 -m unittest discover -s tests
```

## License

MIT © fangdididi
