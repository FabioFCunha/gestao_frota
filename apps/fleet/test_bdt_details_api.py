import uuid

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.fleet.models import BDT


class BDTDetailsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bdt-reader", password="safe-password")
        self.client.force_authenticate(self.user)

    def test_open_bdt_detail_preserves_zero_and_long_note(self):
        note = "Observação longa do motorista. " * 30
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=True,
            started_at=timezone.now(),
            started_km="0",
            latitude_match=0,
            longitude_match=0,
            note=note,
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["source_status"], "ABERTO")
        self.assertEqual(response.data["started_km"], "0")
        self.assertEqual(response.data["latitude_match"], "0.00000000")
        self.assertEqual(response.data["longitude_match"], "0.00000000")
        self.assertEqual(response.data["note"], note)
        self.assertIsNone(response.data["ended_at"])

    def test_closed_bdt_detail_reports_source_status(self):
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="0",
            ended_km="0",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["source_status"], "ENCERRADO")
        self.assertEqual(str(response.data["total_km"]), "0")
