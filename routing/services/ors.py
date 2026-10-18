"""Thin OpenRouteService client. One directions call per uncached route.

Every function that hits the network goes through ``_request`` so tests can patch a single
place and count calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

METERS_PER_MILE = 1609.344

_session = requests.Session()


class RoutingError(Exception):
    """Base class; `status` is the HTTP status the API should answer with."""

    status = 502


class RoutingNotConfigured(RoutingError):
    status = 503


class RoutingQuotaExceeded(RoutingError):
    status = 503


class NoRouteFound(RoutingError):
    status = 400


@dataclass
class OrsRoute:
    lons: np.ndarray
    lats: np.ndarray
    distance_miles: float
    duration_minutes: float


def _request(method: str, path: str, **kwargs) -> requests.Response:
    key = settings.ORS_API_KEY
    if not key:
        raise RoutingNotConfigured("ORS_API_KEY is not set. Add it to .env (see .env.example).")
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = key
    # The free public ORS server occasionally stalls for a minute on an otherwise 1-3 s
    # request. A short timeout plus ONE retry keeps the worst case at two calls.
    attempts = 1 + settings.ORS_RETRIES
    for attempt in range(attempts):
        try:
            resp = _session.request(
                method, settings.ORS_BASE_URL + path, headers=headers,
                timeout=settings.ORS_TIMEOUT_SECONDS, **kwargs,
            )
        except requests.Timeout as exc:
            if attempt + 1 < attempts:
                continue
            raise RoutingError("Routing service timed out.") from exc
        except requests.RequestException as exc:
            if attempt + 1 < attempts:
                continue
            raise RoutingError(f"Routing service unreachable: {exc}") from exc
        if resp.status_code >= 500 and attempt + 1 < attempts:
            continue
        break

    if resp.status_code in (401, 403):
        raise RoutingNotConfigured("OpenRouteService rejected the API key.")
    if resp.status_code == 429:
        raise RoutingQuotaExceeded("OpenRouteService rate limit / daily quota reached.")
    if resp.status_code >= 400:
        detail = _error_message(resp)
        if resp.status_code in (400, 404):
            raise NoRouteFound(f"No drivable route between those points ({detail}).")
        raise RoutingError(f"OpenRouteService error {resp.status_code}: {detail}")
    return resp


def _error_message(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error", resp.text)
        return err.get("message", str(err)) if isinstance(err, dict) else str(err)
    except ValueError:
        return resp.text[:200]


def directions(start: tuple[float, float], finish: tuple[float, float]) -> OrsRoute:
    """Driving route between two (lat, lon) points - the ONE routing call per trip."""
    resp = _request(
        "POST", "/v2/directions/driving-car/geojson",
        json={
            "coordinates": [[start[1], start[0]], [finish[1], finish[0]]],
            "instructions": False,
            "radiuses": [-1, -1],   # snap to the nearest road however far (city centroids)
        },
    )
    feature = resp.json()["features"][0]
    coords = np.asarray(feature["geometry"]["coordinates"], dtype=float)
    summary = feature["properties"]["summary"]
    return OrsRoute(
        lons=coords[:, 0], lats=coords[:, 1],
        distance_miles=summary["distance"] / METERS_PER_MILE,
        duration_minutes=summary["duration"] / 60.0,
    )


def geocode(text: str) -> tuple[float, float, str] | None:
    """Free-form address -> (lat, lon, label), US only. Only used as a last resort."""
    resp = _request(
        "GET", "/geocode/search",
        params={"text": text, "boundary.country": "US", "size": 1},
    )
    features = resp.json().get("features") or []
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    return lat, lon, features[0]["properties"].get("label", text)
