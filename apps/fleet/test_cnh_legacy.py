import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from apps.fleet.cnh_legacy import extract_legacy_cnh_data, legacy_cnh_images, _cpf_digits


class LegacyCNHTests(SimpleTestCase):
    def setUp(self):
        self.front = Image.new("RGB", (963, 680), "green")
        self.back = Image.new("RGB", (963, 680), "white")

    def field_text(self, image, bounds, scale=3):
        values = {
            (.166, .268, .94, .306): "MOTORISTA DE TESTE",
            (.503, .448, .739, .502): "123.456.789-09",
            (.166, .91, .475, .955): "01234567890",
            (.84, .805, .935, .854): "AD",
            (.50, .35, .94, .405): "123456789 DETRAN RJ",
            (.765, .451, .94, .497): "25/08/1983",
            (.5, .91, .699, .955): "01/07/2031",
            (.72, .91, .94, .955): "18/12/2006",
            (.5, .55, .94, .64): "PAI DO MOTORISTA",
            (.5, .65, .94, .755): "MARIA OLIVEIRA DA S\nILVA",
            (.165, .60, .70, .645): "RIO DE JANEIRO, RJ",
            (.72, .60, .94, .645): "22/10/2021",
        }
        return values[bounds]

    @patch("apps.fleet.cnh_legacy.legacy_cnh_images")
    @patch("apps.fleet.cnh_legacy._read")
    def test_isolates_dates_identity_and_wrapped_parent_names(self, read, images):
        images.return_value = self.front, self.back
        read.side_effect = self.field_text
        data = extract_legacy_cnh_data(b"pdf")
        self.assertEqual(data["name"], "MOTORISTA DE TESTE")
        self.assertEqual(data["cpf"], "123.456.789-09")
        self.assertEqual(data["cnh_number"], "01234567890")
        self.assertEqual(data["issuing_authority"], "DETRAN")
        self.assertEqual(data["issuing_state"], "RJ")
        self.assertEqual(data["cnh_category"], "AD")
        self.assertEqual(data["cnh_expiration"], "2031-07-01")
        self.assertEqual(data["cnh_first_issue_date"], "2006-12-18")
        self.assertEqual(data["cnh_issue_date"], "2021-10-22")
        self.assertEqual(data["cnh_first_issue_date_display"], "18/12/2006")
        self.assertEqual(data["mother_name"], "MARIA OLIVEIRA DA SILVA")
        self.assertEqual(data["father_name"], "PAI DO MOTORISTA")
        self.assertEqual(data["location"], "RIO DE JANEIRO, RJ")
        self.assertNotIn("nationality", data)  # Não consta neste modelo.

    def test_cpf_requires_valid_check_digits(self):
        self.assertEqual(_cpf_digits("123.456.789-09"), "12345678909")
        for invalid in ("123.456.789-00", "11111111111", "123456789009"):
            self.assertEqual(_cpf_digits(invalid), "")

    @patch("apps.fleet.cnh_legacy.legacy_cnh_images")
    @patch("apps.fleet.cnh_legacy._read")
    def test_unreadable_dates_do_not_reuse_adjacent_field(self, read, images):
        images.return_value = self.front, None
        read.side_effect = lambda image, bounds, scale=3: (
            "unreadable" if bounds == (.72, .91, .94, .955) else self.field_text(image, bounds, scale)
        )
        self.assertEqual(extract_legacy_cnh_data(b"pdf")["cnh_first_issue_date"], "")

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh_legacy._read")
    def test_new_model_and_qr_are_not_treated_as_old_model(self, read, reader):
        qr = SimpleNamespace(image=Image.new("RGB", (591, 591)))
        front = SimpleNamespace(image=self.front)
        reader.return_value.pages = [SimpleNamespace(images=[qr, front])]
        read.return_value = "NOME E SOBRENOME DOC. IDENTIDADE HABILITAÇÃO"
        self.assertEqual(legacy_cnh_images(b"pdf"), (None, None))
        self.assertEqual(read.call_count, 1)

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh_legacy._read")
    def test_requires_bottom_labels_before_accepting_photo_layout(self, read, reader):
        reader.return_value.pages = [SimpleNamespace(images=[SimpleNamespace(image=self.front)])]
        read.side_effect = ["NOME MOTORISTA DE TESTE DOC. IDENTIDADE", "OTHER DOCUMENT"]
        self.assertEqual(legacy_cnh_images(b"pdf"), (None, None))

    @patch("apps.fleet.cnh._cnh_ocr", side_effect=RuntimeError("OCR unavailable"))
    def test_optional_crop_failure_is_empty_not_server_error(self, _ocr):
        from apps.fleet.cnh_legacy import _read
        self.assertEqual(_read(self.front, (.1, .1, .2, .2)), "")

    @patch("pypdf.PdfReader")
    @patch("apps.fleet.cnh_legacy.legacy_cnh_images")
    def test_legacy_photo_is_cropped_from_front(self, images, reader):
        from apps.ui.cnh_photo import extract_cnh_photo
        reader.return_value.pages = []
        images.return_value = self.front, self.back
        photo = Image.open(io.BytesIO(extract_cnh_photo(b"pdf")))
        self.assertEqual(photo.size, (264, 358))
        self.assertEqual(photo.format, "JPEG")


@skipUnless(os.environ.get("CNH_LEGACY_VALIDATION_PDF"), "PDF real disponível apenas na validação local protegida.")
class RealLegacyCNHTests(TestCase):
    def test_real_upload_confirmation_and_photo_preserve_driver(self):
        import tempfile
        from apps.fleet.models import Driver, Sector, DriverCNHPhoto, DocumentRelation
        expected = json.loads(Path(os.environ["CNH_LEGACY_EXPECTED_JSON"]).read_text())
        user = get_user_model().objects.create_user(username="legacy-pdf-check")
        user.user_permissions.add(Permission.objects.get(codename="change_driver"))
        sector, _ = Sector.objects.get_or_create(slug="adm", defaults={"name": "ADM"})
        user.sectors.add(sector)
        driver = Driver.objects.create(name="CADASTRO PRESERVADO")
        driver.sectors.add(sector)
        self.client.force_login(user)
        url = f"/motoristas/{driver.pk}/cnh/?sector=adm"
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            response = self.client.post(url, {"step": "upload", "file": SimpleUploadedFile(
                "cnh.pdf", Path(os.environ["CNH_LEGACY_VALIDATION_PDF"]).read_bytes(),
            )})
            self.assertEqual(response.status_code, 200)
            preview = response.context["preview"]
            for key, value in expected.items():
                if key != "text_extracted":
                    self.assertEqual(preview[key], value, key)
            response = self.client.post(url, {**preview, "step": "confirm",
                "document_id": str(response.context["document"].pk),
                "identity_confirmed": "on", "save_cnh_photo": "1"})
            self.assertEqual(response.status_code, 302)
            driver.refresh_from_db()
            self.assertEqual(driver.name, "CADASTRO PRESERVADO")
            self.assertEqual(driver.cpf, expected["cpf"])
            self.assertEqual(driver.cnh_category, expected["cnh_category"])
            self.assertEqual(Driver.objects.count(), 1)
            self.assertEqual(DocumentRelation.objects.filter(object_id=driver.pk).count(), 1)
            photo = DriverCNHPhoto.objects.get(driver=driver)
            self.assertTrue(photo.active)
            self.assertEqual(Image.open(io.BytesIO(bytes(photo.image))).format, "JPEG")
