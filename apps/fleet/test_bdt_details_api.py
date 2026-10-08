import uuid

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.fleet.models import BDT


class BDTDetailsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="bdt-reader", email="bdt-reader@example.com", password="safe-password")
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


class BDTKmDisplayTests(APITestCase):
    """
    Testa que os campos de quilometragem exibidos na API estão
    consistentes entre si: started_km_display, ended_km_display e total_km
    devem todos usar valores normalizados.

    Reproduz o bug real onde started_km="9.850" (separador de milhar)
    era exibido como "9.850 km" mas total_km era calculado corretamente
    como 30 km (9880 - 9850), causando divergência visual.
    """

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="km-tester", password="safe-password"
        )
        self.client.force_authenticate(self.user)

    def test_thousands_separator_dot_normalized_for_display(self):
        """
        BDT real do Hórus: started_km="9.850" (separador de milhar),
        ended_km="9880". O ponto em "9.850" é um separador de milhar
        (grupo de 3 dígitos), não decimal.

        Antes da correção:
          - started_km exibido: "9.850 km" (parecia 9,85 km)
          - ended_km exibido:   "9880 km"
          - total_km exibido:   "30 km"
          → Divergência: 9880 - 9.850 ≠ 30

        Após a correção:
          - started_km_display: "9850"
          - ended_km_display:   "9880"
          - total_km:           "30"
          → Consistente: 9880 - 9850 = 30
        """
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="9.850",
            ended_km="9880",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)

        # Campo bruto preservado para auditoria
        self.assertEqual(response.data["started_km"], "9.850")
        self.assertEqual(response.data["ended_km"], "9880")

        # Campos normalizados para exibição
        self.assertEqual(response.data["started_km_display"], "9850")
        self.assertEqual(response.data["ended_km_display"], "9880")

        # Total calculado consistentemente
        self.assertEqual(response.data["total_km"], "30")

    def test_decimal_km_preserved_correctly(self):
        """
        BDT real do Hórus: started_km="870.0", ended_km="935.3".
        Estes são valores decimais legítimos (1 casa decimal).
        """
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="870.0",
            ended_km="935.3",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["started_km_display"], "870.0")
        self.assertEqual(response.data["ended_km_display"], "935.3")
        self.assertEqual(response.data["total_km"], "65.3")

    def test_two_decimal_places_preserved(self):
        """
        BDT real do Hórus: started_km="650.00", ended_km="706.00".
        Duas casas decimais devem ser preservadas.
        """
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="650.00",
            ended_km="706.00",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["started_km_display"], "650.00")
        self.assertEqual(response.data["ended_km_display"], "706.00")
        self.assertEqual(response.data["total_km"], "56.00")

    def test_zero_km_total_preserved(self):
        """Quando saída e retorno são iguais, total = 0."""
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="5000",
            ended_km="5000",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_km"], "0")

    def test_missing_ended_km_shows_null(self):
        """Quando ended_km está vazio, total e display devem ser null."""
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=True,
            started_at=timezone.now(),
            started_km="5000",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["started_km_display"], "5000")
        self.assertIsNone(response.data["ended_km_display"])
        self.assertIsNone(response.data["total_km"])

    def test_both_km_empty_shows_null(self):
        """Quando ambos os campos estão vazios."""
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=True,
            started_at=timezone.now(),
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["started_km_display"])
        self.assertIsNone(response.data["ended_km_display"])
        self.assertIsNone(response.data["total_km"])

    def test_large_thousands_separator_dot_normalized(self):
        """
        BDT real do Hórus: started_km="54.460", ended_km="54486".
        O ponto em "54.460" é um separador de milhar.
        """
        bdt = BDT.objects.create(
            external_id=uuid.uuid4(),
            horus_active=False,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            started_km="54.460",
            ended_km="54486",
        )

        response = self.client.get(f"/api/bdts/{bdt.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["started_km_display"], "54460")
        self.assertEqual(response.data["ended_km_display"], "54486")
        self.assertEqual(response.data["total_km"], "26")
