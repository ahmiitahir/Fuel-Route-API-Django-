import logging
import time
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteRequestSerializer
from routing.services import inputs, ors, planner

logger = logging.getLogger(__name__)


class RouteView(APIView):
    """Plan a drive between two US locations with cost-optimal fuel stops.

    GET  /api/route/?start=Chicago,IL&finish=Dallas,TX
    POST /api/route/  {"start": "Chicago, IL", "finish": "Dallas, TX"}
    """

    def get(self, request):
        return self._handle(request.query_params)

    def post(self, request):
        return self._handle(request.data)

    def _handle(self, data):
        ser = RouteRequestSerializer(data=data)
        ser.is_valid(raise_exception=True)
        began = time.perf_counter()
        try:
            start = inputs.resolve(ser.validated_data["start"], "start")
            finish = inputs.resolve(ser.validated_data["finish"], "finish")
            if (start.lat, start.lon) == (finish.lat, finish.lon):
                raise inputs.InvalidLocation("'start' and 'finish' are the same place.")
            result = planner.plan_trip(start, finish)
        except inputs.InvalidLocation as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except planner.NoFeasiblePlan as exc:
            return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ors.RoutingError as exc:
            logger.warning("routing failure: %s", exc)
            return Response({"error": str(exc)}, status=exc.status)

        query = urlencode({"start": ser.validated_data["start"], "finish": ser.validated_data["finish"]})
        result["map_url"] = self.request.build_absolute_uri(reverse("route-map") + "?" + query)
        result["compute_ms"] = round((time.perf_counter() - began) * 1000)
        return Response(result)


def route_map(request):
    """HTML page that calls the API and draws the route + stops on a Leaflet map."""
    return render(request, "routing/map.html", {
        "api_url": reverse("route"),
        "start": request.GET.get("start", ""),
        "finish": request.GET.get("finish", ""),
    })
