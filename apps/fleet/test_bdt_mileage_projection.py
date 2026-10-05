import uuid

from django.test import TestCase
from django.utils import timezone

from .models import BDT, Vehicle, VehicleMileage, VehicleStatus
from .sync_bdt import sync_bdt_mileage


class BDTMileageProjectionTests(TestCase):
    def setUp(self):
        status = VehicleStatus.objects.create(name="Ativo")
        self.vehicle = Vehicle.objects.create(horus_fleet_id=uuid.uuid4(), status=status)

    def make_bdt(self, started="0", ended="100", **kwargs):
        return BDT.objects.create(
            external_id=uuid.uuid4(), vehicle=self.vehicle,
            started_at=timezone.now(), ended_at=timezone.now(),
            started_km=started, ended_km=ended, **kwargs
        )

    def test_valid_zero_and_idempotent_update(self):
        bdt = self.make_bdt(started="0", ended="100")
        self.assertTrue(sync_bdt_mileage(bdt))
        self.assertTrue(sync_bdt_mileage(bdt))
        self.assertEqual(VehicleMileage.objects.filter(origin="INTEGRACAO", external_id=str(bdt.external_id)).count(), 1)
        self.assertEqual(VehicleMileage.objects.get(external_id=str(bdt.external_id)).mileage, 100)

    def test_open_or_inconsistent_bdt_does_not_project(self):
        self.assertFalse(sync_bdt_mileage(self.make_bdt(started="0", ended=None)))
        self.assertFalse(sync_bdt_mileage(self.make_bdt(started="100", ended="50")))
        self.assertEqual(VehicleMileage.objects.filter(origin="INTEGRACAO").count(), 0)

    def test_manual_mileage_is_preserved(self):
        manual = VehicleMileage.objects.create(vehicle=self.vehicle, mileage=999, origin="MANUAL")
        bdt = self.make_bdt(started="0", ended="100")
        sync_bdt_mileage(bdt)
        manual.refresh_from_db()
        self.assertEqual(manual.mileage, 999)
        self.assertFalse(BDT.objects.filter(vehicle=self.vehicle, ended_at__isnull=False).count() == 0)

