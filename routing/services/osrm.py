"""Fallback router: the public OSRM demo server (free, no API key).

Used only when OpenRouteService fails. Returns the same ``OrsRoute`` shape.
"""

from __future__ import annotations

import numpy as np
import requests
from django.conf import settings

from routing.services.ors import METERS_PER_MILE, NoRouteFound, OrsRoute, RoutingError

_session = requests.Session()


def directions(start: tuple[float, float], finish: tuple[float, float]) -> OrsRoute:
    url = (
        f"{settings.OSRM_BASE_URL}/route/v1/driving/"
        f"{start[1]:.6f},{start[0]:.6f};{finish[1]:.6f},{finish[0]:.6f}"
    )
    try:
        resp = _session.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            headers={"User-Agent": "fuelroute-assessment/1.0"},
            timeout=settings.OSRM_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RoutingError(f"Fallback routing service unreachable: {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        body = {}
    if body.get("code") in ("NoRoute", "NoSegment"):
        raise NoRouteFound("No drivable route between those points.")
    if resp.status_code != 200 or body.get("code") != "Ok" or not body.get("routes"):
        raise RoutingError(f"Fallback routing service error {resp.status_code}.")

    route = body["routes"][0]
    coords = np.asarray(route["geometry"]["coordinates"], dtype=float)
    return OrsRoute(
        lons=coords[:, 0], lats=coords[:, 1],
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_minutes=route["duration"] / 60.0,
    )
