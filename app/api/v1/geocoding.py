"""
Geocoding and reverse-geocoding endpoints for NammaClean.
Provides place search and coordinate-to-address resolution for Bengaluru civic reporting.
Uses local curated Bengaluru landmarks with OpenStreetMap Nominatim fallback and caching.
"""

import json
import logging
import math
import urllib.parse
import urllib.request
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/geocoding", tags=["Geocoding"])


class PlaceSearchResult(BaseModel):
    place_id: str
    display_name: str
    latitude: float
    longitude: float
    locality: Optional[str] = None
    zone: Optional[str] = None


class ReverseGeocodeResponse(BaseModel):
    display_name: str
    locality: Optional[str] = None
    latitude: float
    longitude: float
    selection_method: str = "manual"


# Curated Bengaluru landmarks and localities for instant offline/test resolution
BENGALURU_PLACES = [
    {"name": "Yelahanka New Town", "zone": "Yelahanka Zone", "lat": 13.0985, "lon": 77.5895, "keywords": ["yelahanka", "new town", "sector 4", "avalhalli", "bmsit"]},
    {"name": "Yelahanka Old Town", "zone": "Yelahanka Zone", "lat": 13.1007, "lon": 77.5963, "keywords": ["yelahanka", "old town", "market", "railway station"]},
    {"name": "Hebbal", "zone": "North Zone", "lat": 13.0358, "lon": 77.5970, "keywords": ["hebbal", "flyover", "hebbal lake", "bellary road"]},
    {"name": "Jakkur", "zone": "Yelahanka Zone", "lat": 13.0784, "lon": 77.6067, "keywords": ["jakkur", "aerodrome", "jakkur lake", "flying club"]},
    {"name": "Indiranagar", "zone": "East Zone", "lat": 12.9784, "lon": 77.6408, "keywords": ["indiranagar", "100ft road", "12th main", "defense colony"]},
    {"name": "Koramangala", "zone": "South Zone", "lat": 12.9352, "lon": 77.6245, "keywords": ["koramangala", "5th block", "sony world", "forum"]},
    {"name": "Whitefield", "zone": "Mahadevapura Zone", "lat": 12.9698, "lon": 77.7500, "keywords": ["whitefield", "itpl", "hope farm", "kadugodi"]},
    {"name": "Jayanagar", "zone": "South Zone", "lat": 12.9308, "lon": 77.5838, "keywords": ["jayanagar", "4th block", "shopping complex", "south end"]},
    {"name": "Malleshwaram", "zone": "West Zone", "lat": 13.0031, "lon": 77.5643, "keywords": ["malleshwaram", "8th cross", "sampige road", "margosa"]},
    {"name": "Rajajinagar", "zone": "West Zone", "lat": 12.9982, "lon": 77.5530, "keywords": ["rajajinagar", "1st block", "orion mall", "navrang"]},
    {"name": "HSR Layout", "zone": "Bommanahalli Zone", "lat": 12.9121, "lon": 77.6446, "keywords": ["hsr", "hsr layout", "sector 1", "sector 2", "27th main"]},
    {"name": "Banashankari", "zone": "South Zone", "lat": 12.9255, "lon": 77.5468, "keywords": ["banashankari", "bsk", "temple", "bus stand"]},
    {"name": "Central Bengaluru (Vidhana Soudha)", "zone": "East Zone", "lat": 12.9797, "lon": 77.5907, "keywords": ["central", "vidhana soudha", "mg road", "cubbon park", "majestic"]},
    {"name": "Marathahalli", "zone": "Mahadevapura Zone", "lat": 12.9591, "lon": 77.6974, "keywords": ["marathahalli", "bridge", "outer ring road", "multiplex"]},
    {"name": "Bellandur", "zone": "Mahadevapura Zone", "lat": 12.9304, "lon": 77.6784, "keywords": ["bellandur", "ecospace", "lake", "outer ring road"]},
    {"name": "Electronic City", "zone": "Bommanahalli Zone", "lat": 12.8452, "lon": 77.6602, "keywords": ["electronic city", "phase 1", "phase 2", "infosys", "wipro"]},
]

# Simple in-memory cache for external lookups
_CACHE_SEARCH = {}
_CACHE_REVERSE = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


