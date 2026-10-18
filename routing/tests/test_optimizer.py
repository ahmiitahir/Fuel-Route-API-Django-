import random

from django.test import SimpleTestCase

from routing.services.optimizer import Candidate, UnreachableError, plan_fuel_stops


def cand(i, mile, price):
    return Candidate(station_id=i, mile=mile, price=price)


def brute_force_cost(cands, total_miles, start_price, range_miles=500, mpg=10):
    """Independent DP over integer gallons (miles must be multiples of `mpg`)."""
    cap = int(range_miles / mpg)
    nodes = [(0, start_price)] + sorted((int(c.mile / mpg), c.price) for c in cands)
    dest = int(total_miles / mpg)
    INF = float("inf")
    # best[g] = min cost to be at the current node holding g gallons (before buying)
    best = {0: 0.0}
    for k, (pos, price) in enumerate(nodes):
        # buy any amount here
        after = {}
        for g, c in best.items():
            for buy in range(0, cap - g + 1):
                v = c + buy * price
                if v < after.get(g + buy, INF):
                    after[g + buy] = v
        nxt = nodes[k + 1][0] if k + 1 < len(nodes) else dest
        nxt = min(nxt, dest)
        d = nxt - pos
        best = {}
        for g, c in after.items():
            if g >= d and c < best.get(g - d, INF):
                best[g - d] = c
        if not best:
            return None
    return min(best.values())


class OptimizerTests(SimpleTestCase):
    def test_short_trip_needs_no_station_but_still_costs_money(self):
        plan = plan_fuel_stops([], total_miles=200, start_price=3.0)
        self.assertEqual(plan.stops, [])
        self.assertAlmostEqual(plan.total_gallons, 20.0)
        self.assertAlmostEqual(plan.total_cost, 60.0)

    def test_exactly_one_tank(self):
        plan = plan_fuel_stops([], total_miles=500, start_price=3.0)
        self.assertAlmostEqual(plan.total_gallons, 50.0)

    def test_gap_over_range_is_unreachable(self):
        with self.assertRaises(UnreachableError):
            plan_fuel_stops([], total_miles=501, start_price=3.0)

    def test_buys_only_enough_to_reach_cheaper_station(self):
        # Cheap station at mile 300: don't fill up at the expensive origin.
        plan = plan_fuel_stops([cand(1, 300, 2.0)], total_miles=700, start_price=4.0)
        origin, stop = plan.purchases
        self.assertAlmostEqual(origin.gallons, 30.0)   # exactly 300 mi worth
        self.assertAlmostEqual(stop.gallons, 40.0)     # remaining 400 mi
        self.assertEqual(stop.candidate.station_id, 1)
        self.assertAlmostEqual(plan.total_cost, 30 * 4.0 + 40 * 2.0)

    def test_fills_up_when_nothing_cheaper_ahead(self):
        # Origin is the cheapest: fill to 50 gal, then buy remainder at the next stop.
        plan = plan_fuel_stops([cand(1, 450, 5.0)], total_miles=700, start_price=2.0)
        self.assertAlmostEqual(plan.purchases[0].gallons, 50.0)
        self.assertAlmostEqual(plan.purchases[1].gallons, 20.0)
        self.assertAlmostEqual(plan.total_gallons, 70.0)

    def test_unreachable_between_stations(self):
        with self.assertRaises(UnreachableError):
            plan_fuel_stops([cand(1, 100, 3.0)], total_miles=900, start_price=3.0)

    def test_stops_never_more_than_range_apart(self):
        cands = [cand(i, 120 * i, 3.0 + (i % 3) * 0.1) for i in range(1, 20)]
        plan = plan_fuel_stops(cands, total_miles=2400, start_price=3.2)
        marks = [0.0] + [p.mile for p in plan.stops] + [2400.0]
        self.assertTrue(all(b - a <= 500 + 1e-6 for a, b in zip(marks, marks[1:])))
        self.assertAlmostEqual(plan.total_gallons, 240.0)

    def test_matches_brute_force_on_random_routes(self):
        rng = random.Random(7)
        for _ in range(200):
            total = rng.randrange(200, 1800, 10)
            n = rng.randrange(0, 12)
            cands = [
                cand(i, rng.randrange(10, total, 10), round(rng.uniform(2.5, 4.5), 3))
                for i in range(n)
            ]
            start_price = round(rng.uniform(2.5, 4.5), 3)
            expected = brute_force_cost(cands, total, start_price)
            if expected is None:
                with self.assertRaises(UnreachableError):
                    plan_fuel_stops(cands, total, start_price)
            else:
                plan = plan_fuel_stops(cands, total, start_price)
                self.assertAlmostEqual(plan.total_cost, expected, places=6)
