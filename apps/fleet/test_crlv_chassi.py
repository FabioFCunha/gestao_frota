from django.test import TestCase
from apps.fleet.crlv import extract_chassi, extract_crlv_data
from apps.fleet.services import confirm_crlv
from apps.fleet.models import Vehicle, VehicleStatus, Sector, Document, DocumentType, DocumentStatus
from django.contrib.auth import get_user_model
from unittest.mock import patch

class CRLVChassiExtractionTests(TestCase):
    def test_a_context_explicit(self):
        text = "PLACA ABC1234\nCHASSI: 9BWZZZ377VT004251\nRENAVAM 123"
        self.assertEqual(extract_chassi(text), "9BWZZZ377VT004251")

    def test_b_spaces_and_separators(self):
        text = "Nº CHASSI: 9BW ZZZ 377 VT004251\n"
        self.assertEqual(extract_chassi(text), "9BWZZZ377VT004251")

    def test_c_absence_of_context(self):
        text = "ID DO DOCUMENTO: ABCD1234EFGH56781"
        self.assertEqual(extract_chassi(text), "")

    def test_d_vin_in_other_context(self):
        text = "HASH ASSINATURA: 12345678901234567\nPLACA: AAA0000"
        self.assertEqual(extract_chassi(text), "")

    def test_e_vin_explicit(self):
        text = "VIN: 9BWZZZ377VT004251"
        self.assertEqual(extract_chassi(text), "9BWZZZ377VT004251")
        
    def test_ocr_errors_fixed_in_context(self):
        text = "CHASSI: 9BWZZZ377VT0O425I"
        # The 'O' and 'I' should be replaced by '0' and '1'
        self.assertEqual(extract_chassi(text), "9BWZZZ377VT004251")

class CRLVChassiServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='crlv_chassi', password='x')
        self.status = VehicleStatus.objects.create(name='Operacional')
        self.sector, _ = Sector.objects.get_or_create(name='ADM', slug='adm')
        self.vehicle = Vehicle.objects.create(status=self.status, sector=self.sector)
        self.vehicle.plate_history.create(plate='ABC1D23', kind='CURRENT')
        
        dtype, _ = DocumentType.objects.get_or_create(name='CRLV')
        dstatus, _ = DocumentStatus.objects.get_or_create(name='Ativo')
        self.document = Document.objects.create(title='T', document_type=dtype, status=dstatus, created_by=self.user)

    def test_f_confirmation_saves_chassi(self):
        confirm_crlv(
            vehicle=self.vehicle,
            document=self.document,
            plate='ABC1D23',
            renavam='12345678901',
            chassi='9BWZZZ377VT004251',
            exercise=2026,
            user=self.user
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.chassi, '9BWZZZ377VT004251')
        self.assertEqual(self.vehicle.history.filter(field='crlv').first().new_value['chassi'], '9BWZZZ377VT004251')
        
    def test_f_confirmation_blocks_different_chassi(self):
        self.vehicle.chassi = '9BWZZZ377VT004251'
        self.vehicle.save()
        
        with self.assertRaisesMessage(ValueError, 'diferente cadastrado'):
            confirm_crlv(
                vehicle=self.vehicle,
                document=self.document,
                plate='ABC1D23',
                renavam='12345678901',
                chassi='9BWZZZ377VT000000',
                exercise=2026,
                user=self.user
            )

    def test_f_confirmation_blocks_chassi_from_other_vehicle(self):
        other_vehicle = Vehicle.objects.create(status=self.status, sector=self.sector, chassi='9BWZZZ377VT004251')
        with self.assertRaisesMessage(ValueError, 'pertence a outro ve'):
            confirm_crlv(
                vehicle=self.vehicle,
                document=self.document,
                plate='ABC1D23',
                renavam='12345678901',
                chassi='9BWZZZ377VT004251',
                exercise=2026,
                user=self.user
            )
