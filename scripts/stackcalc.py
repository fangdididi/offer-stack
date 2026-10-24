#!/usr/bin/env python3
"""stackcalc - deterministic offer-stacking math for one shopping basket.

Commands:
  best   <basket.json> [--top N]   cheapest legal plan (with optional padding)
  audit  <basket.json>             per-offer verdicts: nominal vs real vs opportunity cost
  quote  <basket.json> --plan ID[,ID] --paid AMOUNT   compare a plan with a real checkout total
  shares <basket.json> [--plan ID[,ID]]  per-item paid share (refunds, bill splitting)

Money is handled in integer cents. Standard library only.
"""
import argparse, itertools, json, sys
from datetime import date

ITEM_LAYER = ("item_price", "percent", "amount_off", "bundle")
ORDER_LAYER = ("threshold", "order_percent")
PAY_LAYER = ("payment",)
LATER_LAYER = ("cashback", "points")
TYPES = ITEM_LAYER + ORDER_LAYER + PAY_LAYER + LATER_LAYER
MAX_OFFERS = 12
MAX_PADDING = 6


def cents(x):
    return int(round(float(x) * 100))


def money(c):
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"


class BasketError(ValueError):
    pass


def load(path_or_obj):
    if isinstance(path_or_obj, dict):
        data = path_or_obj
    else:
        with open(path_or_obj, encoding="utf-8") as f:
            data = json.load(f)
    s = data.get("settings", {})
    settings = {
        "today": s.get("today") or date.today().isoformat(),
        "channel": s.get("channel"),
        "threshold_base": s.get("threshold_base", "after_item"),
        "cashback_haircut": float(s.get("cashback_haircut", 0.8)),
        "point_value": float(s.get("point_value", 0.0)),
        "maybe_credit": float(s.get("maybe_credit", 0.8)),
        "shipping_fee": cents(s.get("shipping_fee", 0)),
        "free_shipping_over": cents(s["free_shipping_over"]) if s.get("free_shipping_over") is not None else None,
    }
    if settings["threshold_base"] not in ("after_item", "list"):
        raise BasketError("threshold_base must be 'after_item' or 'list'")
    items = []
    seen = set()
    for it in data.get("items", []):
        iid = str(it["id"])
        if iid in seen:
            raise BasketError(f"duplicate item id {iid}")
        seen.add(iid)
        want = it.get("want", "need")
        if want not in ("need", "maybe"):
            raise BasketError(f"item {iid}: want must be need or maybe")
        price = cents(it["price"])
        if price < 0:
            raise BasketError(f"item {iid}: negative price")
        items.append({
            "id": iid, "name": it.get("name", iid), "price": price,
            "qty": int(it.get("qty", 1)), "want": want,
            "low_30d": cents(it["low_30d"]) if it.get("low_30d") is not None else None,
        })
    if not any(i["want"] == "need" for i in items):
        raise BasketError("basket needs at least one item with want=need")
    offers, dropped = [], []
    ids = set()
    for o in data.get("offers", []):
        oid = str(o["id"])
        if oid in ids:
            raise BasketError(f"duplicate offer id {oid}")
        ids.add(oid)
        t = o.get("type")
        if t not in TYPES:
            raise BasketError(f"offer {oid}: unknown type {t!r}")
        reason = None
        if o.get("expires") and o["expires"] < settings["today"]:
            reason = f"expired {o['expires']}"
        elif o.get("starts") and o["starts"] > settings["today"]:
            reason = f"not active until {o['starts']}"
        elif o.get("channels") and settings["channel"] and settings["channel"] not in o["channels"]:
            reason = f"channel {settings['channel']} not in {o['channels']}"
        elif o.get("verified") is False:
            reason = "terms not verified (kept out of the math)"
        rec = {
            "id": oid, "type": t, "label": o.get("label", oid),
            "applies_to": [str(x) for x in o.get("applies_to", [])],
            "slots": [[str(x) for x in slot] for slot in o.get("slots", [])],
            "value": float(o.get("value", 0)),
            "percent": float(o.get("percent", 0)),
            "price": cents(o["price"]) if o.get("price") is not None else None,
            "min_spend": cents(o.get("min_spend", 0)),
            "cap": cents(o["cap"]) if o.get("cap") is not None else None,
            "max_units": int(o.get("max_units", 1)),
            "group": o.get("group"), "exclusive": bool(o.get("exclusive", False)),
        }
        if t == "bundle" and (not rec["slots"] or rec["price"] is None):
            raise BasketError(f"offer {oid}: bundle needs slots and price")
        if t == "item_price" and rec["price"] is None:
            raise BasketError(f"offer {oid}: item_price needs price")
        if reason:
            dropped.append({"id": oid, "label": rec["label"], "reason": reason})
        else:
            offers.append(rec)
    if len(offers) > MAX_OFFERS:
        raise BasketError(f"{len(offers)} live offers; the exhaustive search handles at most {MAX_OFFERS}. Drop obvious losers first.")
    if sum(1 for i in items if i["want"] == "maybe") > MAX_PADDING:
        raise BasketError(f"at most {MAX_PADDING} maybe items")
    return {"settings": settings, "items": items, "offers": offers, "dropped": dropped}


