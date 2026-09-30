from django.urls import path, include
from .sync_views import BDTSyncAPIView
from .bdt_views import BDTViewSet
from .sync_vehicle_views import VehicleSyncAPIView
from .sync_driver_views import DriverSyncAPIView
from rest_framework.routers import DefaultRouter
from .views import MaintenanceViewSet, VehicleViewSet, VehicleCustodyViewSet, VehicleInspectionViewSet, VehicleFineViewSet, SEIProcessViewSet, DocumentViewSet, DashboardAPIView

router = DefaultRouter()
router.register("vehicles", VehicleViewSet)
router.register("vehicle-custodies", VehicleCustodyViewSet)
router.register("maintenances", MaintenanceViewSet)
router.register("vehicle-inspections", VehicleInspectionViewSet)
router.register("vehicle-fines", VehicleFineViewSet)
router.register("sei-processes", SEIProcessViewSet)
router.register("documents", DocumentViewSet)
router.register("bdts", BDTViewSet, basename="bdt")

urlpatterns = [
    path('sync/vehicles/', VehicleSyncAPIView.as_view(), name='sync-vehicles'),
    path('sync/drivers/', DriverSyncAPIView.as_view(), name='sync-drivers'),
    path('sync/bdts/', BDTSyncAPIView.as_view(), name='sync-bdts'),
    path('dashboard/', DashboardAPIView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]
