import uuid

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from .models import BDT, Driver, Vehicle, VehicleStatus


class VehicleBDTEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bdt-vehicle-reader", password="safe-password")
        self.client.force_authenticate(self.user)
        status = VehicleStatus.objects.create(name="Ativo")
        self.fleet_id = uuid.uuid4()
        self.vehicle = Vehicle.objects.create(horus_fleet_id=self.fleet_id, status=status)
        self.other = Vehicle.objects.create(horus_fleet_id=uuid.uuid4(), status=status)
        self.driver = Driver.objects.create(name="Motorista BDT")

    def test_returns_only_uuid_linked_bdts_with_summary_and_pagination(self):
        BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.vehicle, driver=self.driver,
                           started_at=timezone.now(), started_km="0", ended_km="100", horus_active=False)
        BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.vehicle,
                           started_at=timezone.now(), started_km="100", horus_active=True)
        BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.other,
                           started_at=timezone.now(), started_km="10", ended_km="20", horus_active=False)

        response = self.client.get(f"/api/vehicles/{self.vehicle.id}/bdts/?page_size=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["total"], 2)
        self.assertEqual(response.data["summary"]["open"], 1)
        self.assertEqual(response.data["summary"]["closed"], 1)
        self.assertEqual(response.data["summary"]["total_km"], "100")
        self.assertEqual(response.data["count"], 2)
        self.assertLessEqual(len(response.data["results"]), response.data["count"])