def compatible(subset):
    if len(subset) > 1 and any(o["exclusive"] for o in subset):
        return False
    groups = [o["group"] for o in subset if o["group"]]
    return len(groups) == len(set(groups))


def evaluate(b, offer_ids, padding_ids):
    """Price one order. Returns dict or None when an offer in the set does nothing (invalid plan)."""
    st = b["settings"]
    byid = {o["id"]: o for o in b["offers"]}
    subset = [byid[x] for x in offer_ids]
    if not compatible(subset):
        return None
    units = []  # each unit: dict(item, paid, by)
    for it in b["items"]:
        if it["want"] == "need" or it["id"] in padding_ids:
            for _ in range(it["qty"]):
                units.append({"item": it, "paid": it["price"], "by": None})
    list_total = sum(u["item"]["price"] for u in units)
    lines = []
    # 1. bundles first: each slot takes the priciest free eligible unit
    for o in [o for o in subset if o["type"] == "bundle"]:
        taken = []
        for slot in o["slots"]:
            cands = [u for u in units if u["by"] is None and u not in taken and u["item"]["id"] in slot]
            if not cands:
                return None
            taken.append(max(cands, key=lambda u: u["item"]["price"]))
        full = sum(u["item"]["price"] for u in taken)
        if o["price"] >= full:
            return None
        # spread bundle price across members in proportion to list price
        given = 0
        for k, u in enumerate(taken):
            share = o["price"] - given if k == len(taken) - 1 else o["price"] * u["item"]["price"] // full
            given += share
            u["paid"], u["by"] = share, o["id"]
        lines.append((o["id"], full - o["price"]))
    # 2. single-item offers, applied best-saving-first to the priciest eligible units
    for o in [o for o in subset if o["type"] in ("item_price", "percent", "amount_off")]:
        cands = sorted([u for u in units if u["by"] is None and u["item"]["id"] in o["applies_to"]],
                       key=lambda u: -u["item"]["price"])[: o["max_units"]]
        saved = 0
        for u in cands:
            p = u["item"]["price"]
            if o["type"] == "item_price":
                new = min(p, o["price"])
            elif o["type"] == "percent":
                new = p - int(round(p * o["value"] / 100))
            else:
                new = max(0, p - cents(o["value"]))
            if new < p:
                saved += p - new
                u["paid"], u["by"] = new, o["id"]
        if o["cap"] is not None and saved > o["cap"]:
            # give back the excess on the last unit touched
            excess = saved - o["cap"]
            for u in reversed(cands):
                if u["by"] == o["id"]:
                    back = min(excess, u["item"]["price"] - u["paid"])
                    u["paid"] += back
                    excess -= back
                if excess == 0:
                    break
            saved = o["cap"]
        if saved == 0:
            return None
        lines.append((o["id"], saved))
    after_item = sum(u["paid"] for u in units)
    base = after_item if st["threshold_base"] == "after_item" else list_total
    # 3. order-level
    order_off = 0
    for o in sorted([o for o in subset if o["type"] in ORDER_LAYER], key=lambda o: o["id"]):
        if base < o["min_spend"]:
            return None
        if o["type"] == "threshold":
            off = cents(o["value"])
        else:
            off = int(round((after_item - order_off) * o["value"] / 100))
        if o["cap"] is not None:
            off = min(off, o["cap"])
        off = min(off, after_item - order_off)
        if off <= 0:
            return None
        order_off += off
        lines.append((o["id"], off))
    goods = after_item - order_off
    ship = st["shipping_fee"]
    if st["free_shipping_over"] is not None and goods >= st["free_shipping_over"]:
        ship = 0
    payable = goods + ship
    # 4. payment-layer (on the amount you would pay)
    for o in [o for o in subset if o["type"] == "payment"]:
        if payable < o["min_spend"]:
            return None
        off = cents(o["value"])
        if o["cap"] is not None:
            off = min(off, o["cap"])
        off = min(off, payable)
        if off <= 0:
            return None
        payable -= off
        lines.append((o["id"], off))
    # 5. later value (does not reduce cash today)
    later = 0
    for o in [o for o in subset if o["type"] in LATER_LAYER]:
        if payable < o["min_spend"]:
            return None
        if o["type"] == "cashback":
            raw = int(round(payable * o["percent"] / 100)) if o["percent"] else cents(o["value"])
            if o["cap"] is not None:
                raw = min(raw, o["cap"])
            val = int(round(raw * st["cashback_haircut"]))
        else:
            val = int(round(o["value"] * st["point_value"] * 100 * st["cashback_haircut"]))
        if val <= 0:
            return None
        later += val
        lines.append((o["id"], val))
    pad_credit = 0
    for it in b["items"]:
        if it["id"] in padding_ids:
            pad_credit += int(round(it["price"] * it["qty"] * st["maybe_credit"]))
    effective = payable - later - pad_credit
    # proportional paid share per unit (what a refund or a fair split would use)
    goods_units = sum(u["paid"] for u in units) or 1
    shares = {}
    for u in units:
        sh = (u["paid"] * (payable)) // goods_units
        shares[u["item"]["id"]] = shares.get(u["item"]["id"], 0) + sh
    return {
        "offers": sorted(offer_ids), "padding": sorted(padding_ids), "list_total": list_total,
        "after_item": after_item, "shipping": ship, "cash_today": payable, "later_value": later,
        "padding_credit": pad_credit, "effective": effective, "lines": lines, "shares": shares,
    }


