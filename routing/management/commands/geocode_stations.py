"""One-time offline step: dedupe the fuel-price CSV and attach coordinates to each station.

    python manage.py geocode_stations             # gazetteer only (no network)
    python manage.py geocode_stations --nominatim # also try Nominatim for leftovers (1 req/s)

Output: data/stations_geocoded.csv (committed, so reviewers don't need to re-run this).
"""

import csv
import time
from collections import defaultdict
from decimal import Decimal

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routing.models import Place
from routing.services.places import US_STATES, lookup_keys

FIELDS = ["opis_id", "name", "address", "city", "state", "price", "lat", "lon", "geocode_source"]


def build_place_index():
    index = defaultdict(list)
    for p in Place.objects.all():
        index[(p.state, p.norm_name)].append(p)
    return index


def best_place(index, city, state):
    for key in lookup_keys(city):
        matches = index.get((state, key))
        if matches:
            # Prefer incorporated places, then the physically larger one.
            return max(matches, key=lambda p: (p.is_incorporated, p.land_sq_mi))
    return None


def nominatim(city, state, session):
    resp = session.get(
        "https://nominatim.openstreetmap.org/search",
        params={"city": city, "state": state, "country": "USA", "format": "json", "limit": 1},
        headers={"User-Agent": "fuelroute-assessment/1.0 (one-time station geocoding)"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return (float(data[0]["lat"]), float(data[0]["lon"])) if data else None


class Command(BaseCommand):
    help = "Dedupe fuel prices and geocode stations into data/stations_geocoded.csv"

    def add_arguments(self, parser):
        parser.add_argument("--nominatim", action="store_true",
                            help="Try Nominatim (1 req/s) for cities missing from the gazetteer")

    def handle(self, *args, **opts):
        src = settings.DATA_DIR / "fuel-prices.csv"
        out = settings.DATA_DIR / "stations_geocoded.csv"
        if not Place.objects.exists():
            raise CommandError("Place table is empty - run `manage.py load_places` first.")

        # Dedupe: one row per OPIS id, keeping the lowest price (and that row's name).
        best = {}
        raw_rows = 0
        with src.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                raw_rows += 1
                price = Decimal(row["Retail Price"])
                sid = int(row["OPIS Truckstop ID"])
                if sid not in best or price < best[sid]["price"]:
                    best[sid] = {
                        "opis_id": sid, "name": row["Truckstop Name"].strip(),
                        "address": row["Address"].strip(), "city": row["City"].strip(),
                        "state": row["State"].strip(), "price": price,
                    }

        index = build_place_index()
        session = requests.Session()
        cache = {}  # (city, state) -> (lat, lon, source)
        unmatched = set()
        rows = []
        for st in best.values():
            if st["state"] not in US_STATES:
                continue  # e.g. Canadian provinces
            key = (st["city"], st["state"])
            if key not in cache:
                place = best_place(index, *key)
                if place:
                    cache[key] = (place.lat, place.lon, "census")
                elif opts["nominatim"]:
                    time.sleep(1.1)
                    try:
                        hit = nominatim(*key, session)
                    except requests.RequestException as exc:
                        self.stderr.write(f"Nominatim failed for {key}: {exc}")
                        hit = None
                    cache[key] = (*hit, "nominatim") if hit else None
                else:
                    cache[key] = None
                if cache[key] is None:
                    unmatched.add(key)
            hit = cache[key]
            rows.append({**st, "lat": hit[0] if hit else "", "lon": hit[1] if hit else "",
                         "geocode_source": hit[2] if hit else "none"})

        rows.sort(key=lambda r: r["opis_id"])
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        located = sum(1 for r in rows if r["lat"] != "")
        self.stdout.write(
            f"{raw_rows} CSV rows -> {len(best)} unique stations -> {len(rows)} in US states\n"
            f"geocoded: {located}/{len(rows)} ({located / len(rows):.1%}); "
            f"unmatched cities: {len(unmatched)}\n"
            f"wrote {out}"
        )
        if unmatched:
            sample = sorted(unmatched)[:25]
            self.stdout.write("sample unmatched: " + "; ".join(f"{c}, {s}" for c, s in sample))
