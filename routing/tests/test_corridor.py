import numpy as np
from django.test import SimpleTestCase

from routing.services import corridor


def straight_route(lat0, lon0, lat1, lon1, n=2000):
    lats = np.linspace(lat0, lat1, n)
    lons = np.linspace(lon0, lon1, n)
    return lons, lats, corridor.cumulative_miles(lons, lats)


class CorridorTests(SimpleTestCase):
    def test_cumulative_miles_known_distance(self):
        # 1 degree of latitude is ~69.1 miles
        cum = corridor.cumulative_miles(np.array([-100.0, -100.0]), np.array([40.0, 41.0]))
        self.assertAlmostEqual(cum[-1], 69.1, delta=0.2)

    def test_decimation_keeps_ends_and_total_length(self):
        lons, lats, cum = straight_route(40, -100, 40, -90)
        dl, da, dc = corridor.decimate(lons, lats, cum, step_miles=2.0)
        self.assertLess(len(dl), len(lons) / 4)
        self.assertEqual(dc[0], 0.0)
        self.assertAlmostEqual(dc[-1], cum[-1])

    def test_projection_distance_and_mile_marker(self):
        lons, lats, cum = straight_route(40, -100, 40, -90)
        dl, da, dc = corridor.decimate(lons, lats, cum)
        st_lat = np.array([40.05, 41.0, 39.9, 40.0])
        st_lon = np.array([-95.0, -95.0, -99.0, -80.0])   # last one is past the end
        idx, dist, mile = corridor.project_stations(st_lat, st_lon, dl, da, dc, corridor_miles=10)
        self.assertEqual(sorted(idx.tolist()), [0, 2])     # 41.0 is ~69 mi away; -80 is off the end
        by = dict(zip(idx.tolist(), zip(dist, mile)))
        self.assertAlmostEqual(by[0][0], 0.05 * 69.093, delta=0.3)
        self.assertAlmostEqual(by[0][1], cum[-1] / 2, delta=1.0)   # roughly mid-route
        self.assertAlmostEqual(by[2][1], cum[-1] / 10, delta=1.0)

    def test_matches_brute_force_on_diagonal_route(self):
        rng = np.random.default_rng(3)
        lons, lats, cum = straight_route(34.0, -118.0, 41.0, -74.0, n=6000)
        dl, da, dc = corridor.decimate(lons, lats, cum)
        st_lat = rng.uniform(33, 42, 3000)
        st_lon = rng.uniform(-119, -73, 3000)
        idx, dist, mile = corridor.project_stations(st_lat, st_lon, dl, da, dc, corridor_miles=10)

        # Brute force against the dense polyline using haversine to every vertex.
        def hav(la1, lo1, la2, lo2):
            p1, p2 = np.radians(la1), np.radians(la2)
            a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2
            return 2 * corridor.EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))

        expected = set()
        for i in range(len(st_lat)):
            if hav(st_lat[i], st_lon[i], lats, lons).min() <= 9.0:   # safely inside the corridor
                expected.add(i)
        got = set(idx.tolist())
        self.assertTrue(expected <= got, f"missed {expected - got}")
        self.assertTrue(all(d <= 10 for d in dist))
