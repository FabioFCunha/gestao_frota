from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.fleet.models import Driver, Maintenance, MaintenanceStatus, MaintenanceType, Vehicle, VehicleExitOrder, VehicleStatus
from apps.fleet.services import set_vehicle_active


class VehicleActiveTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operator")
        self.status = VehicleStatus.objects.create(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.status, created_by=self.user)

    def test_inactivation_creates_history_and_audit(self):
        set_vehicle_active(vehicle=self.vehicle, active=False, user=self.user, reason="Baixa")
        self.vehicle.refresh_from_db()
        self.assertFalse(self.vehicle.active)
        self.assertTrue(self.vehicle.history.filter(field="active").exists())

    def test_pending_exit_order_blocks_inactivation(self):
        driver = Driver.objects.create(name="Condutor")
        VehicleExitOrder.objects.create(number="OS-1", vehicle=self.vehicle, driver=driver, departed_at="2026-01-01T00:00Z", destination="x", reason="x", opened_by=self.user)
        with self.assertRaises(ValueError):
            set_vehicle_active(vehicle=self.vehicle, active=False, user=self.user)

    def test_open_maintenance_blocks_inactivation(self):
        Maintenance.objects.create(vehicle=self.vehicle, type=MaintenanceType.objects.create(name="x"), status=MaintenanceStatus.objects.create(name="Aberta"))
        with self.assertRaises(ValueError):
            set_vehicle_active(vehicle=self.vehicle, active=False, user=self.user)
