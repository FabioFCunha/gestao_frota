import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import AuditLog, Driver, Sector, Vehicle, VehicleStatus
from .services import end_vehicle_custody, start_vehicle_custody, transfer_vehicle_custody


@unittest.skipUnless(connection.vendor == "postgresql", "requer PostgreSQL isolado")
class VehicleCustodyWorkflowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="custody")
        self.status = VehicleStatus.objects.get(name="Ativo")
        self.sector = Sector.objects.get(slug="adm")
        self.vehicle = Vehicle.objects.create(status=self.status, sector=self.sector)
        self.first = Driver.objects.create(name="Primeiro")
        self.second = Driver.objects.create(name="Segundo")

    def test_start_transfer_end_preserves_initial_assignment_and_history(self):
        custody = start_vehicle_custody(vehicle=self.vehicle, driver=self.first, sei_number="SEI-1",
            started_on=timezone.localdate(), user=self.user)
        initial_id = custody.assignment_id
        transferred = transfer_vehicle_custody(custody=custody, new_driver=self.second, user=self.user,
            transferred_at=timezone.now())
        self.assertEqual(custody.assignment_id, initial_id)
        self.assertEqual(transferred.custody_id, custody.id)
        self.assertEqual(self.vehicle.custodies.get(ended_on__isnull=True).id, custody.id)
        end_vehicle_custody(custody=custody, user=self.user, ended_on=timezone.localdate(),
            assignment_ended_at=timezone.now())
        custody.refresh_from_db()
        transferred.refresh_from_db()
        self.assertIsNotNone(custody.ended_on)
        self.assertFalse(transferred.is_active)
        self.assertEqual(AuditLog.objects.filter(entity_id=custody.id).count(), 3)

    def test_transfer_rollback_keeps_responsible_active(self):
        custody = start_vehicle_custody(vehicle=self.vehicle, driver=self.first, sei_number="SEI-1",
            started_on=timezone.localdate(), user=self.user)
        with self.assertRaises(ValueError):
            transfer_vehicle_custody(custody=custody, new_driver=self.second, user=self.user,
                transferred_at=timezone.now() + timedelta(days=1))
        self.assertTrue(custody.assignments.get(driver=self.first).is_active)

    def test_api_requires_permission_and_sector(self):
        client = APIClient()
        outsider = get_user_model().objects.create_user(username="outside")
        client.force_authenticate(outsider)
        payload = {"vehicle": str(self.vehicle.id), "responsible": str(self.first.id),
                   "sei_number": "SEI-API", "started_on": timezone.localdate().isoformat()}
        self.assertEqual(client.post("/api/vehicle-custodies/", payload).status_code, 403)
        outsider.user_permissions.add(Permission.objects.get(codename="add_vehiclecustody"))
        self.assertEqual(client.post("/api/vehicle-custodies/", payload).status_code, 403)
