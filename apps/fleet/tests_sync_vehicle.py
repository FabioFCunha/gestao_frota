import uuid
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from apps.fleet.models import Vehicle, VehiclePlate, VehicleStatus

class VehicleSyncReconciliationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.sync_url = reverse("sync-vehicles")

        # Token authorization if needed
        self.token = "fake-token"
        from django.conf import settings
        settings.FLEET_SYNC_TOKEN = self.token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        self.status_ativo = VehicleStatus.objects.create(name="Ativo", active=True)

    def test_found_by_horus_fleet_id(self):
        fleet_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(
            horus_fleet_id=fleet_id,
            status=self.status_ativo,
            color="Branco"
        )

        data = {
            "external_id": str(fleet_id),
            "plate": "ABC1234",
            "color": "Preto",
            "management_name": "Test Mgmt"
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.color, "Preto")
        self.assertIn("Test Mgmt", vehicle.notes)
        self.assertTrue(vehicle.plate_history.filter(plate="ABC1234").exists())

    def test_found_by_plate_without_horus_fleet_id(self):
        fleet_id = uuid.uuid4()

        # Veiculo existente SEM horus_fleet_id, com placa RTH7D34
        vehicle = Vehicle.objects.create(
            status=self.status_ativo,
            color="Branco",
            horus_fleet_id=None
        )
        VehiclePlate.objects.create(
            vehicle=vehicle,
            plate="RTH7D34",
            kind=VehiclePlate.CURRENT,
            starts_on=timezone.now()
        )

        data = {
            "external_id": str(fleet_id),
            "plate": "rth7d34", # lowercase to test iexact
            "color": "Prata",
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["result"], "updated")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.horus_fleet_id, fleet_id)
        self.assertEqual(vehicle.color, "Prata")

        # Nao deve ter criado outra placa CURRENT
        self.assertEqual(vehicle.plate_history.count(), 1)

    def test_found_by_plate_with_same_horus_fleet_id(self):
        fleet_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(
            horus_fleet_id=fleet_id,
            status=self.status_ativo,
            color="Branco"
        )
        VehiclePlate.objects.create(
            vehicle=vehicle,
            plate="RTH7D34",
            kind=VehiclePlate.CURRENT,
            starts_on=timezone.now()
        )

        data = {
            "external_id": str(fleet_id),
            "plate": "RTH7D34",
            "color": "Preto",
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.color, "Preto")

    def test_conflict_plate_with_another_horus_fleet_id(self):
        fleet_id_1 = uuid.uuid4()
        fleet_id_2 = uuid.uuid4()

        # Vehicle 1 tem RTH7D34
        vehicle1 = Vehicle.objects.create(
            horus_fleet_id=fleet_id_1,
            status=self.status_ativo
        )
        VehiclePlate.objects.create(
            vehicle=vehicle1,
            plate="RTH7D34",
            kind=VehiclePlate.CURRENT,
            starts_on=timezone.now()
        )

        # Tentamos sincronizar fleet_id_2 com RTH7D34
        data = {
            "external_id": str(fleet_id_2),
            "plate": "RTH7D34",
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["result"], "error")
        self.assertEqual(response.data["conflicting_horus_fleet_id"], str(fleet_id_1))

    def test_creation_of_new_vehicle(self):
        fleet_id = uuid.uuid4()

        data = {
            "external_id": str(fleet_id),
            "plate": "NEW0001",
            "color": "Verde",
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["result"], "created")

        vehicle = Vehicle.objects.get(horus_fleet_id=fleet_id)
        self.assertEqual(vehicle.color, "Verde")
        self.assertTrue(vehicle.plate_history.filter(plate="NEW0001").exists())

    def test_legitimate_plate_change(self):
        fleet_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(
            horus_fleet_id=fleet_id,
            status=self.status_ativo
        )
        old_plate = VehiclePlate.objects.create(
            vehicle=vehicle,
            plate="OLD0000",
            kind=VehiclePlate.CURRENT,
            starts_on=timezone.now()
        )

        data = {
            "external_id": str(fleet_id),
            "plate": "NEW0000",
        }

        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        old_plate.refresh_from_db()
        self.assertIsNotNone(old_plate.ends_on)

        current_plate = vehicle.plate_history.get(ends_on__isnull=True)
        self.assertEqual(current_plate.plate, "NEW0000")

    def test_no_duplicate_vehicle_plate(self):
        fleet_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(
            horus_fleet_id=fleet_id,
            status=self.status_ativo
        )
        # Sincroniza a primeira vez
        data = {
            "external_id": str(fleet_id),
            "plate": "DUP0000",
        }
        self.client.post(self.sync_url, data, format="json")

        # Sincroniza de novo
        response = self.client.post(self.sync_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Deve haver apenas UMA placa DUP0000 associada
        self.assertEqual(vehicle.plate_history.count(), 1)
