from datetime import date
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings

from apps.fleet.cnh import extract_cnh_data
from apps.fleet.models import AuditLog, Document, DocumentRelation, Driver, Sector
from apps.ui.forms import CNHDriverCreateForm


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
    def test_extracts_supplemental_fields_when_ocr_values_share_label_lines(self, all_text):
        all_text.return_value = """
        NOME E SOBRENOME ALBERTO FELIPE PEREIRA LOPA
        CPF 113.483.417-93
        DOC. IDENTIDADE / ORG. EMISSOR / UF
        021012056533 COMAER RJ
        DATA NASCIMENTO 22/01/1987
        DATA EMISSAO VALIDADE ACC
        16/04/2024 14/04/2034
        1a HABILITACAO 29/09/2006
        NACIONALIDADE BRASILEIRO(A)
        FILIACAO JOSE ALBERTO DE ALMEIDA LOPA
        MARIA CRISTINA PEREIRA
        LOCAL RIO DE JANEIRO RJ
        I<BRA039447298<457<<<<<<<<<<<<
        8701222M3404148BRA<<<<<<<<<<<8
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertEqual(data["identity_document"], "021012056533")
        self.assertEqual(data["issuing_authority"], "COMAER")
        self.assertEqual(data["issuing_state"], "RJ")
        self.assertEqual(data["nationality"], "BRASILEIRO(A)")
        self.assertEqual(data["father_name"], "JOSE ALBERTO DE ALMEIDA LOPA")
        self.assertEqual(data["mother_name"], "MARIA CRISTINA PEREIRA")
        self.assertEqual(data["location"], "RIO DE JANEIRO RJ")
        self.assertEqual(data["cnh_issue_date"], "2024-04-16")
        self.assertEqual(data["cnh_first_issue_date"], "2006-09-29")
        self.assertEqual(data["birth_date_display"], "22/01/1987")
        self.assertEqual(data["cnh_expiration_display"], "14/04/2034")

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

    @patch("apps.fleet.cnh._all_text")
    def test_name_parser_does_not_match_inside_sobrenome(self, all_text):
        all_text.return_value = """
        SOBRENOME PEREIRA
        DATA NASCIMENTO
        01/02/1985
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertEqual(data["name"], "")

    @patch("apps.fleet.cnh._all_text")
    def test_name_parser_stops_at_date_and_following_labels(self, all_text):
        all_text.return_value = """
        NOME E SOBRENOME ALBERTO FELIPE PEREIRA LOPA 29/09/2006 DATA LOCAL
        CPF
        123.456.789-09
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertEqual(data["name"], "ALBERTO FELIPE PEREIRA LOPA")


    @patch("apps.fleet.cnh._all_text")
    def test_extracts_columnar_ocr_fields_and_mrz_dates(self, all_text):
        all_text.return_value = """
        REPUBLICA FEDERATIVA DO BRASIL
        NOME E SOBRENOME 1º HABILITAÇÃO
        ALBERTO FELIPE PEREIRA LOPA 29/09/2006
        DATA, LOCAL E UF DE NASCIMENTO
        22/01/1987, RIO DE JANEIRO, RJ
        DATA EMISSAO VALIDADE ACC
        16/04/2024 14/04/2034
        DOC IDENTIDADE / ORG EMISSOR UF
        021012056533 COMAER RJ
        CPF 5 Nº REGISTRO 9 CAT HAB
        123.456.789-09 03044729845
        NACIONALIDADE
        BRASILEIRO(A)
        FILIAÇÃO
        JOSE ALBERTO DE ALMEIDA LOPA
        MARIA CRISTINA PEREIRA
        LOCAL
        RIO DE JANEIRO RJ
        I<BRA039447298<457<<<<<<<<<<<<
        8701222M3404148BRA<<<<<<<<<<<8
        ALBERTO<<FELIPE<PEREIRA<LOPA<<
        """
        upload = SimpleUploadedFile("cnh.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = extract_cnh_data(upload)
        self.assertEqual(data["name"], "ALBERTO FELIPE PEREIRA LOPA")
        self.assertEqual(data["cpf"], "123.456.789-09")
        self.assertEqual(data["cnh_number"], "03044729845")
        self.assertEqual(data["birth_date"], "1987-01-22")
        self.assertEqual(data["cnh_issue_date"], "2024-04-16")
        self.assertEqual(data["cnh_expiration"], "2034-04-14")
        self.assertEqual(data["cnh_first_issue_date"], "2006-09-29")
        self.assertEqual(data["identity_document"], "021012056533")
        self.assertEqual(data["issuing_authority"], "COMAER")
        self.assertEqual(data["issuing_state"], "RJ")
        self.assertEqual(data["nationality"], "BRASILEIRO(A)")
        self.assertEqual(data["father_name"], "JOSE ALBERTO DE ALMEIDA LOPA")
        self.assertEqual(data["mother_name"], "MARIA CRISTINA PEREIRA")
        self.assertEqual(data["location"], "RIO DE JANEIRO RJ")


class CNHExtractionRegressionTests(SimpleTestCase):
    noisy_text = """
NOME E SOBRENOME 1º HABILITAÇÃO
ALBERTO FELIPE PEREIRA LOPA 29/09/2006 + i" oO h poa
DATA, LOCAL E UF DE NASCIMENTO
22/01/1987, RIO DE JANEIRO, RJ
DATA EMISSÃO VALIDADE ACC
16/04/2024 14/04/2034 ==|D
E AE DOCIDENTIDADE / ORG EMISSOR UF
= 021012056533 COMAER RJ "i oO E a oO T E Ea, o — =
a nm =
E ad CPF 5 Nº REGISTRO 9 CATHAB Fr —
2 O 113.483.417-93 03044729845 || D = eons, Tl ee FILE m1
& a NACIONALIDADE nan ul Ba = | na
E a BRASILEIRO(A) po + no mp
e - Fiação T Fr Em e jm la
s bi JOSE ALBERTO DE ALMEIDA LOPA Co Eça ns a = ei rs I
E 4 Alb Edy P lda MARIA CRISTINA PEREIRA a 1 ao al Du Fr |
= 7 ASSINATURA DO PORTADOR
Filiação / Filiation / Filiación - 12. Observações / Observations
I<BRA039447298<457<<<<<<<<<<<<
8701222M3404148BRA<<<<<<<<<<<8
"""
    field_text = """
