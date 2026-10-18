"""Cost-optimal refuelling plan along a route (the classic "gas station" problem).

Pure Python, no Django or network imports, so it is trivial to unit test.

Model
-----
* The route is a line of ``total_miles``; candidate stations sit at mile markers.
* Tank capacity is ``range_miles / mpg`` gallons (500 mi / 10 mpg = 50 gal).
* A virtual "origin" node at mile 0 sells fuel at ``start_price``. Using it as the
  first stop means the fuel the vehicle starts the trip with is priced like any other
  gallon, so every gallon burned is paid for, even on trips shorter than one tank.
* A virtual "destination" node at ``total_miles`` has price 0, which makes the greedy
  rule buy only what is needed to arrive with an empty tank.

Greedy rule at each node: if a cheaper node is within range, buy just enough fuel to
reach the *first* such node; otherwise fill the tank and drive to the cheapest node
within range. This is optimal for this problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EPS = 1e-9


class UnreachableError(Exception):
    """Raised when two consecutive candidate stops are further apart than the range."""

    def __init__(self, from_mile: float, to_mile: float | None, range_miles: float):
        self.from_mile = from_mile
        self.to_mile = to_mile
        self.range_miles = range_miles
        gap = "the destination" if to_mile is None else f"mile {to_mile:.0f}"
        super().__init__(
            f"No fuel station within {range_miles:.0f} miles of mile {from_mile:.0f} "
            f"on the way to {gap}."
        )


@dataclass(frozen=True)
class Candidate:
    """A station that can be used for fuelling, positioned along the route."""

    station_id: int
    mile: float
    price: float
    ref: Any = None  # arbitrary payload (e.g. the station row) carried through


@dataclass
class Purchase:
    candidate: Candidate | None  # None => the virtual origin node
    mile: float
    price: float
    gallons: float

    @property
    def cost(self) -> float:
        return self.gallons * self.price


@dataclass
class FuelPlan:
    purchases: list[Purchase] = field(default_factory=list)  # origin purchase first (if any)
    total_miles: float = 0.0

    @property
    def total_cost(self) -> float:
        return sum(p.cost for p in self.purchases)

    @property
    def total_gallons(self) -> float:
        return sum(p.gallons for p in self.purchases)

    @property
    def stops(self) -> list[Purchase]:
        """Purchases made at real stations (everything except the origin fill)."""
        return [p for p in self.purchases if p.candidate is not None]


def plan_fuel_stops(
    candidates: list[Candidate],
    total_miles: float,
    start_price: float,
    range_miles: float = 500.0,
    mpg: float = 10.0,
) -> FuelPlan:
    capacity = range_miles / mpg

    # Node arrays: index 0 = origin, last = destination, real stations in between.
    inner = sorted(
        (c for c in candidates if EPS < c.mile < total_miles - EPS),
        key=lambda c: (c.mile, c.price),
    )
    miles = [0.0] + [c.mile for c in inner] + [total_miles]
    prices = [start_price] + [c.price for c in inner] + [0.0]
    cands: list[Candidate | None] = [None] + inner + [None]
    last = len(miles) - 1

    plan = FuelPlan(total_miles=total_miles)
    fuel = 0.0
    i = 0
    while i < last:
        reach = miles[i] + range_miles + EPS
        # All nodes reachable from i with a full tank.
        j_end = i
        while j_end + 1 <= last and miles[j_end + 1] <= reach:
            j_end += 1
        if j_end == i:
            nxt = miles[i + 1]
            raise UnreachableError(miles[i], None if i + 1 == last else nxt, range_miles)

        cheaper = next((j for j in range(i + 1, j_end + 1) if prices[j] < prices[i] - EPS), None)
        if cheaper is not None:
            target = cheaper
            need = (miles[cheaper] - miles[i]) / mpg
            buy = max(0.0, need - fuel)
        else:
            # Nothing cheaper in range: fill up, then go to the cheapest node in range
            # (farthest one on ties, to keep the number of stops low).
            target = min(range(i + 1, j_end + 1), key=lambda j: (prices[j], -miles[j]))
            need = (miles[target] - miles[i]) / mpg
            buy = capacity - fuel

        if buy > EPS:
            plan.purchases.append(Purchase(cands[i], miles[i], prices[i], buy))
        fuel = fuel + buy - need
        i = target

    return plan
