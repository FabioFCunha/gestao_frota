"""Curated Wikimedia Commons model photos; no keys or runtime external requests."""
import re
import unicodedata
from functools import lru_cache


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


@lru_cache(maxsize=1)
def image_catalog():
    import json
    from pathlib import Path
    path = Path(__file__).with_name('data') / 'vehicle_images.json'
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def imagem_veiculo(marca, modelo, ano=None):
    from django.templatetags.static import static
    make, family, _ = normalize_vehicle(marca, modelo, ano)
    if not make or not family:
        return None
    item = image_catalog().get(f'{make}/{family}')
    if not isinstance(item, dict):
        return None
    # Only curated local assets and fully credited, reusable Commons files.
    path = item.get('image', '')
    if not path.startswith('ui/vehicle_models/') or '..' in path:
        return None
    if not all(item.get(field) for field in ('author', 'source', 'license', 'license_url')):
        return None
    if item['license'] not in {'CC0', 'CC BY 4.0', 'CC BY-SA 3.0', 'CC BY-SA 4.0'}:
        return None
    return {**item, 'url': static(path)}


def url_imagem_veiculo(marca, modelo, ano=None):
    item = imagem_veiculo(marca, modelo, ano)
    return item['url'] if item else None


def probe_image(marca, modelo, ano=None):
    from django.contrib.staticfiles import finders
    make, family, _ = normalize_vehicle(marca, modelo, ano)
    if not make or not family:
        return 'missing_data'
    item = imagem_veiculo(marca, modelo, ano)
    if not item:
        return 'missing_catalog'
    return 'image' if finders.find(item['image']) else 'missing_file'
