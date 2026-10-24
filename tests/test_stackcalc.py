import json, os, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import stackcalc as sc  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "weekly-shop.json")


def basket(items, offers=(), **settings):
    settings.setdefault("today", "2026-10-24")
    return sc.load({"settings": settings, "items": list(items), "offers": list(offers)})


A = {"id": "a", "price": 30}
B = {"id": "b", "price": 20}


class Money(unittest.TestCase):
    def test_cents_rounding(self):
        self.assertEqual(sc.cents(9.9), 990)
        self.assertEqual(sc.cents("0.1"), 10)

    def test_money_format(self):
        self.assertEqual(sc.money(5), "0.05")
        self.assertEqual(sc.money(-1234), "-12.34")


class Loading(unittest.TestCase):
    def test_needs_a_need_item(self):
        with self.assertRaises(sc.BasketError):
            basket([{"id": "x", "price": 1, "want": "maybe"}])

    def test_duplicate_item(self):
        with self.assertRaises(sc.BasketError):
            basket([A, A])

    def test_unknown_offer_type(self):
        with self.assertRaises(sc.BasketError):
            basket([A], [{"id": "z", "type": "magic"}])

    def test_expired_dropped(self):
        b = basket([A], [{"id": "t", "type": "threshold", "min_spend": 10, "value": 5, "expires": "2026-10-01"}])
        self.assertEqual(b["offers"], [])
        self.assertIn("expired", b["dropped"][0]["reason"])

    def test_not_started_dropped(self):
        b = basket([A], [{"id": "t", "type": "threshold", "value": 5, "starts": "2026-11-01"}])
        self.assertIn("not active", b["dropped"][0]["reason"])

    def test_channel_mismatch_dropped(self):
        b = basket([A], [{"id": "t", "type": "threshold", "value": 5, "channels": ["web"]}], channel="app")
        self.assertIn("channel", b["dropped"][0]["reason"])

    def test_unverified_dropped(self):
        b = basket([A], [{"id": "t", "type": "threshold", "value": 5, "verified": False}])
        self.assertIn("not verified", b["dropped"][0]["reason"])

    def test_too_many_offers(self):
        offers = [{"id": f"o{i}", "type": "threshold", "value": 1} for i in range(13)]
        with self.assertRaises(sc.BasketError):
            basket([A], offers)


