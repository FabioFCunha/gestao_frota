"""Authenticated address suggestions; no user identity is sent to the geocoder."""
import hashlib
import math
import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from .authentication import DeviceAuthentication
from .views import member_for


class AddressThrottle(UserRateThrottle):
    scope = 'driver_addresses'
    rate = '30/min'


def point(value):
    if value is None:
        return {'destination_latitude': None, 'destination_longitude': None}
    if not isinstance(value, dict):
        raise ValidationError('Coordenadas do destino inválidas.')
    lat, lon = value.get('latitude'), value.get('longitude')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)):
        raise ValidationError('Coordenadas do destino inválidas.')
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValidationError('Coordenadas do destino fora do intervalo permitido.')
    return {'destination_latitude': lat, 'destination_longitude': lon}


def leg_destinations(request, values):
    points = request.data.get('destination_points')
    if points is None:
        points = [None] * len(values)
    if not isinstance(points, list) or len(points) != len(values):
        raise ValidationError('Coordenadas devem corresponder à ordem dos destinos.')
    return [dict(destination=label, **point(location)) for label, location in zip(values, points)]


@api_view(['GET'])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AddressThrottle])
def suggestions(request):
    member = member_for(request)
    query = ' '.join(request.query_params.get('q', '').split())
    if not 4 <= len(query) <= 160:
        raise ValidationError('Digite entre 4 e 160 caracteres para buscar um endereço.')
    endpoint = getattr(settings, 'DRIVER_GEOCODER_URL', 'https://photon.komoot.io/api/')
    key = 'driver-address:' + str(member.company_id) + ':' + hashlib.sha256((endpoint + query.casefold()).encode()).hexdigest()
    items = cache.get(key)
    if items is None:
        try:
            response = requests.get(endpoint, params={'q': query, 'limit': 5, 'countrycode': 'BR'},
                headers={'User-Agent': 'Transfrota-address-search/1.0', 'Accept': 'application/json'},
                timeout=(2, 5), allow_redirects=False)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Unexpected response')
            payload = response.json()
            features = payload.get('features', [])
            if not isinstance(features, list):
                raise ValueError('Invalid suggestions')
            items = []
            for feature in features[:5]:
                try:
                    props = feature['properties']
                    if str(props.get('countrycode', '')).upper() != 'BR':
                        continue
                    lon, lat = feature['geometry']['coordinates'][:2]
                    point({'latitude': lat, 'longitude': lon})
                    parts = [props.get('name'), ' '.join(str(props.get(k) or '') for k in ('street', 'housenumber')).strip(),
                             props.get('district'), props.get('city') or props.get('county'), props.get('state'), props.get('postcode')]
                    label = ', '.join(dict.fromkeys(str(p).strip() for p in parts if p))
                    if label and len(label) <= 300:
                        item = {'label': label, 'latitude': lat, 'longitude': lon}
                        if item not in items:
                            items.append(item)
                except (KeyError, TypeError, ValueError, ValidationError):
                    continue
            cache.set(key, items, 300)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return Response({'detail': 'Busca indisponível. Você pode informar o endereço completo manualmente.'}, status=503)
    result = Response({'results': items, 'attribution': '© OpenStreetMap contributors · Photon'})
    result['Cache-Control'] = 'private, no-store'
    return result
