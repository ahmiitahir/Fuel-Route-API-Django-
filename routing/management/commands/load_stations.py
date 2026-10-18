import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routing.models import Station
from routing.services import stations as station_index


class Command(BaseCommand):
    help = "Load data/stations_geocoded.csv into the Station table."

    def handle(self, *args, **opts):
        path = settings.DATA_DIR / "stations_geocoded.csv"
        if not path.exists():
            raise CommandError("Run `manage.py geocode_stations` first.")
        rows = []
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                rows.append(Station(
                    opis_id=int(r["opis_id"]), name=r["name"], address=r["address"],
                    city=r["city"], state=r["state"], price=Decimal(r["price"]),
                    lat=float(r["lat"]) if r["lat"] else None,
                    lon=float(r["lon"]) if r["lon"] else None,
                ))
        Station.objects.all().delete()
        Station.objects.bulk_create(rows, batch_size=2000)
        station_index.reset()
        located = sum(1 for s in rows if s.lat is not None)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(rows)} stations ({located} with coordinates)"))
