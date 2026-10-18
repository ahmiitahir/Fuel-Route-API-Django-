"""Pick a routing provider: OpenRouteService first, public OSRM as an automatic fallback.

Settings: ROUTING_PROVIDER = "auto" (default) | "ors" | "osrm".
In "auto" mode, once ORS fails the fallback is used directly for ORS_COOLDOWN_SECONDS so a
stalled provider does not add its timeout to every request.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings

from routing.services import ors, osrm

logger = logging.getLogger(__name__)

_ors_down_until = 0.0


def reset() -> None:
    global _ors_down_until
    _ors_down_until = 0.0


def directions(start: tuple[float, float], finish: tuple[float, float]):
    """Returns (OrsRoute, provider_name). Exactly one provider call in the normal case."""
    global _ors_down_until
    mode = settings.ROUTING_PROVIDER

    if mode == "osrm":
        return osrm.directions(start, finish), "osrm"
    if mode == "ors":
        return ors.directions(start, finish), "ors"

    if time.monotonic() >= _ors_down_until:
        try:
            return ors.directions(start, finish), "ors"
        except ors.NoRouteFound:
            raise                        # a genuine "no route": the fallback would agree
        except ors.RoutingError as exc:  # timeout, 5xx, quota, missing/rejected key
            logger.warning("ORS failed (%s); falling back to OSRM", exc)
            _ors_down_until = time.monotonic() + settings.ORS_COOLDOWN_SECONDS
    return osrm.directions(start, finish), "osrm"
