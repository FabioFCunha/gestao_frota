"""Validação estrutural antes de processar documentos de identificação."""
import io

from django.conf import settings
from pypdf import PdfReader


def identification_pdf_reader(raw):
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("O PDF está protegido por senha. Envie uma cópia sem senha.")
        count = len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Não foi possível abrir o PDF. O arquivo pode estar corrompido; envie outra cópia.") from exc
    maximum = getattr(settings, "DOCUMENT_MAX_PDF_PAGES", 10)
    if not count:
        raise ValueError("O PDF não contém páginas.")
    if count > maximum:
        raise ValueError(f"Envie somente o documento de identificação, com até {maximum} páginas.")
    return reader