4c DOC IDENTIDADE / ORG EMISSOR / UF
021012056533 COMAER RJ |
4d CPF 5 Nº REGISTRO 9 CAT HAB
113.483.417-93 | | 03944729845 | D |
NACIONALIDADE
BRASILEIRO(A) |
FILIAÇÃO
JOSE ALBERTO DE ALMEIDA LOPA
MARIA CRISTINA PEREIRA
"""

    @patch("apps.fleet.cnh._cnh_field_text")
    @patch("apps.fleet.cnh._all_text")
    def test_real_ocr_noise_recovers_fields_without_replacing_original_identifiers(self, all_text, field_text):
        all_text.return_value = self.noisy_text
        field_text.return_value = self.field_text
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["issuing_authority"], "COMAER")
        self.assertEqual(data["issuing_state"], "RJ")
        self.assertEqual(data["cnh_category"], "D")
        self.assertEqual(data["father_name"], "JOSE ALBERTO DE ALMEIDA LOPA")
        self.assertEqual(data["mother_name"], "MARIA CRISTINA PEREIRA")
        self.assertEqual(data["nationality"], "BRASILEIRO(A)")
        self.assertEqual(data["name"], "ALBERTO FELIPE PEREIRA LOPA")
        self.assertEqual(data["cpf"], "113.483.417-93")
        self.assertEqual(data["identity_document"], "021012056533")
        self.assertEqual(data["cnh_number"], "03044729845")
        self.assertEqual(data["birth_date"], "1987-01-22")
        self.assertEqual(data["cnh_issue_date"], "2024-04-16")
        self.assertEqual(data["cnh_expiration"], "2034-04-14")
        self.assertEqual(data["cnh_first_issue_date"], "2006-09-29")
        self.assertEqual(data["text_extracted"], self.noisy_text)

    @patch("apps.fleet.cnh._cnh_field_text", return_value="")
    @patch("apps.fleet.cnh._all_text")
    def test_missing_supplemental_ocr_preserves_original_extraction(self, all_text, field_text):
        all_text.return_value = self.noisy_text
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["issuing_authority"], "COMAER")
        self.assertEqual(data["issuing_state"], "RJ")
        self.assertEqual(data["cnh_category"], "D")
        self.assertEqual(data["father_name"], "")
        self.assertEqual(data["mother_name"], "")
        self.assertEqual(data["cpf"], "113.483.417-93")
        self.assertEqual(data["cnh_number"], "03044729845")

    @patch("apps.fleet.cnh._cnh_field_text")
    @patch("apps.fleet.cnh._all_text")
    def test_supplemental_ocr_recovers_noisy_nationality(self, all_text, field_text):
        all_text.return_value = self.noisy_text.replace("BRASILEIRO(A)", "BRAS1LEIR0(A)")
        field_text.return_value = self.field_text
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["nationality"], "BRASILEIRO(A)")

    @patch("apps.fleet.cnh._cnh_field_text")
    @patch("apps.fleet.cnh._all_text")
    def test_parent_names_are_complete_and_single_name_is_not_assigned(self, all_text, field_text):
        all_text.return_value = self.noisy_text
        father = "JOSE ALBERTO DE ALMEIDA LOPA DA SILVA DE OLIVEIRA"
        field_text.return_value = self.field_text.replace("JOSE ALBERTO DE ALMEIDA LOPA", father)
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["father_name"], father)
        self.assertEqual(data["mother_name"], "MARIA CRISTINA PEREIRA")
        field_text.return_value = "FILIAÇÃO\nMARIA CRISTINA PEREIRA\n"
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["father_name"], "")
        self.assertEqual(data["mother_name"], "")

    @patch("apps.fleet.cnh._cnh_field_text", return_value="")
    @patch("apps.fleet.cnh._all_text")
    def test_category_window_does_not_consume_following_personal_fields(self, all_text, field_text):
        all_text.return_value = "CAT HAB\nNACIONALIDADE\nBRASILEIRO(A)\nFILIAÇÃO\nA DE ALMEIDA\nMARIA PEREIRA\n"
        data = extract_cnh_data(b"%PDF-1.4 test")
        self.assertEqual(data["cnh_category"], "")


    def test_complementary_ocr_uses_margin_and_skips_square_qr_image(self):
        import sys
        import types
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_field_text

        qr = MagicMock()
        qr.image.convert.return_value.width = 591
        qr.image.convert.return_value.height = 591
        embedded = MagicMock()
        image = embedded.image.convert.return_value
        image.width, image.height = 963, 680
        enlarged = image.resize.return_value
        enlarged.width, enlarged.height = 1926, 1360
        page = MagicMock()
        page.images = [qr, embedded]
        reader = MagicMock()
        reader.pages = [page]
        pdf_module = types.ModuleType("pypdf")
        pdf_module.PdfReader = MagicMock(return_value=reader)
        with patch.dict(sys.modules, {"pypdf": pdf_module}):
            with patch(
                "apps.fleet.cnh._cnh_ocr",
                side_effect=[
                    {"text": ["DOC"], "left": [944], "top": [690]},
                    self.field_text,
                ],
            ) as ocr:
                self.assertEqual(_cnh_field_text(b"pdf"), self.field_text)
        qr.image.convert.return_value.resize.assert_not_called()
        enlarged.crop.assert_called_once_with((877, 682, 1926, 1360))
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(ocr.call_args_list[0].kwargs, {"data": True})

    def test_complementary_ocr_failure_returns_empty_text(self):
        import sys
        import types
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_field_text

        pdf_module = types.ModuleType("pypdf")
        pdf_module.PdfReader = MagicMock(side_effect=RuntimeError("PDF indisponível"))
        ocr_module = types.ModuleType("pytesseract")
        with patch.dict(sys.modules, {"pypdf": pdf_module, "pytesseract": ocr_module}):
            self.assertEqual(_cnh_field_text(b"pdf"), "")


class CNHOCRPerformanceTests(SimpleTestCase):
    def _ocr_environment(self):
        import types
        from unittest.mock import MagicMock

        module = types.ModuleType("pytesseract")
        module.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract")
        result = MagicMock()
        result.stdout = b"FILIA\xc3\x87\xc3\x83O\nJOSE ALBERTO DE ALMEIDA LOPA\nMARIA CRISTINA PEREIRA\n"
        return module, result

    def test_thread_limit_is_passed_only_to_cnh_subprocess(self):
        import os
        import sys
        from pathlib import Path
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_ocr

        module, result = self._ocr_environment()
        image = MagicMock()
        with patch.dict(os.environ, {"OMP_THREAD_LIMIT": "7", "CNH_TEST_ENV": "preserved"}):
            with patch.dict(sys.modules, {"pytesseract": module}):
                with patch("subprocess.run", return_value=result) as run:
                    text = _cnh_ocr(image)
                    call = run.call_args
                    self.assertEqual(call.kwargs["env"]["OMP_THREAD_LIMIT"], "1")
                    self.assertEqual(call.kwargs["env"]["CNH_TEST_ENV"], "preserved")
                    self.assertEqual(os.environ["OMP_THREAD_LIMIT"], "7")
                    self.assertEqual(call.args[0][0], "tesseract")
                    self.assertEqual(call.args[0][2:], ["stdout", "-l", "por+eng", "--psm", "6"])
                    self.assertEqual(call.kwargs["timeout"], 90)
                    self.assertTrue(call.kwargs["check"])
                    self.assertFalse(Path(call.args[0][1]).parent.exists())
        self.assertEqual(text, result.stdout.decode("utf-8"))
        image.save.assert_called_once()

    def test_tsv_coordinates_remain_available_for_dynamic_crop(self):
        import sys
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_ocr

        module, result = self._ocr_environment()
        result.stdout = b"level\tleft\ttop\ttext\n5\t944\t690\tDOC\n5\t998\t686\tIDENTIDADE\n"
        with patch.dict(sys.modules, {"pytesseract": module}):
            with patch("subprocess.run", return_value=result) as run:
                words = _cnh_ocr(MagicMock(), data=True)
        self.assertEqual(words, {
            "text": ["DOC", "IDENTIDADE"], "left": [944, 998], "top": [690, 686],
        })
        self.assertEqual(run.call_args.args[0][-1], "tsv")

    def test_subprocess_failure_does_not_change_environment(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_ocr

        module, _ = self._ocr_environment()
        with patch.dict(os.environ, {"OMP_THREAD_LIMIT": "7"}):
            with patch.dict(sys.modules, {"pytesseract": module}):
                with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tesseract")) as run:
                    with self.assertRaises(subprocess.CalledProcessError):
                        _cnh_ocr(MagicMock())
                    self.assertEqual(os.environ["OMP_THREAD_LIMIT"], "7")
                    self.assertFalse(Path(run.call_args.args[0][1]).parent.exists())

    @patch("apps.fleet.cnh._cnh_ocr", side_effect=RuntimeError("OCR indisponível"))
    def test_complementary_failure_preserves_original_extraction(self, _ocr):
        import sys
        import types
        from unittest.mock import MagicMock
        from apps.fleet.cnh import _cnh_field_text

        embedded = MagicMock()
        image = embedded.image.convert.return_value
        image.width, image.height = 963, 680
        reader = MagicMock()
        reader.pages = [types.SimpleNamespace(images=[embedded])]
        module = types.ModuleType("pypdf")
        module.PdfReader = MagicMock(return_value=reader)
        with patch.dict(sys.modules, {"pypdf": module}):
            self.assertEqual(_cnh_field_text(b"pdf"), "")


class CNHBrazilianDateFormatTests(SimpleTestCase):
    def test_cnh_date_fields_render_and_accept_brazilian_dates(self):
        form = CNHDriverCreateForm()
        for name, expected in (
            ("birth_date", "22/01/1987"),
            ("cnh_expiration", "14/04/2034"),
            ("cnh_issue_date", "16/04/2024"),
            ("cnh_first_issue_date", "29/09/2006"),
        ):
            field = form.fields[name]
            self.assertEqual(field.widget.input_type, "text")
            self.assertEqual(field.widget.attrs.get("placeholder"), "dd/mm/aaaa")
            self.assertEqual(field.clean(expected).isoformat(), {
                "birth_date": "1987-01-22",
                "cnh_expiration": "2034-04-14",
                "cnh_issue_date": "2024-04-16",
                "cnh_first_issue_date": "2006-09-29",
            }[name])

    def test_cnh_date_fields_format_iso_initial_values_for_brazil(self):
        form = CNHDriverCreateForm(initial={
            "birth_date": "1987-01-22",
            "cnh_expiration": "2034-04-14",
            "cnh_issue_date": "2024-04-16",
            "cnh_first_issue_date": "2006-09-29",
        })
        self.assertIn('value="22/01/1987"', str(form["birth_date"]))
        self.assertIn('value="14/04/2034"', str(form["cnh_expiration"]))
        self.assertIn('value="16/04/2024"', str(form["cnh_issue_date"]))
        self.assertIn('value="29/09/2006"', str(form["cnh_first_issue_date"]))


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
        self.assertTrue(driver.sectors.filter(pk=self.sector.pk).exists())
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


class CNHExistingDriverTests(TestCase):
    def setUp(self):
        import uuid
        from apps.fleet.models import BDT
        self.media_root = tempfile.TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=self.media_root.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.media_root.cleanup)
        self.user = get_user_model().objects.create_user(username="cnh-update-test", password="x")
        self.user.user_permissions.add(Permission.objects.get(codename="change_driver"))
        self.sector, _ = Sector.objects.get_or_create(slug="adm", defaults={"name": "ADM"})
        self.user.sectors.add(self.sector)
        self.driver = Driver.objects.create(
            name="MARIA DA SILVA HORUS", horus_user_id=uuid.uuid4(), registration="HORUS-17",
            phone="21999999999", email="maria@example.com",
        )
        self.driver.sectors.add(self.sector)
        self.bdt = BDT.objects.create(external_id=uuid.uuid4(), driver=self.driver, horus_management_id=125)
        self.url = f"/motoristas/{self.driver.pk}/cnh/?sector=adm"
        self.client.force_login(self.user)
        self.extracted = {
            "name": "MARIA DA SILVA", "cpf": "123.456.789-09", "cnh_number": "01234567890",
            "birth_date": "1985-02-01", "cnh_category": "AB", "cnh_expiration": "2030-12-31",
            "cnh_issue_date": "2025-06-05", "cnh_first_issue_date": "2005-03-12", "father_name": "JOSE DA SILVA",
            "mother_name": "ANA PEREIRA", "text_extraction_succeeded": True,
        }

    def upload(self, data=None, url=None):
        with patch("apps.fleet.cnh.extract_cnh_data", return_value=data or self.extracted):
            return self.client.post(url or self.url, {
                "step": "upload", "file": SimpleUploadedFile("cnh.pdf", b"%PDF-test"),
            })

    def confirm(self, document, **changes):
        values = {**self.extracted, "step": "confirm", "document_id": str(document.pk), "identity_confirmed": "on"}
        values.update(changes)
        return self.client.post(self.url, values)

    def document(self):
        return Document.objects.get(document_type__name="CNH")

    def test_existing_horus_driver_is_updated_without_creating_or_moving_records(self):
        original = (self.driver.pk, self.driver.horus_user_id, self.driver.registration, self.driver.name)
        total = Driver.objects.count()
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MARIA DA SILVA HORUS")
        self.assertNotIn("name", response.context["confirm_form"].fields)
        self.assertFalse(DocumentRelation.objects.exists())
        document = self.document()
        response = self.confirm(document, name="NOME ADULTERADO", registration="ALTERADA", phone="0", identity_document="")
        self.assertEqual(response.status_code, 302)
        self.driver.refresh_from_db()
        self.bdt.refresh_from_db()
        self.assertEqual((self.driver.pk, self.driver.horus_user_id, self.driver.registration, self.driver.name), original)
        self.assertEqual(Driver.objects.count(), total)
        self.assertEqual(self.bdt.driver_id, self.driver.pk)
        self.assertEqual(self.driver.phone, "21999999999")
        self.assertEqual(self.driver.email, "maria@example.com")
        self.assertEqual(set(self.driver.sectors.values_list("pk", flat=True)), {self.sector.pk})
        self.assertEqual(self.driver.cpf, self.extracted["cpf"])
        self.assertEqual(self.driver.cnh_number, self.extracted["cnh_number"])
        self.assertEqual(self.driver.cnh_history.count(), 1)
        self.assertTrue(DocumentRelation.objects.filter(document=document, object_id=self.driver.pk).exists())
        audit = AuditLog.objects.get(action="CNH ATUALIZADA A PARTIR DE PDF", entity_id=document.pk)
        self.assertEqual(audit.new_values["driver_id"], str(self.driver.pk))
        self.assertEqual(audit.new_values["form_values"]["mother_name"], "ANA PEREIRA")
        self.assertEqual(audit.old_values["cpf"], "")

    def test_renewal_preserves_earlier_pdf_and_history(self):
        self.upload()
        first = self.document()
        self.assertEqual(self.confirm(first).status_code, 302)
        second_values = {**self.extracted, "cnh_expiration": "2035-12-31", "cnh_issue_date": "2030-06-05"}
        self.assertEqual(self.upload(second_values).status_code, 200)
        second = Document.objects.exclude(pk=first.pk).get()
        response = self.confirm(second, cnh_expiration="2035-12-31", cnh_issue_date="2030-06-05")
        self.assertEqual(response.status_code, 302)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cnh_expiration, date(2035, 12, 31))
        self.assertEqual(self.driver.cnh_history.count(), 2)
        self.assertEqual(DocumentRelation.objects.filter(object_id=self.driver.pk).count(), 2)

    def test_wrong_cpf_or_registration_pdf_is_refused_before_document_storage(self):
        self.driver.cpf = self.extracted["cpf"]
        self.driver.cnh_number = self.extracted["cnh_number"]
        self.driver.save()
        for key, wrong in (("cpf", "987.654.321-00"), ("cnh_number", "99999999999")):
            with self.subTest(field=key):
                response = self.upload({**self.extracted, key: wrong})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["upload_form"].errors)
        self.assertEqual(Document.objects.count(), 0)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cnh_number, self.extracted["cnh_number"])

    def test_missing_identifiers_are_refused_even_for_first_link(self):
        response = self.upload({"name": "MARIA", "cpf": "", "cnh_number": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["upload_form"].errors)
        self.assertFalse(Document.objects.exists())

    def test_duplicate_identity_is_found_across_sectors_and_inactive_drivers(self):
        other_sector, _ = Sector.objects.get_or_create(slug="lei-seca", defaults={"name": "Lei Seca"})
        other = Driver.objects.create(name="OUTRA MARIA", cpf="12345678909", active=False)
        other.sectors.add(other_sector)
        response = self.upload()
        self.assertContains(response, "já pertence a outro motorista")
        self.assertFalse(Document.objects.exists())

    def test_tampered_confirmation_identifiers_are_refused(self):
        self.upload()
        document = self.document()
        for field, wrong in (("cpf", "987.654.321-00"), ("cnh_number", "99999999999")):
            with self.subTest(field=field):
                response = self.confirm(document, **{field: wrong})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["confirm_form"].errors)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cpf, "")
        self.assertFalse(DocumentRelation.objects.exists())
        self.assertFalse(self.driver.cnh_history.exists())

    def test_confirmation_is_required_and_replay_is_blocked(self):
        self.upload()
        document = self.document()
        response = self.confirm(document, identity_confirmed="")
        self.assertTrue(response.context["confirm_form"].errors)
        self.assertFalse(DocumentRelation.objects.exists())
        self.assertEqual(self.confirm(document).status_code, 302)
        self.assertEqual(self.confirm(document).status_code, 200)
        self.assertEqual(DocumentRelation.objects.count(), 1)
        self.assertEqual(self.driver.cnh_history.count(), 1)

    def test_document_cannot_be_confirmed_for_another_driver_or_user(self):
        self.upload()
        document = self.document()
        other = Driver.objects.create(name="OUTRO MOTORISTA")
        other.sectors.add(self.sector)
        original_url = self.url
        self.url = f"/motoristas/{other.pk}/cnh/?sector=adm"
        response = self.confirm(document)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preview"])
        self.url = original_url
        other_user = get_user_model().objects.create_user(username="another-cnh-user")
        other_user.sectors.add(self.sector)
        other_user.user_permissions.add(Permission.objects.get(codename="change_driver"))
        self.client.force_login(other_user)
        response = self.confirm(document)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preview"])
        self.assertFalse(DocumentRelation.objects.exists())

    def test_sector_and_permission_checks_apply_to_get_and_upload(self):
        other_sector, _ = Sector.objects.get_or_create(slug="lei-seca", defaults={"name": "Lei Seca"})
        other = Driver.objects.create(name="OUTRO SETOR")
        other.sectors.add(other_sector)
        response = self.client.get(f"/motoristas/{other.pk}/cnh/")
        self.assertEqual(response.status_code, 404)
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)

    def test_invalid_document_uuid_is_a_form_error(self):
        response = self.client.post(self.url, {**self.extracted, "step": "confirm", "document_id": "invalid", "identity_confirmed": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("document_id", response.context["confirm_form"].errors)

    def test_database_blocks_normalized_duplicates_even_without_form(self):
        from django.db import IntegrityError, transaction
        Driver.objects.create(name="CPF PRINCIPAL", cpf="123.456.789-09", cnh_number="01234567890")
        for values in ({"cpf": "12345678909"}, {"cnh_number": "012.345.678-90"}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Driver.objects.create(name="DUPLICADO", **values)

    def test_database_blocks_duplicate_from_queryset_update(self):
        from django.db import IntegrityError, transaction
        other = Driver.objects.create(name="CPF PRINCIPAL", cpf="123.456.789-09")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Driver.objects.filter(pk=self.driver.pk).update(cpf="12345678909")
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cpf, "")

    def test_legacy_empty_identifiers_and_first_fill_are_allowed_but_change_is_blocked(self):
        from django.core.exceptions import ValidationError
        Driver.objects.create(name="LEGADO SEM CPF")
        self.driver.cpf = "123.456.789-09"
        self.driver.cnh_number = "01234567890"
        self.driver.save()
        for field, value in (("cpf", ""), ("cpf", "987.654.321-00"), ("cnh_number", "99999999999")):
            with self.subTest(field=field, value=value):
                self.driver.refresh_from_db()
                setattr(self.driver, field, value)
                with self.assertRaises(ValidationError):
                    self.driver.save()
        self.driver.refresh_from_db()
        self.driver.cpf = "12345678909"
        self.driver.save()

    def test_identity_changed_after_upload_is_rechecked_at_confirmation(self):
        self.upload()
        document = self.document()
        self.driver.cpf = "987.654.321-00"
        self.driver.save()
        response = self.confirm(document)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["confirm_form"].errors)
        self.assertFalse(DocumentRelation.objects.exists())

    def test_new_driver_creation_rejects_duplicate_existing_driver(self):
        self.user.user_permissions.add(Permission.objects.get(codename="add_driver"))
        self.upload(url="/motoristas/novo/?sector=adm")
        document = self.document()
        self.driver.cpf = "12345678909"
        self.driver.save()
        self.url = "/motoristas/novo/?sector=adm"
        response = self.confirm(document)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Driver.objects.count(), 1)
        self.assertFalse(DocumentRelation.objects.exists())

    def test_manual_creation_and_edit_return_form_errors_on_identity_conflict(self):
        self.user.user_permissions.add(Permission.objects.get(codename="add_driver"))
        self.driver.cpf = "123.456.789-09"
        self.driver.save()
        values = {"name": "MARIA", "cpf": "12345678909", "active": "True", "sectors": [str(self.sector.pk)]}
        response = self.client.post("/motoristas/novo/?manual=1&sector=adm", values)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        response = self.client.post(f"/motoristas/{self.driver.pk}/editar/?sector=adm", {**values, "cpf": "987.654.321-00"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cpf, "123.456.789-09")

    def test_supplemental_document_data_is_preserved_when_later_ocr_is_blank(self):
        self.upload()
        first = self.document()
        self.assertEqual(self.confirm(first).status_code, 302)
        data = {**self.extracted, "father_name": "", "mother_name": "", "cnh_expiration": "2035-12-31"}
        self.upload(data)
        second = Document.objects.exclude(pk=first.pk).get()
        response = self.confirm(second, father_name="", mother_name="", cnh_expiration="2035-12-31")
        self.assertEqual(response.status_code, 302)
        audit = AuditLog.objects.get(action="CNH ATUALIZADA A PARTIR DE PDF", entity_id=second.pk)
        self.assertEqual(audit.new_values["form_values"]["father_name"], "JOSE DA SILVA")
        self.assertEqual(audit.new_values["form_values"]["mother_name"], "ANA PEREIRA")

    def test_pdf_uploaded_for_creation_cannot_update_an_existing_driver(self):
        self.user.user_permissions.add(Permission.objects.get(codename="add_driver"))
        self.upload(url="/motoristas/novo/?sector=adm")
        response = self.confirm(self.document())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preview"])
        self.assertFalse(DocumentRelation.objects.exists())

    def test_real_pdf_when_supplied_validates_ocr_and_existing_driver_link(self):
        import os
        from pathlib import Path
        source = os.environ.get("CNH_VALIDATION_PDF")
        if not source:
            self.skipTest("Real PDF supplied by the guarded VPS validation script.")
        self.driver.name = "ALBERTO FELIPE PEREIRA LOPA"
        self.driver.save(update_fields=["name", "updated_at"])
        response = self.client.post(self.url, {
            "step": "upload", "file": SimpleUploadedFile("cnh-real.pdf", Path(source).read_bytes(), content_type="application/pdf"),
        })
        self.assertEqual(response.status_code, 200)
        preview = response.context["preview"]
        expected = {
            "name": "ALBERTO FELIPE PEREIRA LOPA", "cpf": "113.483.417-93",
            "identity_document": "021012056533", "issuing_authority": "COMAER", "issuing_state": "RJ",
            "cnh_number": "03044729845", "cnh_category": "D", "nationality": "BRASILEIRO(A)",
            "father_name": "JOSE ALBERTO DE ALMEIDA LOPA", "mother_name": "MARIA CRISTINA PEREIRA",
            "birth_date": "1987-01-22", "cnh_expiration": "2034-04-14",
            "cnh_issue_date": "2024-04-16", "cnh_first_issue_date": "2006-09-29",
        }
        self.assertIsNotNone(preview)
        for key, value in expected.items():
            self.assertEqual(preview[key], value, key)
        response = self.confirm(self.document(), **expected)
        self.assertEqual(response.status_code, 302)
        self.driver.refresh_from_db()
        self.assertEqual(Driver.objects.count(), 1)
        self.assertEqual(self.driver.cnh_number, expected["cnh_number"])
        self.assertEqual(self.driver.horus_user_id, Driver.objects.get().horus_user_id)


    def test_horus_sync_after_pdf_keeps_cnh_and_existing_bdt_links(self):
        from rest_framework.test import APIRequestFactory
        from apps.fleet.sync_driver_views import DriverSyncAPIView
        self.upload()
        self.assertEqual(self.confirm(self.document()).status_code, 302)
        request = APIRequestFactory().post("/api/sync/drivers/", [{
            "external_id": str(self.driver.horus_user_id), "name": "MARIA HORUS ATUALIZADA", "registration": "OUTRA MATRICULA",
        }], format="json", HTTP_AUTHORIZATION="Bearer isolated-test-token")
        with override_settings(FLEET_SYNC_TOKEN="isolated-test-token"):
            response = DriverSyncAPIView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.driver.refresh_from_db()
        self.bdt.refresh_from_db()
        self.assertEqual(Driver.objects.count(), 1)
        self.assertEqual(self.driver.cpf, self.extracted["cpf"])
        self.assertEqual(self.driver.cnh_number, self.extracted["cnh_number"])
        self.assertEqual(self.driver.registration, "HORUS-17")
        self.assertEqual(self.bdt.driver_id, self.driver.pk)
        self.assertEqual(DocumentRelation.objects.filter(object_id=self.driver.pk).count(), 1)


    def test_manual_edit_has_same_document_fields_and_prefills_pdf_values(self):
        from apps.ui.forms import CNHDriverCreateForm
        self.upload()
        self.assertEqual(self.confirm(self.document()).status_code, 302)
        response = self.client.get(f"/motoristas/{self.driver.pk}/editar/?sector=adm")
        self.assertEqual(response.status_code, 200)
        form = response.context["confirm_form"]
        self.assertEqual([field.name for field in form.visible_fields()], CNHDriverCreateForm.Meta.fields)
        self.assertNotIn("document_id", form.fields)
        self.assertNotIn("registration", form.fields)
        self.assertNotIn("sectors", form.fields)
        self.assertNotIn("phone", form.fields)
        self.assertEqual(form["father_name"].value(), "JOSE DA SILVA")
        self.assertEqual(form["mother_name"].value(), "ANA PEREIRA")
        self.assertIn('value="05/06/2025"', str(form["cnh_issue_date"]))
        self.assertIn('value="31/12/2030"', str(form["cnh_expiration"]))
        self.assertTrue(form.fields["name"].disabled)
        self.assertNotContains(response, "Documento lido")
        self.assertNotContains(response, "Não foi possível reconhecer o texto")
        self.assertContains(response, "Salvar alterações")

    def test_manual_document_edit_persists_extra_fields_and_keeps_horus_pdf_and_sectors(self):
        from apps.fleet.services import current_cnh_document_values
        self.upload()
        document = self.document()
        self.assertEqual(self.confirm(document).status_code, 302)
        original_name = self.driver.name
        original_horus_id = self.driver.horus_user_id
        response = self.client.post(f"/motoristas/{self.driver.pk}/editar/?sector=adm", {
            **self.extracted, "name": "NOME ADULTERADO", "father_name": "JOSE DA SILVA CORRIGIDO",
            "mother_name": "ANA PEREIRA CORRIGIDA", "issuing_authority": "COMAER", "issuing_state": "RJ",
            "nationality": "BRASILEIRA", "identity_document": "123456789", "location": "RIO DE JANEIRO RJ",
            "cnh_issue_date": "05/06/2030", "cnh_expiration": "31/12/2035",
            "registration": "MATRICULA ADULTERADA", "phone": "0", "email": "outra@example.com",
            "active": "False", "sectors": [],
        })
        self.assertEqual(response.status_code, 302)
        self.driver.refresh_from_db()
        self.bdt.refresh_from_db()
        self.assertEqual(self.driver.name, original_name)
        self.assertEqual(self.driver.horus_user_id, original_horus_id)
        self.assertEqual(self.driver.registration, "HORUS-17")
        self.assertEqual(self.driver.phone, "21999999999")
        self.assertEqual(self.driver.email, "maria@example.com")
        self.assertTrue(self.driver.active)
        self.assertEqual(self.bdt.driver_id, self.driver.pk)
        self.assertEqual(Driver.objects.count(), 1)
        self.assertEqual(set(self.driver.sectors.values_list("pk", flat=True)), {self.sector.pk})
        self.assertTrue(DocumentRelation.objects.filter(document=document, object_id=self.driver.pk).exists())
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(self.driver.cnh_history.count(), 2)
        values = current_cnh_document_values(self.driver)
        self.assertEqual(values["father_name"], "JOSE DA SILVA CORRIGIDO")
        self.assertEqual(values["mother_name"], "ANA PEREIRA CORRIGIDA")
        self.assertEqual(values["identity_document"], "123456789")
        self.assertEqual(values["cnh_issue_date"], "2030-06-05")
        original_audit = AuditLog.objects.get(action="CNH ATUALIZADA A PARTIR DE PDF", entity_id=document.pk)
        self.assertEqual(original_audit.new_values["form_values"]["father_name"], "JOSE DA SILVA")
        response = self.client.get(f"/motoristas/{self.driver.pk}/editar/?sector=adm")
        self.assertEqual(response.context["confirm_form"]["father_name"].value(), "JOSE DA SILVA CORRIGIDO")

    def test_manual_document_edit_can_clear_extra_field_without_changing_source_pdf(self):
        from apps.fleet.services import current_cnh_document_values
        self.upload()
        self.assertEqual(self.confirm(self.document()).status_code, 302)
        response = self.client.post(f"/motoristas/{self.driver.pk}/editar/?sector=adm", {**self.extracted, "father_name": ""})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(current_cnh_document_values(self.driver)["father_name"], "")
        audit = AuditLog.objects.get(action="CNH EDITADA MANUALMENTE", entity_id=self.driver.pk)
        self.assertEqual(audit.old_values["father_name"], "JOSE DA SILVA")
        self.assertEqual(Document.objects.count(), 1)

    def test_manual_edit_of_driver_without_cnh_does_not_require_pdf_or_change_membership(self):
        response = self.client.post(f"/motoristas/{self.driver.pk}/editar/?sector=adm", {
            "name": "ADULTERADO", "father_name": "PAI INFORMADO", "mother_name": "MAE INFORMADA",
        })
        self.assertEqual(response.status_code, 302)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.name, "MARIA DA SILVA HORUS")
        self.assertEqual(self.driver.cpf, "")
        self.assertEqual(self.driver.cnh_number, "")
        self.assertTrue(self.driver.sectors.filter(pk=self.sector.pk).exists())
        self.assertFalse(Document.objects.exists())

    def test_manual_edit_rejects_identity_change_and_duplicate_with_no_partial_save(self):
        self.upload()
        self.assertEqual(self.confirm(self.document()).status_code, 302)
        url = f"/motoristas/{self.driver.pk}/editar/?sector=adm"
        for field, value in (("cpf", "987.654.321-00"), ("cnh_number", "99999999999")):
            with self.subTest(field=field):
                response = self.client.post(url, {**self.extracted, field: value, "father_name": "ALTERADO"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["confirm_form"].errors)
        self.assertFalse(AuditLog.objects.filter(action="CNH EDITADA MANUALMENTE").exists())
        other = Driver.objects.create(name="LEGADO SEM CPF")
        other.sectors.add(self.sector)
        response = self.client.post(f"/motoristas/{other.pk}/editar/?sector=adm", {**self.extracted, "name": "LEGADO SEM CPF"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["confirm_form"].errors)
        other.refresh_from_db()
        self.assertEqual(other.cpf, "")

    def test_pdf_update_after_manual_edit_uses_latest_document_history(self):
        self.upload()
        first = self.document()
        self.assertEqual(self.confirm(first).status_code, 302)
        response = self.client.post(f"/motoristas/{self.driver.pk}/editar/?sector=adm", {**self.extracted, "father_name": "PAI CONFERIDO"})
        self.assertEqual(response.status_code, 302)
        response = self.upload({**self.extracted, "father_name": "", "cnh_expiration": "2035-12-31"})
        self.assertEqual(response.context["confirm_form"]["father_name"].value(), "PAI CONFERIDO")
        second = Document.objects.exclude(pk=first.pk).get()
        self.assertEqual(self.confirm(second, father_name="", cnh_expiration="2035-12-31").status_code, 302)
        audit = AuditLog.objects.get(action="CNH ATUALIZADA A PARTIR DE PDF", entity_id=second.pk)
        self.assertEqual(audit.new_values["form_values"]["father_name"], "PAI CONFERIDO")


class CNHConcurrentDriverIdentityTests(TransactionTestCase):
    def test_concurrent_first_fill_accepts_one_driver_for_same_cpf(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connection, IntegrityError
        if connection.vendor != "postgresql":
            self.skipTest("Concurrency validation requires PostgreSQL.")
        drivers = [Driver.objects.create(name=f"CONCORRENTE {i}") for i in range(2)]
        barrier = Barrier(2)

        def fill(pk):
            close_old_connections()
            try:
                driver = Driver.objects.get(pk=pk)
                driver.cpf = "123.456.789-09"
                barrier.wait(timeout=15)
                try:
                    driver.save()
                    return "accepted"
                except IntegrityError:
                    return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(fill, [driver.pk for driver in drivers]))
        self.assertCountEqual(outcomes, ["accepted", "duplicate"])
        self.assertEqual(Driver.objects.exclude(cpf="").count(), 1)

class CNHMissingDigitalFieldsTests(SimpleTestCase):
    noisy_text = """