@router.get("/search", response_model=List[PlaceSearchResult])
async def search_places(
    q: str = Query(..., min_length=2, max_length=100, description="Place search query for Bengaluru"),
) -> List[PlaceSearchResult]:
    query_clean = q.strip().lower()
    results: List[PlaceSearchResult] = []

    # 1. Match local curated places
    for p in BENGALURU_PLACES:
        matched = False
        if query_clean in p["name"].lower():
            matched = True
        elif any(k in query_clean or query_clean in k for k in p.get("keywords", [])):
            matched = True
        if matched:
            results.append(
                PlaceSearchResult(
                    place_id=f"local-{p['name'].replace(' ', '_').lower()}",
                    display_name=f"{p['name']}, Bengaluru, Karnataka",
                    latitude=p["lat"],
                    longitude=p["lon"],
                    locality=p["name"],
                    zone=p["zone"],
                )
            )

    # 2. If results found locally, return up to 5
    if results:
        return results[:5]

    # 3. Check memory cache
    if query_clean in _CACHE_SEARCH:
        return _CACHE_SEARCH[query_clean]

    # 4. Optional query to Nominatim bounded to Bengaluru
    try:
        encoded_q = urllib.parse.quote(f"{q}, Bengaluru, Karnataka")
        url = (
            f"https://nominatim.openstreetmap.org/search?format=json&q={encoded_q}"
            f"&viewbox=77.3,13.2,77.8,12.8&bounded=0&limit=5"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NammaClean-CivicApp/1.0 (civic-waste-mgmt; Bengaluru)"}
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            for item in data:
                lat = float(item["lat"])
                lon = float(item["lon"])
                results.append(
                    PlaceSearchResult(
                        place_id=str(item.get("place_id", f"{lat}_{lon}")),
                        display_name=item.get("display_name", q),
                        latitude=lat,
                        longitude=lon,
                        locality=item.get("name") or q,
                        zone="Bengaluru",
                    )
                )
            _CACHE_SEARCH[query_clean] = results[:5]
            return results[:5]
    except Exception as exc:
        logger.debug("External geocoding query failed (%s), returning fallback", exc)

    # Fallback to closest local landmark if no results
    default_p = BENGALURU_PLACES[0]
    return [
        PlaceSearchResult(
            place_id="fallback-default",
            display_name=f"{default_p['name']}, Bengaluru",
            latitude=default_p["lat"],
            longitude=default_p["lon"],
            locality=default_p["name"],
            zone=default_p["zone"],
        )
    ]


@router.get("/reverse", response_model=ReverseGeocodeResponse)
async def reverse_geocode(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    method: str = Query(default="manual", description="Selection method"),
) -> ReverseGeocodeResponse:
    # 1. Check if close to a curated place (< 2.5 km)
    closest = None
    min_dist = 9999.0
    for p in BENGALURU_PLACES:
        d = _haversine_km(latitude, longitude, p["lat"], p["lon"])
        if d < min_dist:
            min_dist = d
            closest = p

    if closest and min_dist <= 2.5:
        return ReverseGeocodeResponse(
            display_name=f"{closest['name']}, Bengaluru (±{min_dist:.1f} km)",
            locality=closest["name"],
            latitude=round(latitude, 6),
            longitude=round(longitude, 6),
            selection_method=method,
        )

    # 2. Check memory cache
    cache_key = f"{round(latitude, 4)}_{round(longitude, 4)}"
    if cache_key in _CACHE_REVERSE:
        cached = _CACHE_REVERSE[cache_key]
        cached.selection_method = method
        return cached

    # 3. Optional query to Nominatim reverse
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?format=json"
            f"&lat={latitude}&lon={longitude}&zoom=17&addressdetails=1"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NammaClean-CivicApp/1.0 (civic-waste-mgmt; Bengaluru)"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode())
            addr = data.get("address", {})
            suburb = (
                addr.get("suburb") or
                addr.get("neighbourhood") or
                addr.get("residential") or
                addr.get("road") or
                "Bengaluru"
            )
            display = data.get("display_name", f"{suburb}, Bengaluru")
            result = ReverseGeocodeResponse(
                display_name=display,
                locality=suburb,
                latitude=round(latitude, 6),
                longitude=round(longitude, 6),
                selection_method=method,
            )
            _CACHE_REVERSE[cache_key] = result
            return result
    except Exception as exc:
        logger.debug("External reverse geocoding failed (%s)", exc)

    # Sensible fallback
    loc_name = closest["name"] if closest else "Bengaluru"
    return ReverseGeocodeResponse(
        display_name=f"Selected location near {loc_name}, Bengaluru",
        locality=loc_name,
        latitude=round(latitude, 6),
        longitude=round(longitude, 6),
        selection_method=method,
    )
