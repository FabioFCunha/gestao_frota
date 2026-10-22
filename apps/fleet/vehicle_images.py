"""IMAGIN URLs and metadata only; vehicle/document data is never changed."""
import re
import unicodedata
from functools import lru_cache
from urllib.parse import urlencode

import requests
from django.conf import settings

# Edit these aliases as new CRLV abbreviations are encountered.
BRAND_ALIASES = {
    'gm': 'chevrolet', 'chev': 'chevrolet', 'gm-chev': 'chevrolet',
    'gm-chevrolet': 'chevrolet', 'chevrolet': 'chevrolet',
    'vw': 'volkswagen', 'volks': 'volkswagen', 'm-benz': 'mercedes-benz',
    'mbenz': 'mercedes-benz', 'mercedes': 'mercedes-benz',
    'i-toyota': 'toyota', 'i-chevrolet': 'chevrolet', 'i-byd': 'byd',
}
MODEL_FAMILIES = {
    'toyota': ('corolla-cross', 'corolla', 'hilux-sw4', 'hilux', 'yaris', 'etios'),
    'chevrolet': ('onix-plus', 'onix', 'spin', 'cruze', 'tracker', 's10', 'montana'),
    'volkswagen': ('polo', 'virtus', 'voyage', 'gol', 't-cross', 'nivus', 'saveiro', 'amarok'),
    'byd': ('king', 'dolphin-mini', 'dolphin', 'song-plus', 'song-pro', 'seal', 'yuan-plus'),
}


def slug(value):
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def normalize_vehicle(marca, modelo, ano=None):
    make = slug(marca)
    make = BRAND_ALIASES.get(make, make)
    if make.startswith('i-'):
        make = BRAND_ALIASES.get(make[2:], make[2:])
    family = slug(modelo)
    for prefix in sorted({make, slug(marca), *[a for a,b in BRAND_ALIASES.items() if b == make]}, key=len, reverse=True):
        if prefix and family.startswith(prefix + '-'):
            family = family[len(prefix)+1:]
            break
    for known in MODEL_FAMILIES.get(make, ()):
        if family == known or family.startswith(known + '-'):
            family = known
            break
    else:
        # Remove engine/trim suffixes, keeping multiword model families intact.
        family = re.split(r'-(?:\d+(?:mt|at|t|v|cv)?|lt\d*|ltz|premier|xlt|xls|gl|gls|gs|premium)(?:-|$)', family, maxsplit=1)[0]
    year = str(ano or '').strip()
    year = year if re.fullmatch(r'[12][0-9]{3}', year) else None
    return make, family, year


@lru_cache(maxsize=2048)
def _cached_url(customer, make, family, year):
    params = {'customer': customer, 'make': make, 'modelFamily': family,
              'angle': '23', 'zoomtype': 'fullscreen'}
    if year:
        params['modelYear'] = year
    return 'https://cdn.imagin.studio/getImage?' + urlencode(params)


def url_imagem_veiculo(marca, modelo, ano=None):
    make, family, year = normalize_vehicle(marca, modelo, ano)
    customer = getattr(settings, 'IMAGIN_CUSTOMER_KEY', '').strip()
    if not customer or not make or not family:
        return None
    return _cached_url(customer, make, family, year)


def classify_headers(headers):
    headers = {k.lower(): str(v).lower() for k,v in headers.items()}
    if not headers.get('content-type', '').startswith('image/'):
        return 'invalid_content_type'
    found = headers.get('x-imaginstudio-request-found')
    resolved = headers.get('x-imaginstudio-request-resolved')
    if found == 'false' or resolved == 'false':
        return 'placeholder'
    # Unknown responses are not presented as verified model photographs.
    if found != 'true' or resolved != 'true':
        return 'unverified'
    return 'image'


def probe_image(marca, modelo, ano=None):
    make, family, year = normalize_vehicle(marca, modelo, ano)
    if not make or not family:
        return 'missing_data'
    url = url_imagem_veiculo(marca, modelo, ano)
    if not url:
        return 'missing_customer_key'
    try:
        # Inspect metadata without downloading/storing licensed image files.
        response = requests.head(url, timeout=5, allow_redirects=False)
        if response.status_code != 200:
            return 'http_' + str(response.status_code)
        return classify_headers(response.headers)
    except requests.RequestException:
        return 'network_error'
