import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.fleet.models import BDT, Vehicle, VehicleStatus
from apps.fleet.sync_bdt import BDTSyncWorker


class SyncContractTests(TestCase):
    def setUp(self):
        from django.conf import settings
        settings.FLEET_SYNC_TOKEN = "test-token"
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-token")
        self.active = VehicleStatus.objects.create(name="Ativo", active=True)

    def test_vehicle_omitted_fields_preserve_local_values(self):
        external_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(
            horus_fleet_id=external_id,
            status=self.active,
            color="Azul",
            notes="Cadastro local preservado",
        )

        response = self.client.post(
            "/api/sync/vehicles/",
            {"external_id": str(external_id), "plate": "ABC1234"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.color, "Azul")
        self.assertEqual(vehicle.status_id, self.active.id)
        self.assertEqual(vehicle.notes, "Cadastro local preservado")

    def test_explicit_unlinked_references_reject_entire_bdt_batch(self):
        row = {
            "id": str(uuid.uuid4()),
            "fleet_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "created_at": timezone.now(),
        }
        result = BDTSyncWorker([row]).run()

        self.assertEqual(result["processados"], 1)
        self.assertEqual(result["falhas"], 1)
        self.assertEqual(BDT.objects.count(), 0)

    def test_missing_source_references_are_allowed(self):
        row = {"id": str(uuid.uuid4()), "created_at": timezone.now()}
        result = BDTSyncWorker([row]).run()

        self.assertEqual(result["falhas"], 0)
        self.assertEqual(result["criados"], 1)
        self.assertEqual(BDT.objects.count(), 1)
