from unittest import mock

import numpy as np
from django.test import SimpleTestCase, override_settings

from routing.services import ors, osrm, routes

A, B = (41.88, -87.63), (32.78, -96.80)


def a_route():
    return ors.OrsRoute(np.array([-87.6, -96.8]), np.array([41.8, 32.7]), 900.0, 800.0)


@override_settings(ROUTING_PROVIDER="auto", ORS_COOLDOWN_SECONDS=120)
class ProviderSelectionTests(SimpleTestCase):
    def setUp(self):
        routes.reset()
        self.addCleanup(routes.reset)

    def test_ors_is_used_when_healthy(self):
        with mock.patch.object(ors, "directions", return_value=a_route()) as o, \
             mock.patch.object(osrm, "directions") as f:
            _, provider = routes.directions(A, B)
        self.assertEqual(provider, "ors")
        o.assert_called_once()
        f.assert_not_called()

    def test_falls_back_to_osrm_when_ors_fails_then_skips_ors_during_cooldown(self):
        with mock.patch.object(ors, "directions", side_effect=ors.RoutingError("timeout")) as o, \
             mock.patch.object(osrm, "directions", return_value=a_route()) as f:
            _, first = routes.directions(A, B)
            _, second = routes.directions(A, B)
        self.assertEqual((first, second), ("osrm", "osrm"))
        self.assertEqual(o.call_count, 1)       # second request didn't wait on ORS again
        self.assertEqual(f.call_count, 2)

    def test_quota_and_bad_key_also_fall_back(self):
        for exc in (ors.RoutingQuotaExceeded("quota"), ors.RoutingNotConfigured("bad key")):
            routes.reset()
            with mock.patch.object(ors, "directions", side_effect=exc), \
                 mock.patch.object(osrm, "directions", return_value=a_route()):
                self.assertEqual(routes.directions(A, B)[1], "osrm")

    def test_no_route_is_not_masked_by_fallback(self):
        with mock.patch.object(ors, "directions", side_effect=ors.NoRouteFound("none")), \
             mock.patch.object(osrm, "directions") as f:
            with self.assertRaises(ors.NoRouteFound):
                routes.directions(A, B)
        f.assert_not_called()

    @override_settings(ROUTING_PROVIDER="osrm")
    def test_osrm_only_mode(self):
        with mock.patch.object(ors, "directions") as o, \
             mock.patch.object(osrm, "directions", return_value=a_route()):
            self.assertEqual(routes.directions(A, B)[1], "osrm")
        o.assert_not_called()
