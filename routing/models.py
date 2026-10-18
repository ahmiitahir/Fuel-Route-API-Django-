from django.db import models


class Place(models.Model):
    """A US city / town / CDP from the Census gazetteer. Used to geocode station
    cities offline and to resolve "City, ST" request inputs without an API call."""

    name = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    norm_name = models.CharField(max_length=120, db_index=True)
    lat = models.FloatField()
    lon = models.FloatField()
    is_incorporated = models.BooleanField(default=True)
    land_sq_mi = models.FloatField(default=0)

    class Meta:
        indexes = [models.Index(fields=["state", "norm_name"])]

    def __str__(self):
        return f"{self.name}, {self.state}"


class Station(models.Model):
    """A truck stop with its (deduplicated) retail diesel price and location."""

    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    price = models.DecimalField(max_digits=6, decimal_places=4)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"
