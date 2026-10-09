from datetime import date
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings

from apps.fleet.cnh import extract_cnh_data
from apps.fleet.models import AuditLog, Document, DocumentRelation, Driver, Sector


class CNHExtractionTests(SimpleTestCase):
    @patch("apps.fleet.cnh._all_text")
    def test_extracts_common_cnh_fields_from_pdf_text(self, all_text):
        all_text.return_value = """
        NOME E SOBRENOME
        MARIA DA SILVA
        DOC. IDENTIDADE / ORG. EMISSOR / UF
        123456789 DETRAN RJ
        CPF
        123.456.789-09
        DATA NASCIMENTO
        01/02/1985
        FILIAÇÃO
        JOSE DA SILVA
        ANA PEREIRA
        PERMISSÃO ACC CAT. HAB.
        AB
        Nº REGISTRO
        12345678901
        VALIDADE
        31/12/2030
        DATA 1ª HABILITAÇÃO
        12/03/2005
        DATA EMISSÃO
        05/06/2025
        NACIONALIDADE
        BRASILEIRA
        LOCAL
        RIO DE JANEIRO RJ
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertEqual(data["name"], "MARIA DA SILVA")
        self.assertEqual(data["cpf"], "123.456.789-09")
        self.assertEqual(data["birth_date"], "1985-02-01")
        self.assertEqual(data["cnh_number"], "12345678901")
        self.assertEqual(data["cnh_category"], "AB")
        self.assertEqual(data["cnh_expiration"], "2030-12-31")
        self.assertEqual(data["cnh_issue_date"], "2025-06-05")
        self.assertEqual(data["cnh_first_issue_date"], "2005-03-12")
        self.assertTrue(data["text_extraction_succeeded"])


    @patch("apps.fleet.cnh._all_text")
    def test_institutional_pdf_text_does_not_count_as_successful_cnh_extraction(self, all_text):
        all_text.return_value = """
        QR-CODE
        Documento assinado com certificado digital em conformidade
        com a Medida Provisória nº 2200-2/2001.
        REPÚBLICA FEDERATIVA DO BRASIL
        MINISTÉRIO DOS TRANSPORTES
        SECRETARIA NACIONAL DE TRÂNSITO - SENATRAN
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertFalse(data["text_extraction_succeeded"])
        self.assertEqual(data["name"], "")
        self.assertEqual(data["cpf"], "")

class CNHDriverFlowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_root.cleanup)

        self.user = get_user_model().objects.create_user(username="cnh-test", password="x")
        self.user.user_permissions.add(Permission.objects.get(codename="add_driver"))
        self.sector, _ = Sector.objects.get_or_create(
            slug="adm",
            defaults={"name": "ADM"},
        )
        self.user.sectors.add(self.sector)

    @patch(
        "apps.fleet.cnh.extract_cnh_data",
        return_value={
            "name": "MARIA DA SILVA",
            "cpf": "123.456.789-09",
            "birth_date": "1985-02-01",
            "cnh_number": "12345678901",
            "cnh_category": "AB",
            "cnh_expiration": "2030-12-31",
            "cnh_issue_date": "2025-06-05",
            "cnh_first_issue_date": "2005-03-12",
            "text_extracted": "texto de teste",
            "text_extraction_succeeded": True,
        },
    )
    def test_upload_review_and_confirm_creates_driver_and_links_pdf(self, _extract):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 placeholder", content_type="application/pdf")
        response = self.client.post(
            "/motoristas/novo/?sector=adm",
            {"step": "upload", "file": upload, "sector": "adm"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["confirm_form"])
        self.assertNotIn("sectors", response.context["confirm_form"].fields)
        self.assertNotIn("registration", response.context["confirm_form"].fields)
        self.assertNotIn("unit", response.context["confirm_form"].fields)
        self.assertNotIn("phone", response.context["confirm_form"].fields)
        self.assertNotIn("email", response.context["confirm_form"].fields)
        self.assertNotIn("renewal_date", response.context["confirm_form"].fields)
        document = Document.objects.get(document_type__name="CNH")
        self.assertFalse(DocumentRelation.objects.filter(document=document).exists())

        response = self.client.post(
            "/motoristas/novo/?sector=adm",
            {
                "step": "confirm",
                "document_id": str(document.id),
                "name": "MARIA DA SILVA",
                "cpf": "123.456.789-09",
                "birth_date": "1985-02-01",
                "cnh_number": "12345678901",
                "cnh_category": "AB",
                "cnh_expiration": "2030-12-31",
                "cnh_issue_date": "2025-06-05",
                "cnh_first_issue_date": "2005-03-12",
                "identity_document": "123456789",
                "issuing_authority": "DETRAN",
                "issuing_state": "RJ",
                "nationality": "BRASILEIRA",
                "father_name": "JOSE DA SILVA",
                "mother_name": "ANA PEREIRA",
                "location": "RIO DE JANEIRO RJ",
            },
        )
        self.assertEqual(response.status_code, 302)
        driver = Driver.objects.get(name="MARIA DA SILVA")
        self.assertEqual(driver.cpf, "123.456.789-09")
        self.assertEqual(driver.birth_date, date(1985, 2, 1))
        self.assertEqual(driver.cnh_number, "12345678901")
        self.assertEqual(driver.cnh_category, "AB")
        self.assertEqual(driver.cnh_expiration, date(2030, 12, 31))
        self.assertTrue(DocumentRelation.objects.filter(document=document, object_id=driver.id).exists())
        audit = AuditLog.objects.get(action="CNH CADASTRADA A PARTIR DE PDF", entity_id=document.id)
        self.assertTrue(audit.new_values["reviewed"])
        self.assertEqual(audit.new_values["form_values"]["cnh_first_issue_date"], "2005-03-12")

    def test_manual_registration_remains_available(self):
        self.client.force_login(self.user)
        response = self.client.get("/motoristas/novo/?manual=1&sector=adm")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadastrar Motorista manualmente")

    def test_manual_registration_saves_driver_and_sector(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/motoristas/novo/?manual=1&sector=adm",
            {
                "name": "MOTORISTA MANUAL TESTE",
                "registration": "MAT-CNH-MANUAL-001",
                "phone": "",
                "email": "",
                "cpf": "",
                "birth_date": "",
                "cnh_number": "",
                "cnh_category": "",
                "cnh_expiration": "",
                "renewal_date": "",
                "active": "True",
                "sectors": [str(self.sector.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        driver = Driver.objects.get(name="MOTORISTA MANUAL TESTE")
        self.assertEqual(driver.registration, "MAT-CNH-MANUAL-001")
        self.assertTrue(driver.sectors.filter(pk=self.sector.pk).exists())