def baseline(b):
    return evaluate(b, [], [])


def search(b, forced=None):
    ids = [o["id"] for o in b["offers"]]
    maybes = [i["id"] for i in b["items"] if i["want"] == "maybe"]
    plans = []
    for r in range(len(ids) + 1):
        for combo in itertools.combinations(ids, r):
            if forced and forced not in combo:
                continue
            for pr in range(len(maybes) + 1):
                for pad in itertools.combinations(maybes, pr):
                    res = evaluate(b, list(combo), list(pad))
                    if res:
                        plans.append(res)
    plans.sort(key=lambda p: (p["effective"], p["cash_today"], len(p["padding"]), len(p["offers"])))
    return plans


def anchor_warnings(b):
    out = []
    for it in b["items"]:
        if it["low_30d"] is not None and it["price"] > it["low_30d"]:
            out.append(f"{it['id']}: listed {money(it['price'])} but 30-day low was {money(it['low_30d'])}; "
                       f"count savings from {money(it['low_30d'])}, not from the list price")
    return out


def cmd_best(b, top=3):
    base = baseline(b)
    plans = search(b)
    nopad = [p for p in plans if not p["padding"]][0]
    return {
        "baseline_cash": base["cash_today"], "plans": plans[:top], "dropped": b["dropped"],
        "best_without_padding": nopad,
        "saving_vs_baseline": base["cash_today"] - nopad["cash_today"],
        "anchor_warnings": anchor_warnings(b),
    }


def cmd_audit(b):
    base = baseline(b)
    plans = search(b)
    best = plans[0]
    rows = []
    for o in b["offers"]:
        alone = [p for p in plans if p["offers"] == [o["id"]]]
        alone_best = alone[0] if alone else None
        forced = [p for p in plans if o["id"] in p["offers"]]
        if not forced:
            rows.append({"id": o["id"], "label": o["label"], "verdict": "DEAD",
                         "why": "cannot apply to this basket, even with padding"})
            continue
        f = forced[0]
        opp = f["effective"] - best["effective"]
        real = base["effective"] - alone_best["effective"] if alone_best else 0
        nominal = nominal_value(b, o)
        if o["id"] in best["offers"]:
            verdict = "USE"
        elif nominal and opp > nominal:
            verdict = "TRAP"
        else:
            verdict = "SKIP"
        rows.append({"id": o["id"], "label": o["label"], "verdict": verdict, "nominal": nominal,
                     "real_alone": real, "opportunity_cost": opp,
                     "needs_padding": bool(alone_best and alone_best["padding"])})
    for d in b["dropped"]:
        rows.append({"id": d["id"], "label": d["label"], "verdict": "OUT", "why": d["reason"]})
    return {"best_offers": best["offers"], "rows": rows}


def nominal_value(b, o):
    prices = {i["id"]: i["price"] for i in b["items"]}
    if o["type"] in ("threshold", "payment") or (o["type"] == "cashback" and not o["percent"]):
        return cents(o["value"])
    if o["type"] == "amount_off":
        return cents(o["value"]) * o["max_units"]
    if o["type"] == "item_price":
        top = max([prices.get(x, 0) for x in o["applies_to"]] or [0])
        return max(0, top - o["price"]) * o["max_units"]
    if o["type"] == "percent":
        top = max([prices.get(x, 0) for x in o["applies_to"]] or [0])
        return int(round(top * o["value"] / 100)) * o["max_units"]
    if o["type"] == "cashback":
        return int(round(baseline(b)["cash_today"] * o["percent"] / 100))
    if o["type"] == "bundle":
        full = sum(max([prices.get(x, 0) for x in slot] or [0]) for slot in o["slots"])
        return max(0, full - o["price"])
    return 0


