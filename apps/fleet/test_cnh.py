from datetime import date
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings

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
