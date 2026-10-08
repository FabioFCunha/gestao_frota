from datetime import date, timedelta
from io import BytesIO
import tempfile
from unittest.mock import patch
from apps.fleet.crlv import extract_crlv_data

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient

from apps.fleet.models import (Document, LicensingCalendar, Sector, Vehicle, VehiclePlate,
                               VehicleStatus)
from apps.fleet.services import confirm_crlv, get_crlv_alerts, stage_crlv_document, stage_crlv_document_for_creation, create_vehicle_from_crlv


class CRLVTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_root.cleanup)
        self.user = get_user_model().objects.create_user(username='crlv', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='change_vehicle'))
        self.status = VehicleStatus.objects.create(name='Operacional')
        self.sector, _ = Sector.objects.get_or_create(name='ADM', slug='adm')
        self.user.sectors.add(self.sector)
        self.vehicle = Vehicle.objects.create(status=self.status, sector=self.sector)
        VehiclePlate.objects.create(vehicle=self.vehicle, plate='ABC1D23', kind='CURRENT')

    @patch('apps.fleet.crlv.extract_crlv_data', return_value={'plate': 'ABC1D23', 'renavam': '12345678901', 'exercise': 2026, 'text_extracted': True})
    def test_interface_upload_then_confirmation(self, _extract):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile('crlv.pdf', b'%PDF-1.4 placeholder', content_type='application/pdf')
        response = self.client.post(f'/veiculos/{self.vehicle.id}/crlv/', {'step': 'upload', 'file': upload})
        self.assertEqual(response.status_code, 200)
        document = Document.objects.get(document_type__name='CRLV')
        response = self.client.post(f'/veiculos/{self.vehicle.id}/crlv/', {'document_id': document.id, 'plate': 'ABC1D23', 'renavam': '12345678901', 'exercise': 2026})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f'/veiculos/{self.vehicle.id}/')
        self.assertTrue(self.vehicle.crlvs.exists())

    @patch('apps.fleet.crlv.extract_crlv_data', return_value={'plate': 'ABC1D23', 'renavam': '12345678901', 'exercise': 2026, 'text_extracted': True})
    def test_stage_and_confirm_updates_vehicle_and_history(self, _extract):
        upload = SimpleUploadedFile('crlv.pdf', b'%PDF-1.4 placeholder', content_type='application/pdf')
        document, extracted = stage_crlv_document(vehicle=self.vehicle, file_obj=upload, user=self.user)
        confirm_crlv(vehicle=self.vehicle, document=document, user=self.user, **{k: extracted[k] for k in ('plate', 'renavam', 'exercise')}, extracted_data=extracted)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.renavam, '12345678901')
        self.assertEqual(self.vehicle.crlv_exercise, 2026)
        self.assertTrue(document.relations.filter(object_id=self.vehicle.id).exists())
        self.assertEqual(self.vehicle.crlvs.count(), 1)

    def test_other_vehicle_plate_is_blocked(self):
        document = Document.objects.create(title='x', document_type_id=self._document_type(), status_id=self._document_status(), created_by=self.user)
        with self.assertRaisesMessage(ValueError, 'não pertence'):
            confirm_crlv(vehicle=self.vehicle, document=document, plate='ZZZ1Z99', renavam='', exercise=2026, user=self.user)

    def _document_type(self):
        from apps.fleet.models import DocumentType
        return DocumentType.objects.create(name='T').id

    def _document_status(self):
        from apps.fleet.models import DocumentStatus
        return DocumentStatus.objects.create(name='S').id

    def test_alerts_cover_missing_calendar_and_prior_year(self):
        today = date(2027, 1, 20)
        LicensingCalendar.objects.create(exercise=2026, plate_final=3, due_date=date(2026, 12, 20), created_by=self.user)
        alerts = get_crlv_alerts(Vehicle.objects.filter(pk=self.vehicle.pk), today=today)
        self.assertEqual(alerts['overdue'][0]['exercise'], 2026)
        self.assertEqual(alerts['calendar_missing'][0]['exercise'], 2027)

    @patch("apps.fleet.crlv._all_text")
    def test_extracts_crlv_digital_layout_maximum_data(self, all_text):
        all_text.return_value = """
        CÓDIGO RENAVAM PLACA EXERCÍCIO ANO FABRICAÇÃO ANO MODELO NÚMERO DO CRV
        01455165457 TTO8A04 2025 2025 2026 254508272509 90048500446 ***
        MARCA / MODELO / VERSÃO CHEV/ONIX 10TMT HB
        ESPÉCIE / TIPO PASSAGEIRO AUTOMOVEL
        PLACA ANTERIOR / UF *******/** CHASSI 9BGEA48H0TG145235
        COR PREDOMINANTE BRANCA COMBUSTÍVEL ALCOOL/GASOLINA
        CATEGORIA PARTICULAR CAPACIDADE *.* POTÊNCIA/CILINDRADA 115CV/1000
        PESO BRUTO TOTAL 1.4 MOTOR L4G252585140 CMT 1.4 EIXOS 2 LOTAÇÃO 05P
        CARROCERIA NÃO APLICAVEL
        NOME CS BRASIL FROTAS SA CPF / CNPJ 27.595.780/0025-93
        LOCAL DATA RIO DE JANEIRO RJ 20/10/2025
        OBSERVAÇÕES DO VEÍCULO BENEF. TRIBUTARIO 30/09/2026
        """
        upload = SimpleUploadedFile("crlv.pdf", b"%PDF", content_type="application/pdf")
        data = extract_crlv_data(upload)
        self.assertEqual(data["plate"], "TTO8A04")
        self.assertEqual(data["renavam"], "90048500446")
        self.assertEqual(data["chassi"], "9BGEA48H0TG145235")
        self.assertEqual(data["exercise"], 2025)
        self.assertEqual(data["color"], "BRANCA")
        self.assertEqual(data["fuel"], "ALCOOL/GASOLINA")
        self.assertEqual(data["owner_document"], "27.595.780/0025-93")
        self.assertTrue(data["raw_text"])

    def test_create_vehicle_from_crlv_preserves_document_history(self):
        document, extracted = stage_crlv_document_for_creation(
            file_obj=SimpleUploadedFile("crlv.pdf", b"%PDF placeholder", content_type="application/pdf"),
            user=self.user,
        )
        self.assertIsNotNone(document)
        vehicle, record = create_vehicle_from_crlv(
            document=document, plate="XYZ1A23", renavam="12345678901",
            chassi="9BWZZZ377VT004251", exercise=2026, brand="Chevrolet",
            model="Onix 1.0", color="BRANCO", sector=self.sector, status=self.status,
            user=self.user, extracted_data={"source": "CRLV", "reviewed": True},
        )
        self.assertEqual(vehicle.plate_history.get(kind="CURRENT").plate, "ABC1D23")
        self.assertEqual(vehicle.renavam, "12345678901")
        self.assertEqual(vehicle.chassi, "9BWZZZ377VT004251")
        self.assertEqual(record.exercise, 2026)
        self.assertTrue(document.relations.filter(object_id=vehicle.id).exists())
        self.assertEqual(vehicle.crlvs.count(), 1)
