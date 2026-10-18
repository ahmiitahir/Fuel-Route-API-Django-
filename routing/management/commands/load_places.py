import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routing.models import Place
from routing.services.places import US_STATES, normalize

# LSAD codes of Census Designated Places (unincorporated); everything else is incorporated.
CDP_LSAD = {"57", "56"}


class Command(BaseCommand):
    help = "Load the Census gazetteer places file (tab separated) into the Place table."

    def add_arguments(self, parser):
        parser.add_argument(
            "path", nargs="?",
            default=str(settings.DATA_DIR / "downloads" / "gaz" / "2024_Gaz_place_national.txt"),
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"{path} not found")

        places = []
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            reader.fieldnames = [f.strip() for f in reader.fieldnames]
            for row in reader:
                state = row["USPS"].strip()
                if state not in US_STATES:  # skip PR etc.
                    continue
                name = row["NAME"].strip()
                places.append(Place(
                    name=name,
                    state=state,
                    norm_name=normalize(name, strip_lsad=True),
                    lat=float(row["INTPTLAT"]),
                    lon=float(row["INTPTLONG"]),
                    is_incorporated=row["LSAD"].strip() not in CDP_LSAD,
                    land_sq_mi=float(row["ALAND_SQMI"]),
                ))
        Place.objects.all().delete()
        Place.objects.bulk_create(places, batch_size=5000)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(places)} places"))
