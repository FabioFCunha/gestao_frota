from django.urls import path
from .driver_urls import urlpatterns as existing_patterns
from apps.driverops.management import management
from apps.driverops.portal import dashboard

urlpatterns = [path('empresas/', management, name='company_management'),
               path('gestao/bdts/', dashboard, name='company_trips'), *existing_patterns]
