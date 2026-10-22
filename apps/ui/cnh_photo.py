import io
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404

from apps.accounts.decorators import module_permission
from apps.fleet.models import (
    AuditLog, Document, Driver, DriverCNHPhoto,
)
from apps.fleet.driver_scope import apply_driver_sector_scope


def extract_cnh_photo(raw):
    """Recorte do modelo digital identificado; outros modelos não são presumidos."""
    from pypdf import PdfReader
    from apps.fleet.cnh import _cnh_ocr

    try:
        for page in PdfReader(io.BytesIO(raw)).pages:
            for embedded in page.images:
                image = embedded.image.convert("RGB")
                if image.width < 500 or not 1.35 < image.width / image.height < 1.5:
                    continue

                def crop(bounds):
                    return image.crop(tuple(
                        round(v * (image.width if i % 2 == 0 else image.height))
                        for i, v in enumerate(bounds)
                    ))

                header = crop((.16, .24, 1., .35))
                header = header.resize((header.width * 2, header.height * 2))
                text = _cnh_ocr(header).upper()
                if not (
                    re.search(r"\bNOME\b", text)
                    and re.search(r"HABILITA", text)
                ):
                    continue

                portrait = crop((.18, .365, .425, .84))
                portrait.thumbnail((450, 600))
                output = io.BytesIO()
                portrait.save(output, format="JPEG", quality=90)
                return output.getvalue()
    except Exception:
        return None
    # O modelo antigo tem foto e rótulos em outras posições.
    from apps.fleet.cnh_legacy import legacy_cnh_images, _crop
    front, _ = legacy_cnh_images(raw)
    if front is not None:
        portrait = _crop(front, (.184, .333, .458, .859), scale=1)
        portrait.thumbnail((450, 600))
        output = io.BytesIO()
        portrait.save(output, format="JPEG", quality=90)
        return output.getvalue()
    return None


def document_photo(document):
    version = document.versions.order_by("-created_at").first()
    if not version:
        return None
    try:
        with version.file.open("rb") as file:
            return extract_cnh_photo(file.read())
    except OSError as exc:
        raise ValueError("Não foi possível ler o PDF da CNH para salvar a foto. Envie o documento novamente.") from exc


def save_confirmed_cnh_photo(*, driver, document, user):
    # Chamado somente após a validação da identidade e do documento.
    image = document_photo(document)
    if not image:
        raise ValueError("Não foi possível extrair a foto desta CNH. Desmarque a opção de salvar a foto para confirmar somente os dados.")

    previous = DriverCNHPhoto.objects.filter(driver=driver).first()
    old_document = str(previous.document_id) if previous else None

    DriverCNHPhoto.objects.update_or_create(
        driver=driver,
        defaults={
            "document": document,
            "image": image,
            "confirmed_by": user,
            "active": True,
        },
    )
    AuditLog.objects.create(
        user=user,
        module="cnh",
        action="FOTO CNH CONFIRMADA",
        entity_type="driver",
        entity_id=driver.pk,
        old_values={"document_id": old_document},
        new_values={"document_id": str(document.pk)},
    )
    return True


def image_response(image):
    response = HttpResponse(bytes(image), content_type="image/jpeg")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def cnh_photo_preview(request, pk):
    document = get_object_or_404(
        Document, pk=pk, created_by=request.user,
        document_type__name__iexact="CNH",
    )
    staged = AuditLog.objects.filter(
        user=request.user,
        module="cnh",
        entity_type="document",
        entity_id=document.pk,
        action__in=[
            "CNH PARA CADASTRO DE MOTORISTA",
            "CNH PARA ATUALIZAR MOTORISTA",
        ],
    ).order_by("-created_at").first()
    if not staged:
        raise Http404

    driver_id = (staged.new_values or {}).get("driver_id")
    if driver_id:
        get_object_or_404(
            apply_driver_sector_scope(
                Driver.objects.all(), request.user, request.GET.get("sector"),
            ),
            pk=driver_id,
        )
    elif not (
        request.user.is_system_creator
        or request.user.has_perm("fleet.add_driver")
    ):
        raise Http404

    try:
        image = document_photo(document)
    except ValueError as exc:
        raise Http404 from exc
    if not image:
        raise Http404
    return image_response(image)


@login_required
@module_permission("fleet.view_driver")
def driver_cnh_photo(request, pk):
    driver = get_object_or_404(
        apply_driver_sector_scope(
            Driver.objects.all(), request.user, request.GET.get("sector"),
        ),
        pk=pk,
    )
    photo = get_object_or_404(DriverCNHPhoto, driver=driver)
    return image_response(photo.image)
