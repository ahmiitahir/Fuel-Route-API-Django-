# Fuel Route API

Django API that takes a start and finish location in the USA and returns:

* the driving route (GeoJSON, plus an interactive Leaflet map page),
* the cost-optimal fuel stops along it, given a **500-mile range**,
* the total money spent on fuel at **10 mpg**, using the supplied fuel-price file.

Built with Django 6.1, Django REST Framework, and the free [OpenRouteService](https://openrouteservice.org) (ORS) routing API.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env            # then put your free ORS key in ORS_API_KEY
python manage.py migrate
python manage.py load_places      # Census gazetteer -> Place table   (see "Data pipeline")
python manage.py load_stations    # data/stations_geocoded.csv -> Station table
python manage.py runserver
```

Get a free ORS key at <https://openrouteservice.org/dev/#/signup> (Dashboard → Request a token → Free; 2,000 requests/day).

Then open <http://127.0.0.1:8000/> for the map UI, or call the API:

```bash
curl "http://127.0.0.1:8000/api/route/?start=Los%20Angeles,%20CA&finish=New%20York,%20NY"

curl -X POST http://127.0.0.1:8000/api/route/ \
     -H "Content-Type: application/json" \
     -d '{"start": "Chicago, IL", "finish": "Dallas, TX"}'
```

`start` / `finish` accept `City, ST` (or full state name), `lat,lon`, or a street address.

### Response (abridged)

```json
{
  "start":  {"label": "Chicago, IL", "lat": 41.83, "lon": -87.68},
  "finish": {"label": "Dallas, TX",  "lat": 32.79, "lon": -96.77},
  "distance_miles": 967.4,
  "duration_minutes": 880,
  "route": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-87.68, 41.83], "..."]}},
  "starting_fuel": {"gallons": 30.1, "price_per_gallon": 3.199, "cost": 96.29},
  "fuel_stops": [
    {"order": 1, "name": "...", "city": "...", "state": "..", "lat": 0, "lon": 0,
     "mile_marker": 301.2, "price_per_gallon": 3.049, "gallons_purchased": 50.0, "cost": 152.45}
  ],
  "total_gallons": 96.74,
  "total_fuel_cost": 305.7,
  "map_url": "http://127.0.0.1:8000/api/route/map/?start=...&finish=...",
  "assumptions": {"vehicle_range_miles": 500, "miles_per_gallon": 10, "...": "..."}
}
```

Errors are JSON `{"error": "..."}`: `400` bad / non-US input, `422` no feasible stop pattern, `503` routing service unavailable or quota hit.

## How it works

1. **Resolve inputs without API calls.** `City, ST` is looked up in a local gazetteer table; `lat,lon` is parsed directly. Only a street address needs ORS geocoding.
2. **One routing call.** A single ORS `driving-car` request returns the geometry, distance and duration. The whole result is cached per start/finish, so repeats make **zero** calls. The free ORS server occasionally stalls for a minute on a normally 1–3 s request, so ORS has an 8 s timeout and, if it fails (timeout, 5xx, quota, bad key), the request falls back to the free keyless public OSRM demo server and ORS is skipped for 2 minutes. Worst case is therefore 2 routing calls per trip; the response reports which one answered in `routing_provider`. Set `ROUTING_PROVIDER=ors` or `osrm` in `.env` to pin one.
3. **Find stations near the route.** All stations sit in an in-memory numpy index. The route is decimated to ~1 point per mile, far stations are dropped with a coarse filter, and the survivors are projected onto route segments to get a *mile marker* and distance from the route (default corridor 10 miles, widened to 25 if the route is otherwise undrivable).
4. **Optimal fuelling.** The classic gas-station greedy: at each stop, if a cheaper station is within range, buy only enough to reach it; otherwise fill the tank and head to the cheapest station in range. It is verified against a brute-force dynamic program in the tests.

### Cost model / assumptions

* Tank = 500 mi ÷ 10 mpg = **50 gallons**. The vehicle ends at the destination with an empty tank (buys exactly what it needs).
* "Start full, pay for fuel burned": the fuel for the first leg is priced at the cheapest station within ~50 miles of the start (`starting_fuel`), so short trips still show a real cost, and `total_gallons = distance / 10`.
* A station's price is the **lowest** price listed for it in the file (678 station IDs repeat, mostly with different prices).
* Extra driving to reach a station off the route is reported (`distance_from_route_miles`) but not added to the cost.
* Contiguous USA only (Alaska/Hawaii rejected).

## Data pipeline

The price file has no coordinates, so stations are geocoded once, offline, and the result is committed in `data/stations_geocoded.csv`:

```bash
# only needed to regenerate the file
python manage.py load_places
python manage.py geocode_stations --nominatim
python manage.py load_stations
```

City/state is matched to the US Census 2024 Gazetteer (public domain; download `2024_Gaz_place_national.zip` from census.gov into `data/downloads/gaz/`). Cities the gazetteer lacks (New England towns, merged city-county names) fall back to OpenStreetMap Nominatim, 1 request/second.

**Limitation:** stations are placed at their *city's* centroid, not their exact address (the file only has highway exits like `I-44, EXIT 283`). The generous corridor absorbs this, but a stop's marker can be a few miles from the real station.

## Tests

```bash
python manage.py test routing
```

Covers the optimizer (including a randomized comparison to brute force), route geometry, input parsing, provider fallback, and the API with a mocked routing client that asserts **exactly one routing call** per new trip and none on repeats.

Live check (real routers, warm server): Chicago→Dallas 961 mi / 6 stops / $283.14 in ~0.2 s; Seattle→Miami 3,303 mi / 19 stops / $1,026.91 in ~0.6 s; repeating a trip takes ~5 ms and makes no routing call. Station geocoding coverage: 6,601 of 6,626 US stations (99.6%).