class Pricing(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(sc.baseline(basket([A, B]))["cash_today"], 5000)

    def test_threshold_met(self):
        b = basket([A, B], [{"id": "t", "type": "threshold", "min_spend": 50, "value": 8}])
        self.assertEqual(sc.evaluate(b, ["t"], [])["cash_today"], 4200)

    def test_threshold_missed_is_invalid(self):
        b = basket([A], [{"id": "t", "type": "threshold", "min_spend": 50, "value": 8}])
        self.assertIsNone(sc.evaluate(b, ["t"], []))

    def test_threshold_base_after_item_vs_list(self):
        offers = [{"id": "p", "type": "percent", "applies_to": ["a"], "value": 50},
                  {"id": "t", "type": "threshold", "min_spend": 50, "value": 8}]
        conservative = basket([A, B], offers)
        self.assertIsNone(sc.evaluate(conservative, ["p", "t"], []))
        generous = basket([A, B], offers, threshold_base="list")
        self.assertEqual(sc.evaluate(generous, ["p", "t"], [])["cash_today"], 2700)

    def test_percent_and_cap(self):
        b = basket([A], [{"id": "p", "type": "percent", "applies_to": ["a"], "value": 50, "cap": 10}])
        self.assertEqual(sc.evaluate(b, ["p"], [])["cash_today"], 2000)

    def test_amount_off_never_below_zero(self):
        b = basket([{"id": "c", "price": 2}], [{"id": "m", "type": "amount_off", "applies_to": ["c"], "value": 5}])
        self.assertEqual(sc.evaluate(b, ["m"], [])["cash_today"], 0)

    def test_item_price_max_units(self):
        b = basket([{"id": "a", "price": 30, "qty": 3}],
                   [{"id": "ip", "type": "item_price", "applies_to": ["a"], "price": 10, "max_units": 2}])
        self.assertEqual(sc.evaluate(b, ["ip"], [])["cash_today"], 5000)

    def test_bundle(self):
        b = basket([A, B], [{"id": "bn", "type": "bundle", "slots": [["a"], ["b"]], "price": 35}])
        self.assertEqual(sc.evaluate(b, ["bn"], [])["cash_today"], 3500)

    def test_bundle_missing_slot_invalid(self):
        b = basket([A], [{"id": "bn", "type": "bundle", "slots": [["a"], ["b"]], "price": 25}])
        self.assertIsNone(sc.evaluate(b, ["bn"], []))

    def test_one_unit_one_item_offer(self):
        offers = [{"id": "p", "type": "percent", "applies_to": ["a"], "value": 10},
                  {"id": "q", "type": "percent", "applies_to": ["a"], "value": 20}]
        b = basket([A], offers)
        self.assertIsNone(sc.evaluate(b, ["p", "q"], []))

    def test_group_exclusive(self):
        offers = [{"id": "t1", "type": "threshold", "value": 5, "group": "g"},
                  {"id": "t2", "type": "threshold", "value": 3, "group": "g"}]
        self.assertIsNone(sc.evaluate(basket([A], offers), ["t1", "t2"], []))

    def test_exclusive_flag(self):
        offers = [{"id": "x", "type": "threshold", "value": 5, "exclusive": True},
                  {"id": "y", "type": "threshold", "value": 3}]
        self.assertIsNone(sc.evaluate(basket([A], offers), ["x", "y"], []))

    def test_shipping_and_free_over(self):
        b = basket([B], shipping_fee=6, free_shipping_over=25)
        self.assertEqual(sc.baseline(b)["cash_today"], 2600)
        b2 = basket([A], shipping_fee=6, free_shipping_over=25)
        self.assertEqual(sc.baseline(b2)["cash_today"], 3000)

    def test_payment_layer_after_order(self):
        offers = [{"id": "t", "type": "threshold", "min_spend": 50, "value": 10},
                  {"id": "w", "type": "payment", "min_spend": 45, "value": 5}]
        b = basket([A, B], offers)
        self.assertIsNone(sc.evaluate(b, ["t", "w"], []))
        self.assertEqual(sc.evaluate(b, ["w"], [])["cash_today"], 4500)

    def test_cashback_is_not_cash_today(self):
        b = basket([A], [{"id": "cb", "type": "cashback", "percent": 10}], cashback_haircut=0.5)
        r = sc.evaluate(b, ["cb"], [])
        self.assertEqual(r["cash_today"], 3000)
        self.assertEqual(r["later_value"], 150)
        self.assertEqual(r["effective"], 2850)

    def test_points_need_value(self):
        b = basket([A], [{"id": "pt", "type": "points", "value": 100}])
        self.assertIsNone(sc.evaluate(b, ["pt"], []))


class Search(unittest.TestCase):
    def test_padding_only_with_maybe(self):
        items = [A, {"id": "m", "price": 10, "want": "maybe"}]
        b = basket(items, [{"id": "t", "type": "threshold", "min_spend": 40, "value": 12}])
        best = sc.search(b)[0]
        self.assertEqual(best["padding"], ["m"])
        self.assertEqual(best["cash_today"], 2800)

    def test_padding_not_worth_it(self):
        items = [A, {"id": "m", "price": 10, "want": "maybe"}]
        b = basket(items, [{"id": "t", "type": "threshold", "min_spend": 40, "value": 1}], maybe_credit=0)
        self.assertEqual(sc.search(b)[0]["padding"], [])

    def test_best_reports_no_padding_plan(self):
        r = sc.cmd_best(sc.load(EXAMPLE))
        self.assertEqual(r["best_without_padding"]["padding"], [])
        self.assertEqual(r["saving_vs_baseline"], 2360)

    def test_anchor_warning(self):
        r = sc.cmd_best(sc.load(EXAMPLE))
        self.assertTrue(any("30-day low" in w for w in r["anchor_warnings"]))


class Audit(unittest.TestCase):
    def test_trap_verdict(self):
        offers = [{"id": "small", "type": "amount_off", "applies_to": ["a"], "value": 1},
                  {"id": "big", "type": "bundle", "slots": [["a"], ["b"]], "price": 20}]
        r = sc.cmd_audit(basket([A, B], offers))
        v = {row["id"]: row["verdict"] for row in r["rows"]}
        self.assertEqual(v["big"], "USE")
        self.assertEqual(v["small"], "TRAP")

    def test_dead_and_out(self):
        offers = [{"id": "far", "type": "threshold", "min_spend": 500, "value": 50},
                  {"id": "old", "type": "threshold", "value": 5, "expires": "2020-01-01"}]
        v = {row["id"]: row["verdict"] for row in sc.cmd_audit(basket([A], offers))["rows"]}
        self.assertEqual(v, {"far": "DEAD", "old": "OUT"})


class Quote(unittest.TestCase):
    def test_match(self):
        b = sc.load(EXAMPLE)
        self.assertEqual(sc.cmd_quote(b, ["T60", "C30", "WALLET"], 5740)["status"], "MATCH")

    def test_mismatch_names_offer(self):
        r = sc.cmd_quote(sc.load(EXAMPLE), ["T60", "C30", "WALLET"], 6340)
        self.assertEqual(r["status"], "MISMATCH")
        self.assertIn("T60", r["advice"])

    def test_lower(self):
        self.assertEqual(sc.cmd_quote(sc.load(EXAMPLE), ["C30"], 100)["status"], "LOWER")


class Shares(unittest.TestCase):
    def test_shares_sum_close_to_cash(self):
        b = basket([A, B], [{"id": "t", "type": "threshold", "min_spend": 50, "value": 10}])
        r = sc.evaluate(b, ["t"], [])
        self.assertLessEqual(abs(sum(r["shares"].values()) - r["cash_today"]), 2)
        self.assertEqual(r["shares"], {"a": 2400, "b": 1600})


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "stackcalc.py"), *args],
                              capture_output=True, text=True)

    def test_best_cli(self):
        r = self.run_cli("best", EXAMPLE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("best without padding", r.stdout)

    def test_audit_json(self):
        r = self.run_cli("audit", EXAMPLE, "--json")
        self.assertIn("rows", json.loads(r.stdout))

    def test_quote_exit_code(self):
        self.assertEqual(self.run_cli("quote", EXAMPLE, "--plan", "C30", "--paid", "1").returncode, 2)

    def test_bad_file(self):
        r = self.run_cli("best", "/nonexistent.json")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
