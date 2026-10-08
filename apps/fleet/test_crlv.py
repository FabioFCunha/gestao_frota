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
        CÓDIGO INTERNO LE1A00RC0DEEBA1XE
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
        self.assertEqual(data["manufacture_year"], 2025)
        self.assertEqual(data["model_year"], 2026)
        self.assertEqual(data["brand_raw"], "CHEV")
        self.assertEqual(data["model_raw"], "ONIX")
        self.assertEqual(data["version"], "10TMT HB")
        self.assertEqual(data["color"], "BRANCA")
        self.assertEqual(data["fuel"], "ALCOOL/GASOLINA")
        self.assertEqual(data["category"], "PARTICULAR")
        self.assertEqual(data["vehicle_type"], "PASSAGEIRO AUTOMOVEL")
        self.assertEqual(data["crv_number"], "254508272509")
        self.assertEqual(data["motor"], "L4G252585140")
        self.assertEqual(data["power_cylinder"], "115CV/1000")
        self.assertEqual(data["gross_weight"], "1.4")
        self.assertEqual(data["cmt"], "1.4")
        self.assertEqual(data["axles"], "2")
        self.assertEqual(data["axles"], "2")
        self.assertEqual(data["seating"], "05P")
        self.assertEqual(data["bodywork"], "NÃO APLICAVEL")
        self.assertEqual(data["owner_name"], "CS BRASIL FROTAS SA")
        self.assertEqual(data["owner_document"], "27.595.780/0025-93")
        self.assertEqual(data["location"], "RIO DE JANEIRO RJ")
        self.assertEqual(data["issue_date"], "20/10/2025")
        self.assertTrue(data["raw_text"])

    @patch("apps.fleet.crlv.extract_crlv_data")
    def test_vehicle_create_crlv_form_is_prefilled_with_extracted_data(self, extract):
        extract.return_value = {
            "plate": "TTO8A04",
            "renavam": "90048500446",
            "chassi": "9BGEA48H0TG145235",
            "exercise": 2025,
            "brand_raw": "CHEV",
            "model_raw": "ONIX",
            "version": "10TMT HB",
            "color": "BRANCA",
            "text_extracted": True,
            "raw_text": "CRLV",
        }
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "crlv.pdf", b"%PDF-1.4 CRLV TEST DATA", content_type="application/pdf"
        )
        response = self.client.post(
            "/veiculos/novo/",
            {"step": "upload", "file": upload},
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('value="TTO8A04"', html)
        self.assertIn('value="90048500446"', html)
        self.assertIn('value="9BGEA48H0TG145235"', html)
        self.assertIn('value="2025"', html)
        self.assertIn('value="CHEV"', html)
        self.assertIn('value="ONIX 10TMT HB"', html)
        self.assertIn('value="BRANCA"', html)

    @patch("apps.fleet.crlv.extract_crlv_data")
    def test_stage_crlv_rewinds_uploaded_file_after_document_save(self, extract):
        # O save do DocumentVersion pode consumir o stream. A extração deve
        # receber o arquivo reposicionado no início.
        extract.side_effect = lambda file_obj: {
            "bytes_read": len(file_obj.read()),
            "text_extracted": True,
        }
        upload = SimpleUploadedFile(
            "crlv.pdf", b"%PDF-1.4 CRLV TEST DATA", content_type="application/pdf"
        )
        document, extracted = stage_crlv_document_for_creation(
            file_obj=upload,
            user=self.user,
        )
        self.assertEqual(extracted["bytes_read"], len(b"%PDF-1.4 CRLV TEST DATA"))
        self.assertTrue(document.versions.exists())

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
        self.assertEqual(vehicle.plate_history.get(kind="CURRENT").plate, "XYZ1A23")
        self.assertEqual(vehicle.renavam, "12345678901")
        self.assertEqual(vehicle.chassi, "9BWZZZ377VT004251")
        self.assertEqual(record.exercise, 2026)
        self.assertTrue(document.relations.filter(object_id=vehicle.id).exists())
        self.assertEqual(vehicle.crlvs.count(), 1)
