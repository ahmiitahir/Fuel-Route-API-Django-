"""Name normalisation shared by the gazetteer loader, the station geocoder and the
request-time "City, ST" resolver, so all three agree on what a place is called."""

import re

# Census LSAD suffixes that are part of the official name but not of how people write it.
_SUFFIXES = (
    "city and borough", "consolidated government", "metropolitan government",
    "unified government", "urban county", "metro government", "municipality",
    "borough", "village", "township", "town", "city", "cdp", "comunidad",
    "zona urbana", "plantation", "gore", "grant", "location", "reservation",
)
_SUFFIX_RE = re.compile(r"\s+(?:" + "|".join(_SUFFIXES) + r")(?:\s*\(balance\))?$")
_ABBREVIATIONS = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount", "n": "north",
                  "s": "south", "e": "east", "w": "west"}

US_STATES = {
    "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "IA", "ID", "IL", "IN", "KS",
    "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ",
    "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT",
    "WA", "WI", "WV", "WY",
}


def normalize(name: str, strip_lsad: bool = False) -> str:
    """Canonical lookup key: 'Ft. Smith' -> 'fort smith'.

    Census names carry one trailing legal-status word ('Oklahoma City city'); pass
    ``strip_lsad=True`` for those. Only ONE suffix is ever removed, so 'Oklahoma City'
    keeps its 'city'.
    """
    name = name.strip().lower()
    if strip_lsad:
        name = _SUFFIX_RE.sub("", name, count=1)
    name = re.sub(r"[.'`]", "", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    words = [_ABBREVIATIONS.get(w, w) for w in name.split()]
    return " ".join(words)


def lookup_keys(name: str) -> list[str]:
    """Keys to try, best first, when matching a user/CSV city name to Place.norm_name."""
    keys = [normalize(name)]
    stripped = normalize(name, strip_lsad=True)
    if stripped not in keys:
        keys.append(stripped)
    return keys
