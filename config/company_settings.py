"""Commercial main system + operational PWA sharing the existing fleet database.

Opt-in only. Never point this module at the separate pilot database to integrate
production accounts. See docs/integracao-gestao-aplicativo.md before deployment.
"""
import os
from .driver_settings import *  # noqa: F403,F401

CENTRAL_USER_MANAGEMENT = True
MANAGEMENT_ORIGIN = os.getenv('MANAGEMENT_ORIGIN', 'https://transfrota.digital').rstrip('/')
DRIVER_APP_ORIGIN = os.getenv('DRIVER_APP_ORIGIN', 'https://piloto.transfrota.digital').rstrip('/')
ROOT_URLCONF = 'config.company_urls'
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index('apps.driverops.middleware.CompanyBoundaryMiddleware'),
                  'apps.driverops.surfaces.AppSurfaceMiddleware')

from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured
for origin in (MANAGEMENT_ORIGIN, DRIVER_APP_ORIGIN):
    parsed = urlsplit(origin)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or (not DEBUG and parsed.scheme != 'https')):
        raise ImproperlyConfigured('Configure MANAGEMENT_ORIGIN e DRIVER_APP_ORIGIN como origens HTTPS sem caminhos.')
if MANAGEMENT_ORIGIN == DRIVER_APP_ORIGIN:
    raise ImproperlyConfigured('A gestão e o aplicativo devem usar hosts distintos.')
ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, urlsplit(MANAGEMENT_ORIGIN).hostname, urlsplit(DRIVER_APP_ORIGIN).hostname]))
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, MANAGEMENT_ORIGIN, DRIVER_APP_ORIGIN]))

# Companies using the existing Hórus BDT list rather than the app monitor.
HORUS_COMPANY_IDS = tuple(value.strip() for value in os.getenv(
    'HORUS_COMPANY_IDS', '5257b218-6ffe-4e70-a979-86a44a2626d8',
).split(',') if value.strip())

CNH_REQUIRE_REVIEW_CONFIRMATION = True
CNH_BACKGROUND_IMPORTS = os.getenv('CNH_BACKGROUND_IMPORTS', '1') == '1'