2e 1NOMEESOBRENOME ve mantração
MAURICIO DE JESUS ARAUJO 29/05/1989 n | Caia
3 DATA, LOCAL E UF DE NASCIMENTO
04/01/1971, RIO DE JANEIRO, RJ
4a DATA EMISSÃO 4b VALIDADE ACC
01/06/2023 30/05/2028
4c DOC IDENTIDADE / ORG EMISSOR / UF
054887039 DETRAN RJ
CPF 5 Nº REGISTRO 9 CAT HAB
990.565.777-00 00107964386 AB
NACIONALIDADE
BRASILEIRO
FILIAÇÃO
WILSON REINALDO DE ARAUJO
MARIA ERMELINDA DE JESUS ARAUJO
ASSINATURA DO PORTADOR
N toca med Sossnenie
a SAO JOAO DE MERITI, RJ RJ957899459
I<BRA001079643<862<<<<<<<<<<<<
7101043M2805302BRA<<<<<<<<<<<6
MAURICIO<<DE<JESUS<ARAUJO<<<<<
"""
    header_text = "2 e 1 NOME E SOBRENOME 1º HABILITAÇÃO\n| MAURICIO DE JESUS ARAUJO | | 29/05/1989 |\n"

    @patch("apps.fleet.cnh._cnh_missing_fields")
    @patch("apps.fleet.cnh._all_text")
    def test_recovers_missing_mauricio_fields_without_replacing_other_data(self, all_text, missing):
        all_text.return_value = self.noisy_text
        missing.return_value = {}
        before = extract_cnh_data(b"pdf")
        missing.return_value = {"name": "MAURICIO DE JESUS ARAUJO", "cnh_first_issue_date": "1989-05-29", "location": "SAO JOAO DE MERITI, RJ"}
        after = extract_cnh_data(b"pdf")
        self.assertEqual(after["name"], "MAURICIO DE JESUS ARAUJO")
        self.assertEqual(after["cnh_first_issue_date"], "1989-05-29")
        self.assertEqual(after["cnh_first_issue_date_display"], "29/05/1989")
        self.assertEqual(after["location"], "SAO JOAO DE MERITI, RJ")
        for key in before:
            if key not in {"name", "cnh_first_issue_date", "cnh_first_issue_date_display", "location"}:
                self.assertEqual(after[key], before[key], key)
        missing.assert_called_with(b"pdf", name=True, first_issue=True, location=True)
        self.assertEqual(after["cpf"], "990.565.777-00")
        self.assertEqual(after["cnh_number"], "00107964386")
        self.assertEqual(after["cnh_category"], "AB")

    @patch("apps.fleet.cnh._cnh_missing_fields")
    @patch("apps.fleet.cnh._all_text")
    def test_complete_fields_do_not_trigger_additional_ocr(self, all_text, missing):
        all_text.return_value = "NOME E SOBRENOME\nJOAO DA SILVA\n1ª HABILITAÇÃO\n01/02/1990\nLOCAL\nRIO DE JANEIRO, RJ\n"
        data = extract_cnh_data(b"pdf")
        self.assertEqual(data["name"], "JOAO DA SILVA")
        self.assertEqual(data["cnh_first_issue_date"], "1990-02-01")
        self.assertEqual(data["location"], "RIO DE JANEIRO, RJ")
        missing.assert_not_called()

    @patch("apps.fleet.cnh._cnh_missing_fields")
    @patch("apps.fleet.cnh._all_text")
    def test_existing_name_and_first_issue_date_cannot_be_replaced(self, all_text, missing):
        all_text.return_value = "NOME E SOBRENOME\nJOAO DA SILVA\n1ª HABILITAÇÃO\n01/02/1990\n"
        missing.return_value = {"name": "OUTRA PESSOA", "cnh_first_issue_date": "2020-01-01", "location": "RIO DE JANEIRO, RJ"}
        data = extract_cnh_data(b"pdf")
        self.assertEqual(data["name"], "JOAO DA SILVA")
        self.assertEqual(data["cnh_first_issue_date"], "1990-02-01")
        missing.assert_called_with(b"pdf", name=False, first_issue=False, location=True)

    def _reader(self):
        from types import SimpleNamespace
        from PIL import Image
        return SimpleNamespace(pages=[SimpleNamespace(images=[
            SimpleNamespace(image=Image.new("RGB", (591, 591))),
            SimpleNamespace(image=Image.new("RGB", (963, 680))),
            SimpleNamespace(image=Image.new("RGB", (963, 680))),
        ])])

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh._cnh_ocr")
    def test_crops_header_and_back_skips_qr_and_stops_after_recovery(self, ocr, reader):
        from apps.fleet.cnh import _cnh_missing_fields
        reader.return_value = self._reader()
        ocr.side_effect = [self.header_text, "LOCAL\n| SAO JOAO DE MERITI, RJ |\n"]
        data = _cnh_missing_fields(b"pdf", name=True, first_issue=True, location=True)
        self.assertEqual(data, {"name": "MAURICIO DE JESUS ARAUJO", "cnh_first_issue_date": "1989-05-29", "location": "SAO JOAO DE MERITI, RJ"})
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(ocr.call_args_list[0].args[0].size, (1618, 150))
        self.assertEqual(ocr.call_args_list[1].args[0].size, (1078, 150))

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh._cnh_ocr")
    def test_header_only_does_not_read_back(self, ocr, reader):
        from apps.fleet.cnh import _cnh_missing_fields
        reader.return_value = self._reader()
        ocr.return_value = self.header_text
        data = _cnh_missing_fields(b"pdf", name=True, first_issue=True)
        self.assertEqual(data["name"], "MAURICIO DE JESUS ARAUJO")
        self.assertEqual(data["cnh_first_issue_date"], "1989-05-29")
        ocr.assert_called_once()

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh._cnh_ocr")
    def test_location_requires_its_own_label_and_a_valid_state(self, ocr, reader):
        from apps.fleet.cnh import _cnh_missing_fields
        reader.return_value = self._reader()
        ocr.side_effect = ["DATA, LOCAL E UF DE NASCIMENTO\n04/01/1971, RIO DE JANEIRO, RJ\n", "LOCAL\nCIDADE, AD\n"]
        self.assertEqual(_cnh_missing_fields(b"pdf", location=True), {})

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh._cnh_ocr")
    def test_later_ocr_failure_preserves_recovered_header_fields(self, ocr, reader):
        from apps.fleet.cnh import _cnh_missing_fields
        reader.return_value = self._reader()
        ocr.side_effect = [self.header_text, RuntimeError("OCR indisponível")]
        data = _cnh_missing_fields(b"pdf", name=True, first_issue=True, location=True)
        self.assertEqual(data["name"], "MAURICIO DE JESUS ARAUJO")
        self.assertEqual(data["cnh_first_issue_date"], "1989-05-29")
        self.assertNotIn("location", data)

    def test_real_mauricio_pdf_when_supplied(self):
        import os
        from pathlib import Path
        filename = os.environ.get("CNH_MAURICIO_VALIDATION_PDF")
        if not filename:
            self.skipTest("PDF real fornecido pela validação isolada da VPS.")
        data = extract_cnh_data(Path(filename).read_bytes())
        expected = {
            "name": "MAURICIO DE JESUS ARAUJO", "cnh_first_issue_date": "1989-05-29",
            "cnh_first_issue_date_display": "29/05/1989", "location": "SAO JOAO DE MERITI, RJ",
            "cpf": "990.565.777-00", "cnh_number": "00107964386", "cnh_category": "AB",
            "birth_date": "1971-01-04", "cnh_expiration": "2028-05-30", "cnh_issue_date": "2023-06-01",
            "identity_document": "054887039", "issuing_authority": "DETRAN", "issuing_state": "RJ",
            "father_name": "WILSON REINALDO DE ARAUJO", "mother_name": "MARIA ERMELINDA DE JESUS ARAUJO",
        }
        for key, value in expected.items():
            self.assertEqual(data[key], value, key)
