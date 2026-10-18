from decimal import Decimal
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from routing.models import Place, Station
from routing.services import corridor, inputs, ors, routes, stations

CHICAGO = (41.88, -87.63)
DALLAS = (32.78, -96.80)


def fake_route(start, finish, n=3000):
    """Straight-line 'route' with realistic distance, shaped like an ORS response."""
    lats = np.linspace(start[0], finish[0], n)
    lons = np.linspace(start[1], finish[1], n)
    miles = corridor.cumulative_miles(lons, lats)[-1]
    return ors.OrsRoute(lons=lons, lats=lats, distance_miles=miles, duration_minutes=miles / 60 * 60)


def make_station(i, frac, price, off=0.0):
    lat = CHICAGO[0] + (DALLAS[0] - CHICAGO[0]) * frac + off
    lon = CHICAGO[1] + (DALLAS[1] - CHICAGO[1]) * frac
    return Station(opis_id=i, name=f"STOP {i}", address="I-55", city="Town", state="IL",
                   price=Decimal(str(price)), lat=lat, lon=lon)


@override_settings(ROUTING_PROVIDER="ors")
class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Place.objects.bulk_create([
            Place(name="Chicago city", state="IL", norm_name="chicago", lat=CHICAGO[0], lon=CHICAGO[1]),
            Place(name="Dallas city", state="TX", norm_name="dallas", lat=DALLAS[0], lon=DALLAS[1]),
            Place(name="Oklahoma City city", state="OK", norm_name="oklahoma city", lat=35.47, lon=-97.52),
        ])
        Station.objects.bulk_create([
            make_station(1, 0.10, 3.50), make_station(2, 0.40, 3.10), make_station(3, 0.55, 3.60),
            make_station(4, 0.80, 3.20), make_station(5, 0.50, 2.50, off=2.5),   # ~170 mi off route
        ])

    def setUp(self):
        cache.clear()
        stations.reset()
        patcher = mock.patch.object(ors, "directions", side_effect=fake_route)
        self.directions = patcher.start()
        self.addCleanup(patcher.stop)
        geo = mock.patch.object(ors, "geocode", side_effect=AssertionError("geocoder must not be called"))
        geo.start()
        self.addCleanup(geo.stop)

    def get(self, start="Chicago, IL", finish="Dallas, TX"):
        return self.client.get(reverse("route"), {"start": start, "finish": finish})

    def test_happy_path_uses_one_routing_call(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(self.directions.call_count, 1)
        self.assertEqual(data["route"]["geometry"]["type"], "LineString")
        self.assertGreater(data["distance_miles"], 700)
        self.assertAlmostEqual(data["total_gallons"], data["distance_miles"] / 10, delta=0.1)

        # Stops are in order and never more than 500 miles apart; the off-route station is ignored.
        marks = [0.0] + [s["mile_marker"] for s in data["fuel_stops"]] + [data["distance_miles"]]
        self.assertTrue(all(b - a <= 500.01 for a, b in zip(marks, marks[1:])))
        self.assertNotIn(5, [s["station_id"] for s in data["fuel_stops"]])

        # Money adds up exactly to the cent.
        items = [s["cost"] for s in data["fuel_stops"]] + [data["starting_fuel"]["cost"]]
        self.assertAlmostEqual(sum(items), data["total_fuel_cost"], places=2)
        self.assertIn("map_url", data)

    def test_second_identical_request_makes_no_routing_call(self):
        first = self.get().json()
        second = self.get().json()
        self.assertEqual(self.directions.call_count, 1)
        self.assertTrue(second["cached"])
        self.assertEqual(first["total_fuel_cost"], second["total_fuel_cost"])

    def test_post_with_json_body(self):
        resp = self.client.post(reverse("route"), {"start": "Chicago, IL", "finish": "Dallas, Texas"},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_coordinates_input(self):
        resp = self.get(start="41.88,-87.63", finish="32.78,-96.80")
        self.assertEqual(resp.status_code, 200)

    def test_rejects_location_outside_usa(self):
        resp = self.get(start="51.5,-0.12")  # London
        self.assertEqual(resp.status_code, 400)
        self.assertIn("outside the contiguous USA", resp.json()["error"])
        self.directions.assert_not_called()

    def test_missing_parameter(self):
        resp = self.client.get(reverse("route"), {"start": "Chicago, IL"})
        self.assertEqual(resp.status_code, 400)

    def test_no_stations_in_range_returns_422(self):
        Station.objects.all().delete()
        stations.reset()
        resp = self.get()
        self.assertEqual(resp.status_code, 422)

    def test_routing_service_failure_is_reported(self):
        self.directions.side_effect = ors.RoutingQuotaExceeded("quota")
        resp = self.get()
        self.assertEqual(resp.status_code, 503)

    def test_map_page_renders(self):
        resp = self.client.get(reverse("route-map"), {"start": "Chicago, IL", "finish": "Dallas, TX"})
        self.assertContains(resp, "leaflet")


class InputTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Place.objects.bulk_create([
            Place(name="Oklahoma City city", state="OK", norm_name="oklahoma city", lat=35.47, lon=-97.52),
            Place(name="Saint Louis city", state="MO", norm_name="saint louis", lat=38.63, lon=-90.24),
        ])

    def test_city_with_suffix_word_in_name(self):
        p = inputs.resolve("Oklahoma City, OK")
        self.assertEqual(p.source, "gazetteer")

    def test_abbreviation_and_state_name(self):
        self.assertEqual(inputs.resolve("St. Louis, Missouri, USA").source, "gazetteer")

    def test_latlon_forms(self):
        self.assertEqual(inputs.resolve("35.47, -97.52").source, "coordinates")
        self.assertEqual(inputs.resolve("35.47 -97.52").lat, 35.47)

    def test_unknown_text_falls_back_to_geocoder_once(self):
        with mock.patch.object(ors, "geocode", return_value=(35.0, -97.0, "Somewhere, OK")) as g:
            p = inputs.resolve("123 Main St, Norman")
        self.assertEqual(p.source, "geocoder")
        g.assert_called_once()
