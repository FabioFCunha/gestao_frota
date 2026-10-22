import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from pypdf import PdfWriter

from apps.fleet.cnh import _all_text as cnh_text
from apps.fleet.crlv import _all_text as crlv_text
from apps.fleet.models import Document, DocumentVersion, Vehicle, VehicleStatus
from apps.fleet.services import stage_cnh_document_for_creation, stage_crlv_document, stage_crlv_document_for_creation


def pdf_bytes(*, pages=1, password=None):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=400)
    if password:
        writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class IdentificationPDFValidationTests(SimpleTestCase):
    def test_invalid_encrypted_empty_and_excessive_pdfs_are_rejected_before_ocr(self):
        cases = [
            (b"not a PDF", "corrompido"),
            (pdf_bytes(password="secret"), "senha"),
            (pdf_bytes(pages=0), "páginas"),
            (pdf_bytes(pages=11), "até 10 páginas"),
        ]
        for raw, message in cases:
            for read in (cnh_text, lambda data: crlv_text(data, "crlv.pdf")):
                with self.subTest(message=message, read=read), patch("pdf2image.convert_from_bytes") as convert:
                    with self.assertRaisesMessage(ValueError, message):
                        read(raw)
                    convert.assert_not_called()

    def test_page_limit_is_configurable(self):
        with override_settings(DOCUMENT_MAX_PDF_PAGES=1), self.assertRaisesMessage(ValueError, "até 1 páginas"):
            cnh_text(pdf_bytes(pages=2))

    def test_blank_valid_pdf_uses_ocr_with_conversion_timeout(self):
        for read in (cnh_text, lambda data: crlv_text(data, "crlv.pdf")):
            with self.subTest(read=read), patch("pdf2image.convert_from_bytes", return_value=[]) as convert:
                self.assertEqual(read(pdf_bytes()), "")
                self.assertEqual(convert.call_args.kwargs["timeout"], 30)


class FailedPDFStagingTests(TestCase):
    def test_invalid_upload_creates_no_document_or_file_for_cnh_and_crlv(self):
        user = get_user_model().objects.create_user(username="pdf-import-check")
        vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name="PDF test"))
        stages = [
            lambda upload: stage_cnh_document_for_creation(file_obj=upload, user=user),
            lambda upload: stage_crlv_document_for_creation(file_obj=upload, user=user),
            lambda upload: stage_crlv_document(file_obj=upload, user=user, vehicle=vehicle),
        ]
        for stage in stages:
            with self.subTest(stage=stage), patch("django.core.files.storage.FileSystemStorage.save") as save:
                with self.assertRaises(ValueError):
                    stage(SimpleUploadedFile("documento.pdf", b"invalid pdf"))
                save.assert_not_called()
                self.assertFalse(Document.objects.exists())
                self.assertFalse(DocumentVersion.objects.exists())
