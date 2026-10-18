"""Geometry helpers: where along the route is each nearby station?

All vectorised numpy; no Django imports. Distances are in statute miles.

Approach: the full route geometry is only used to compute exact cumulative distance. For
the nearest-segment search the polyline is decimated to ~1 point per mile, a cheap coarse
filter drops far-away stations, and only the survivors are projected exactly onto segments.
"""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_MI = 3958.7613
MILES_PER_DEG_LAT = 69.093
MILES_PER_DEG_LON_EQ = 69.172


def cumulative_miles(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Haversine cumulative distance along a polyline, starting at 0."""
    lat_r, lon_r = np.radians(lats), np.radians(lons)
    dlat, dlon = np.diff(lat_r), np.diff(lon_r)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
    seg = 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))
    return np.concatenate(([0.0], np.cumsum(seg)))


def decimate(lons, lats, cum, step_miles: float = 1.0):
    """Keep roughly one vertex per `step_miles`, always including both ends."""
    if len(cum) <= 2:
        return lons, lats, cum
    targets = np.arange(0.0, cum[-1], step_miles)
    idx = np.unique(np.concatenate((np.searchsorted(cum, targets), [0, len(cum) - 1])))
    idx = idx[idx < len(cum)]
    return lons[idx], lats[idx], cum[idx]


def _local_xy(dlon, dlat, ref_lat_deg):
    """Offsets in miles for small lon/lat deltas around a reference latitude."""
    return dlon * MILES_PER_DEG_LON_EQ * np.cos(np.radians(ref_lat_deg)), dlat * MILES_PER_DEG_LAT


def project_stations(
    st_lat: np.ndarray,
    st_lon: np.ndarray,
    route_lons: np.ndarray,
    route_lats: np.ndarray,
    route_cum: np.ndarray,
    corridor_miles: float,
):
    """Return (station_indices, distance_to_route_mi, mile_marker) for stations within
    `corridor_miles` of the polyline. The polyline should already be decimated."""
    pad = corridor_miles / MILES_PER_DEG_LAT + 0.05
    keep = (
        (st_lat >= route_lats.min() - pad) & (st_lat <= route_lats.max() + pad)
        & (st_lon >= route_lons.min() - pad * 1.6) & (st_lon <= route_lons.max() + pad * 1.6)
    )
    cand = np.flatnonzero(keep)
    if cand.size == 0 or len(route_lons) < 2:
        return cand, np.array([]), np.array([])

    # Coarse filter: distance to every ~10th vertex (+ slack for the skipped stretch).
    stride = max(1, len(route_lons) // 400)
    coarse_lon, coarse_lat = route_lons[::stride], route_lats[::stride]
    slack = corridor_miles + (float(np.max(np.diff(route_cum))) * stride) / 2 + 1.0
    survivors = []
    for block in np.array_split(cand, max(1, cand.size // 1500 + 1)):
        dx, dy = _local_xy(st_lon[block, None] - coarse_lon[None, :],
                           st_lat[block, None] - coarse_lat[None, :], st_lat[block, None])
        near = (dx * dx + dy * dy).min(axis=1) <= slack * slack
        survivors.append(block[near])
    cand = np.concatenate(survivors)
    if cand.size == 0:
        return cand, np.array([]), np.array([])

    # Exact: project onto every segment of the decimated route, chunked to bound memory.
    a_lon, a_lat = route_lons[:-1], route_lats[:-1]
    ab_x, ab_y = _local_xy(route_lons[1:] - a_lon, route_lats[1:] - a_lat, a_lat)
    ab_len2 = np.maximum(ab_x * ab_x + ab_y * ab_y, 1e-12)
    seg_len = route_cum[1:] - route_cum[:-1]

    out_idx, out_dist, out_mile = [], [], []
    chunk = max(1, 600_000 // len(a_lon))
    for start in range(0, cand.size, chunk):
        block = cand[start:start + chunk]
        ap_x, ap_y = _local_xy(st_lon[block, None] - a_lon[None, :],
                               st_lat[block, None] - a_lat[None, :], a_lat[None, :])
        t = np.clip((ap_x * ab_x + ap_y * ab_y) / ab_len2, 0.0, 1.0)
        dist = np.hypot(ap_x - t * ab_x, ap_y - t * ab_y)
        best = dist.argmin(axis=1)
        rows = np.arange(block.size)
        d = dist[rows, best]
        ok = d <= corridor_miles
        out_idx.append(block[ok])
        out_dist.append(d[ok])
        out_mile.append(route_cum[best[ok]] + t[rows, best][ok] * seg_len[best[ok]])
    return np.concatenate(out_idx), np.concatenate(out_dist), np.concatenate(out_mile)
