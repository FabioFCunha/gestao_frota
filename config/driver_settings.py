"""Configuração exclusiva de homologação do app. Não altera settings de produção."""
from .settings import *  # noqa: F403,F401

INSTALLED_APPS = [*INSTALLED_APPS, "apps.driverops"]
ROOT_URLCONF = "config.driver_urls"
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"driver_login": "10/min"},
}

MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
    "apps.driverops.middleware.CompanyBoundaryMiddleware",
)
