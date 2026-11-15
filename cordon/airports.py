"""The FAA's Core 30 airports, for measuring how close a flight restriction or program sits to the busiest US traffic.

List: the FAA's ASPM help page "Core 30" (aspm.faa.gov/aspmhelp/index/Core_30.html, read 15 Nov 2026), 30 airports.
Coordinates: OurAirports (ourairports.com/data, airports.csv, downloaded 15 Nov 2026; its data is released to the
public domain), the airport reference point, rounded to 4 decimals.
"""
import math

CORE30_SOURCE = ("FAA ASPM Core 30 list (aspm.faa.gov/aspmhelp/index/Core_30.html, read 15 Nov 2026); coordinates "
                 "from OurAirports (public domain, downloaded 15 Nov 2026)")
CORE30 = {
    "ATL": (33.6367, -84.4281), "BOS": (42.362, -71.0079), "BWI": (39.1754, -76.6683), "CLT": (35.214, -80.9431),
    "DCA": (38.8521, -77.0377), "DEN": (39.86, -104.6738), "DFW": (32.8968, -97.038), "DTW": (42.2138, -83.3538),
    "EWR": (40.6894, -74.1705), "FLL": (26.0726, -80.1527), "HNL": (21.3184, -157.9257), "IAD": (38.9445, -77.4558),
    "IAH": (29.9844, -95.3414), "JFK": (40.6394, -73.7793), "LAS": (36.0834, -115.1518), "LAX": (33.9425, -118.408),
    "LGA": (40.7772, -73.8726), "MCO": (28.4294, -81.309), "MDW": (41.786, -87.7524), "MEM": (35.0438, -89.9763),
    "MIA": (25.796, -80.2898), "MSP": (44.8801, -93.2217), "ORD": (41.9786, -87.9048), "PHL": (39.8719, -75.2411),
    "PHX": (33.4353, -112.0059), "SAN": (32.7336, -117.19), "SEA": (47.4479, -122.3103), "SFO": (37.6198, -122.3748),
    "SLC": (40.7889, -111.9799), "TPA": (27.9755, -82.5332),
}


def km(a, b) -> float:
    """Great-circle distance in km between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, h)))


def nearest_core30(points) -> tuple[str, float] | None:
    """(airport, km) of the Core 30 airport nearest any of the (lat, lon) points, or None for no points."""
    best = None
    for p in points:
        for code, q in CORE30.items():
            d = km(p, q)
            if best is None or d < best[1]:
                best = (code, d)
    return (best[0], round(best[1], 1)) if best else None
