"""Orchestrates one trip: routing call -> corridor stations -> optimal fuel plan -> response.

The result is a plain JSON-serialisable dict and is cached per (start, finish), so a
repeated request costs zero routing-API calls.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache

from routing.services import corridor, routes, stations
from routing.services.inputs import Point
from routing.services.optimizer import Candidate, UnreachableError, plan_fuel_stops

ROUTE_OUTPUT_STEP_MILES = 0.5   # geometry returned to the client (keeps payload small)
START_PRICE_WINDOW_MILES = 50   # origin fuel is priced at the cheapest station this close


class NoFeasiblePlan(Exception):
    """Route cannot be driven with the given range using stations in the dataset."""


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cache_key(start: Point, finish: Point) -> str:
    raw = f"{start.lat:.3f},{start.lon:.3f}|{finish.lat:.3f},{finish.lon:.3f}"
    return "route:" + hashlib.sha1(raw.encode()).hexdigest()


def plan_trip(start: Point, finish: Point) -> dict:
    key = _cache_key(start, finish)
    if (hit := cache.get(key)) is not None:
        return {**hit, "cached": True}

    route, provider = routes.directions((start.lat, start.lon), (finish.lat, finish.lon))  # the 1 API call

    cum = corridor.cumulative_miles(route.lons, route.lats)
    # Trust the routing engine's distance; haversine over the polyline is within ~0.1%.
    total_miles = route.distance_miles
    cum = cum * (total_miles / cum[-1]) if cum[-1] > 0 else cum
    d_lons, d_lats, d_cum = corridor.decimate(route.lons, route.lats, cum, step_miles=1.0)

    index = stations.get_index()
    range_miles, mpg = settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG

    plan = used_corridor = None
    last_error = None
    for corridor_miles in settings.STATION_CORRIDOR_MILES:
        idx, dist, mile = corridor.project_stations(
            index.lat, index.lon, d_lons, d_lats, d_cum, corridor_miles
        )
        candidates = [
            Candidate(station_id=int(index.rows[i].opis_id), mile=float(m),
                      price=float(index.price[i]), ref=(int(i), float(d)))
            for i, d, m in zip(idx, dist, mile)
        ]
        near_start = [c.price for c in candidates if c.mile <= START_PRICE_WINDOW_MILES]
        if near_start:
            start_price = min(near_start)
        elif candidates:
            start_price = min(candidates, key=lambda c: c.mile).price
        else:
            start_price = index.mean_price
        try:
            plan = plan_fuel_stops(candidates, total_miles, start_price, range_miles, mpg)
            used_corridor = corridor_miles
            break
        except UnreachableError as exc:
            last_error = exc
    if plan is None:
        raise NoFeasiblePlan(
            f"{last_error} Tried stations within {settings.STATION_CORRIDOR_MILES[-1]} miles of "
            f"the route; the dataset has no usable stop for that stretch."
        )

    result = _build_result(start, finish, route, cum, total_miles, plan, index, used_corridor)
    result["routing_provider"] = provider
    cache.set(key, result, settings.ROUTE_CACHE_SECONDS)
    return {**result, "cached": False}


def _build_result(start, finish, route, cum, total_miles, plan, index, used_corridor) -> dict:
    # Geometry for the client: lighter than the raw ORS polyline.
    o_lons, o_lats, _ = corridor.decimate(route.lons, route.lats, cum, ROUTE_OUTPUT_STEP_MILES)
    geometry = {
        "type": "LineString",
        "coordinates": [[round(float(x), 5), round(float(y), 5)] for x, y in zip(o_lons, o_lats)],
    }

    stops, line_costs = [], []
    for n, p in enumerate(plan.stops, start=1):
        i, detour = p.candidate.ref
        st = index.rows[i]
        cost = _money(p.gallons * p.price)
        line_costs.append(cost)
        stops.append({
            "order": n,
            "station_id": st.opis_id,
            "name": st.name,
            "address": st.address,
            "city": st.city,
            "state": st.state,
            "lat": st.lat,
            "lon": st.lon,
            "mile_marker": round(p.mile, 1),
            "distance_from_route_miles": round(detour, 1),
            "price_per_gallon": round(p.price, 4),
            "gallons_purchased": round(p.gallons, 2),
            "cost": float(cost),
        })

    origin = next((p for p in plan.purchases if p.candidate is None), None)
    starting_fuel = None
    if origin is not None:
        cost = _money(origin.gallons * origin.price)
        line_costs.append(cost)
        starting_fuel = {
            "gallons": round(origin.gallons, 2),
            "price_per_gallon": round(origin.price, 4),
            "cost": float(cost),
            "note": "Fuel for the first leg, priced at the cheapest station near the start.",
        }

    return {
        "start": {"label": start.label, "lat": start.lat, "lon": start.lon},
        "finish": {"label": finish.label, "lat": finish.lat, "lon": finish.lon},
        "distance_miles": round(total_miles, 1),
        "duration_minutes": round(route.duration_minutes),
        "route": {"type": "Feature", "properties": {}, "geometry": geometry},
        "fuel_stops": stops,
        "starting_fuel": starting_fuel,
        "total_gallons": round(plan.total_gallons, 2),
        "total_fuel_cost": float(sum(line_costs, Decimal("0"))),
        "currency": "USD",
        "assumptions": {
            "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
            "miles_per_gallon": settings.VEHICLE_MPG,
            "tank_gallons": settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG,
            "station_search_corridor_miles": used_corridor,
            "price_rule": "lowest price listed per station in the supplied file",
            "detours_included_in_cost": False,
        },
    }
