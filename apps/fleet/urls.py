from django.urls import path, include
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

urlpatterns = [
    path('dashboard/', DashboardAPIView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]
