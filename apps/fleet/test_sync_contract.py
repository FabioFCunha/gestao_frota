import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.fleet.models import BDT, Vehicle, VehicleMileage, VehicleStatus
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

    def test_worker_path_projects_bdt_mileage_idempotently(self):
        fleet_id = uuid.uuid4()
        vehicle = Vehicle.objects.create(horus_fleet_id=fleet_id, status=self.active)
        external_id = uuid.uuid4()
        row = {
            "id": str(external_id), "fleet_id": str(fleet_id),
            "started_at": timezone.now(), "ended_at": timezone.now(),
            "started_km": "0", "ended_km": "125",
            "active": False, "created_at": timezone.now(),
        }
        first = BDTSyncWorker([row]).run()
        second = BDTSyncWorker([row]).run()
        self.assertEqual(first["criados"], 1)
        self.assertEqual(second["atualizados"], 1)
        projection = VehicleMileage.objects.get(
            origin=VehicleMileage.INTEGRACAO, external_id=str(external_id)
        )
        self.assertEqual(projection.vehicle_id, vehicle.id)
        self.assertEqual(projection.mileage, 125)
        self.assertEqual(VehicleMileage.objects.filter(external_id=str(external_id)).count(), 1)

    def test_bdt_api_vehicle_filter_does_not_leak_other_vehicle(self):
        vehicle_1 = Vehicle.objects.create(horus_fleet_id=uuid.uuid4(), status=self.active)
        vehicle_2 = Vehicle.objects.create(horus_fleet_id=uuid.uuid4(), status=self.active)
        bdt_1 = BDT.objects.create(external_id=uuid.uuid4(), vehicle=vehicle_1)
        BDT.objects.create(external_id=uuid.uuid4(), vehicle=vehicle_2)
        response = self.client.get(f"/api/bdts/?vehicle={vehicle_1.id}")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(str(bdt_1.id), ids)
        self.assertEqual(response.data["count"], 1)

    def test_bdt_api_invalid_vehicle_filter_is_empty(self):
        response = self.client.get("/api/bdts/?vehicle=not-a-uuid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
