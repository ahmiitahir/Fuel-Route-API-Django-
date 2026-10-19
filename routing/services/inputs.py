"""Turn the user's `start` / `finish` strings into coordinates, preferring zero API calls.

Accepted forms, tried in order:
  1. "lat,lon"                      -> parsed directly
  2. "City, ST" / "City, State"     -> looked up in the local Census gazetteer table
  3. anything else (street address) -> OpenRouteService geocoder (one extra call, last resort)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from routing.models import Place
from routing.services import ors
from routing.services.places import US_STATES, lookup_keys

# Contiguous USA bounding box (Alaska / Hawaii are out of scope for road routing here).
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 24.3, 49.6, -125.1, -66.8

_LATLON_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

STATE_NAMES = {
    "alabama": "AL", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY",
}


class InvalidLocation(ValueError):
    """The input cannot be used (unparseable, not found, or outside the contiguous USA)."""


@dataclass(frozen=True)
class Point:
    label: str
    lat: float
    lon: float
    source: str  # "coordinates" | "gazetteer" | "geocoder"
    note: str = ""  # shown to the user when we had to guess (e.g. several cities share a name)


def in_contiguous_us(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def _city_state(text: str) -> tuple[str, str] | None:
    parts = [p.strip() for p in re.sub(r",?\s*(usa|us|united states)$", "", text.strip(), flags=re.I).split(",")]
    if len(parts) != 2 or not parts[0]:
        return None
    state = parts[1].upper()
    if state not in US_STATES:
        state = STATE_NAMES.get(parts[1].lower(), "")
    return (parts[0], state) if state else None


def _lookup_place(city: str, state: str) -> Place | None:
    keys = lookup_keys(city)
    matches = list(Place.objects.filter(state=state, norm_name__in=keys))
    if not matches:
        return None
    # Earlier key = closer to what the user typed; then incorporated; then larger.
    return max(matches, key=lambda p: (-keys.index(p.norm_name), p.is_incorporated, p.land_sq_mi))


def _lookup_bare_name(text: str) -> Point | None:
    """'Chicago' with no state: use the local table instead of an API call.

    If several states have a place with that name, take the incorporated one with the
    largest land area (a rough proxy for "the well-known one") and say so in `note`.
    """
    keys = lookup_keys(text)
    matches = list(Place.objects.filter(norm_name__in=keys))
    if not matches:
        return None
    best = max(matches, key=lambda p: (-keys.index(p.norm_name), p.is_incorporated, p.land_sq_mi))
    others = sorted({p.state for p in matches if p.state != best.state})
    note = ""
    if others:
        note = (f"'{text.strip()}' matched several states; using {best.state}. "
                f"Add a state (e.g. '{text.strip()}, {others[0]}') to choose another.")
    return Point(f"{best.name}, {best.state}", best.lat, best.lon, "gazetteer", note)


def resolve(text: str, field: str = "location") -> Point:
    text = (text or "").strip()
    if not text:
        raise InvalidLocation(f"'{field}' is required.")

    point = None
    if m := _LATLON_RE.match(text):
        lat, lon = float(m.group(1)), float(m.group(2))
        point = Point(f"{lat:.5f}, {lon:.5f}", lat, lon, "coordinates")
    elif cs := _city_state(text):
        place = _lookup_place(*cs)
        if place:
            point = Point(f"{place.name}, {place.state}", place.lat, place.lon, "gazetteer")
    elif "," not in text and re.fullmatch(r"[A-Za-z .'\-]+", text):
        point = _lookup_bare_name(text)

    if point is None:
        found = ors.geocode(text)
        if not found:
            raise InvalidLocation(
                f"Could not find '{text}' in the USA. Use 'lat,lon' or 'City, ST'."
            )
        point = Point(found[2], found[0], found[1], "geocoder")

    if not in_contiguous_us(point.lat, point.lon):
        raise InvalidLocation(
            f"'{field}' ({point.label}) is outside the contiguous USA, which is the supported area."
        )
    return point
