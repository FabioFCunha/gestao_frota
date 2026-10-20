from django.urls import include, path
from .urls import urlpatterns as existing_patterns

urlpatterns = [
    path("api/driver/", include("apps.driverops.urls")),
    *existing_patterns,
]