def cmd_quote(b, plan_ids, paid):
    res = evaluate(b, plan_ids, [])
    if res is None:
        raise BasketError("that plan is not valid for this basket (an offer does nothing or rules clash)")
    diff = paid - res["cash_today"]
    if diff == 0:
        status, advice = "MATCH", "the checkout agrees with the math; safe to proceed"
    elif diff > 0:
        status = "MISMATCH"
        guesses = []
        for oid in plan_ids:
            rest = [x for x in plan_ids if x != oid]
            alt = evaluate(b, rest, []) if rest else baseline(b)
            if alt and alt["cash_today"] == paid:
                guesses.append(oid)
        advice = (f"checkout is {money(diff)} higher. "
                  + (f"Matches the plan without {', '.join(guesses)}: that offer did not apply. " if guesses else "")
                  + "Do not pay yet; re-check the offer terms or re-quote.")
    else:
        status, advice = "LOWER", f"checkout is {money(-diff)} lower than expected; find out why before trusting it again"
    return {"status": status, "expected": res["cash_today"], "paid": paid, "advice": advice}


def fmt_plan(p, i):
    out = [f"  #{i} cash today {money(p['cash_today'])}  effective {money(p['effective'])}"
           f"  offers [{', '.join(p['offers']) or 'none'}]  padding [{', '.join(p['padding']) or 'none'}]"]
    for oid, v in p["lines"]:
        out.append(f"      {oid}: {money(v)}")
    if p["shipping"]:
        out.append(f"      shipping: {money(p['shipping'])}")
    if p["later_value"]:
        out.append(f"      later value (after haircut, not cash today): {money(p['later_value'])}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["best", "audit", "quote", "shares"])
    ap.add_argument("basket")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--plan", default="")
    ap.add_argument("--paid")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        b = load(a.basket)
        plan = [x for x in a.plan.split(",") if x]
        if a.command == "best":
            r = cmd_best(b, a.top)
            if a.json:
                print(json.dumps(r, indent=1)); return 0
            print(f"baseline (no offers, no padding): {money(r['baseline_cash'])}")
            for i, p in enumerate(r["plans"], 1):
                print(fmt_plan(p, i))
            n = r["best_without_padding"]
            print(f"best without padding: cash today {money(n['cash_today'])} with [{', '.join(n['offers']) or 'none'}]"
                  f" -> saves {money(r['saving_vs_baseline'])} on the needs alone")
            top1 = r["plans"][0]
            if top1["padding"]:
                print(f"note: plan #1 adds {', '.join(top1['padding'])}; it only wins if you would buy those soon anyway"
                      f" (credited at {money(top1['padding_credit'])})")
            for d in r["dropped"]:
                print(f"  left out {d['id']}: {d['reason']}")
            for w in r["anchor_warnings"]:
                print(f"  anchor: {w}")
        elif a.command == "audit":
            r = cmd_audit(b)
            if a.json:
                print(json.dumps(r, indent=1)); return 0
            print(f"best plan uses: {', '.join(r['best_offers']) or 'no offers'}")
            for row in r["rows"]:
                if "nominal" in row:
                    print(f"  {row['verdict']:<5} {row['id']}: nominal {money(row['nominal'])}, real alone {money(row['real_alone'])}, "
                          f"opportunity cost {money(row['opportunity_cost'])}{' (needs padding)' if row['needs_padding'] else ''}")
                else:
                    print(f"  {row['verdict']:<5} {row['id']}: {row['why']}")
        elif a.command == "quote":
            if a.paid is None:
                ap.error("quote needs --paid")
            r = cmd_quote(b, plan, cents(a.paid))
            if a.json:
                print(json.dumps(r, indent=1)); return 0
            print(f"{r['status']}: expected {money(r['expected'])}, checkout {money(r['paid'])}. {r['advice']}")
            return 0 if r["status"] == "MATCH" else 2
        else:
            res = evaluate(b, plan, []) if plan else search(b)[0]
            if res is None:
                raise BasketError("that plan is not valid for this basket")
            if a.json:
                print(json.dumps(res["shares"], indent=1)); return 0
            for iid, c in res["shares"].items():
                print(f"  {iid}: {money(c)}")
            print(f"  (sums to about {money(res['cash_today'])}; rounding stays with the payer)")
    except (BasketError, KeyError, OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
