from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from routing.services import ors

GOOD = {
    "features": [{
        "geometry": {"coordinates": [[-87.6, 41.8], [-96.8, 32.7]]},
        "properties": {"summary": {"distance": 1609344.0, "duration": 3600.0}},
    }]
}


def response(status=200, body=None):
    r = mock.Mock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = body if body is not None else GOOD
    r.text = ""
    return r


@override_settings(ORS_API_KEY="test", ORS_RETRIES=1)
class OrsClientTests(SimpleTestCase):
    def test_success_is_one_call_and_converts_units(self):
        with mock.patch.object(ors._session, "request", return_value=response()) as req:
            route = ors.directions((41.8, -87.6), (32.7, -96.8))
        self.assertEqual(req.call_count, 1)
        self.assertAlmostEqual(route.distance_miles, 1000.0)
        self.assertAlmostEqual(route.duration_minutes, 60.0)

    def test_retries_once_after_timeout(self):
        with mock.patch.object(ors._session, "request",
                               side_effect=[requests.Timeout(), response()]) as req:
            ors.directions((41.8, -87.6), (32.7, -96.8))
        self.assertEqual(req.call_count, 2)

    def test_gives_up_after_one_retry(self):
        with mock.patch.object(ors._session, "request", side_effect=requests.Timeout()) as req:
            with self.assertRaises(ors.RoutingError):
                ors.directions((41.8, -87.6), (32.7, -96.8))
        self.assertEqual(req.call_count, 2)

    def test_quota_and_bad_key_are_not_retried(self):
        for status, exc in ((429, ors.RoutingQuotaExceeded), (403, ors.RoutingNotConfigured)):
            with mock.patch.object(ors._session, "request", return_value=response(status, {})) as req:
                with self.assertRaises(exc):
                    ors.directions((41.8, -87.6), (32.7, -96.8))
            self.assertEqual(req.call_count, 1)

    @override_settings(ORS_API_KEY="")
    def test_missing_key(self):
        with self.assertRaises(ors.RoutingNotConfigured):
            ors.directions((41.8, -87.6), (32.7, -96.8))
