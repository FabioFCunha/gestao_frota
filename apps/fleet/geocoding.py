"""Reverse-geocoding helper and API endpoint for BDT addresses."""

import logging
import requests
from django.http import JsonResponse
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes

from .models import BDT
from .sector_scope import user_can_access_vehicle

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_TIMEOUT = 5
USER_AGENT = "GestaoFrotas/1.0 (sistema interno)"


def _format_address(data):
    """
    Build a friendly address string from Nominatim response data.
    Returns a string like "Rua das Palmeiras, 120 — Centro, Rio de Janeiro/RJ"
    """
    if not data or "address" not in data:
        return None

    addr = data["address"]
    parts = []

    # Street / road
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or ""
    house_number = addr.get("house_number", "")
    if road:
        street_part = road
        if house_number:
            street_part += ", " + house_number
        parts.append(street_part)

    # Neighbourhood / suburb
    neighbourhood = (
        addr.get("neighbourhood")
        or addr.get("suburb")
        or addr.get("quarter")
        or ""
    )
    if neighbourhood:
        parts.append(neighbourhood)

    # City
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("municipality")
        or addr.get("village")
        or ""
    )
    state = addr.get("state", "")
    if city and state:
        parts.append(city + "/" + state)
    elif city:
        parts.append(city)
    elif state:
        parts.append(state)

    if not parts:
        # Fallback: use display_name from Nominatim
        return data.get("display_name") or None

    return " \u2014 ".join(parts)


def reverse_geocode(lat, lon):
    """
    Call Nominatim reverse geocoding API.
    Returns a formatted address string, or None on failure.
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "lat": str(lat),
                "lon": str(lon),
                "format": "jsonv2",
                "addressdetails": "1",
                "accept-language": "pt-BR",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            logger.warning("Nominatim error for (%s, %s): %s", lat, lon, data["error"])
            return None

        return _format_address(data)
    except requests.RequestException as e:
        logger.warning("Nominatim request failed for (%s, %s): %s", lat, lon, e)
        return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def geocode_bdt(request, pk):
    """
    POST /api/bdts/<pk>/geocode/
    Geocodes departure and return coordinates for a BDT.
    Saves results to departure_address and return_address fields.
    Returns the addresses as JSON.
    """
    try:
        bdt = BDT.objects.select_related("vehicle").get(pk=pk)
    except BDT.DoesNotExist:
        return JsonResponse({"error": "BDT not found"}, status=404)

    if bdt.vehicle_id and not user_can_access_vehicle(request.user, bdt.vehicle):
        return JsonResponse({"error": "Acesso negado."}, status=403)

    try:
        bdt = bdt
    changed = False

    # Geocode departure (match) coordinates
    if (
        bdt.latitude_match is not None
        and bdt.longitude_match is not None
        and not bdt.departure_address
    ):
        addr = reverse_geocode(bdt.latitude_match, bdt.longitude_match)
        if addr:
            bdt.departure_address = addr
            changed = True

    # Geocode return (retreat) coordinates
    if (
        bdt.latitude_retreat is not None
        and bdt.longitude_retreat is not None
        and not bdt.return_address
    ):
        addr = reverse_geocode(bdt.latitude_retreat, bdt.longitude_retreat)
        if addr:
            bdt.return_address = addr
            changed = True

    if changed:
        bdt.save(update_fields=["departure_address", "return_address"])

    return JsonResponse({
        "departure_address": bdt.departure_address or None,
        "return_address": bdt.return_address or None,
    })
