"""In-memory station index: loaded once per process, then reused by every request."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from routing.models import Station

_lock = threading.Lock()
_index: "StationIndex | None" = None


@dataclass
class StationIndex:
    rows: list          # list[Station], aligned with the arrays below
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray

    @property
    def mean_price(self) -> float:
        return float(self.price.mean()) if self.price.size else 0.0


def get_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                rows = list(Station.objects.exclude(lat__isnull=True).exclude(lon__isnull=True))
                _index = StationIndex(
                    rows=rows,
                    lat=np.array([s.lat for s in rows], dtype=float),
                    lon=np.array([s.lon for s in rows], dtype=float),
                    price=np.array([float(s.price) for s in rows], dtype=float),
                )
    return _index


def reset() -> None:
    global _index
    _index = None
