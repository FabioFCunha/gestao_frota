"""Leitura por campos do modelo digital antigo (frente e verso verdes)."""
import io
import re


def _crop(image, bounds, scale=3):
    crop = image.crop(tuple(
        round(value * (image.width if index % 2 == 0 else image.height))
        for index, value in enumerate(bounds)
    ))
    return crop.resize((crop.width * scale, crop.height * scale))


def _read(image, bounds, scale=3):
    from .cnh import _cnh_ocr
    try:
        return _cnh_ocr(_crop(image, bounds, scale)).upper()
    except Exception:
        # A recuperação complementar não deve impedir a conferência manual.
        return ""


def legacy_cnh_images(raw):
    """Exige os rótulos e sua posição; não aplica recortes a outro modelo/QR."""
    from pypdf import PdfReader
    front = back = None
    try:
        for page in PdfReader(io.BytesIO(raw)).pages:
            for embedded in page.images:
                image = embedded.image.convert("RGB")
                if image.width < 500 or not 1.35 < image.width / image.height < 1.5:
                    continue
                header = _read(image, (.16, .21, .97, .36))
                if (re.search(r"\bNOME\b", header) and "SOBRENOME" not in header
                        and re.search(r"DOC\.?\s*IDENTIDADE", header)):
                    labels = _read(image, (.16, .87, .97, .922))
                    if all(word in labels for word in ("REGISTRO", "VALIDADE", "HABILITA")):
                        front = image
                elif front is not None:
                    labels = _read(image, (.16, .55, .95, .65))
                    if re.search(r"\bLOCAL\b", labels) and re.search(r"DATA\s+EMISS", labels):
                        back = image
    except Exception:
        return None, None
    return front, back


def _cpf_digits(text):
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) != 11 or len(set(digits)) == 1:
        return ""
    for length in (9, 10):
        check = sum(int(digit) * weight for digit, weight in zip(digits[:length], range(length + 1, 1, -1))) * 10 % 11 % 10
        if check != int(digits[length]):
            return ""
    return digits


def _name(text):
    from .cnh import _clean
    # O nome pode quebrar no meio de uma palavra na borda do campo.
    text = text.strip()
    # Reconstitui apenas quebras reconhecíveis, sem unir nomes completos
    # legítimos (por exemplo, RUI / ALVES).
    surnames = {"SILVA", "PEREIRA", "OLIVEIRA", "ALMEIDA", "RODRIGUES", "NASCIMENTO", "FERREIRA", "CARVALHO", "SANTOS"}
    def join_boundary(match):
        left, right = match.groups()
        if len(left) == 1 or left + right in surnames:
            return left + right
        return left + " " + right
    text = re.sub(r"\b([A-Z]{1,3})[ \t]*\n([A-Z]{2,})\b", join_boundary, text)
    text = _clean(text).strip(" |")
    return text if re.fullmatch(r"[A-ZÀ-ÖØ-Þ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ'’.-]+){1,9}", text) else ""


def extract_legacy_cnh_data(raw):
    from .cnh import _iso_date, _br_date, _CNH_VALID_CATEGORIES
    front, back = legacy_cnh_images(raw)
    if front is None:
        return {}
    result = {"name": _name(_read(front, (.166, .268, .94, .306)))}
    # Não reutilize o primeiro CPF do OCR da página inteira: bordas e QR
    # podem duplicar números. Confira os dígitos verificadores deste recorte.
    cpf = ""
    for scale in (2, 1, 3):
        cpf = _cpf_digits(_read(front, (.503, .448, .739, .502), scale))
        if cpf:
            break
    result["cpf"] = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if cpf else ""
    number = re.sub(r"\D", "", _read(front, (.166, .91, .475, .955)))
    result["cnh_number"] = number if len(number) == 11 else ""
    category = _read(front, (.84, .805, .935, .854)).strip(" \n|[]")
    result["cnh_category"] = category if category in _CNH_VALID_CATEGORIES else ""
    identity = _read(front, (.50, .35, .94, .405))
    found = re.search(r"(?m)^\s*(\d[\d. -]{4,19})\s+([A-Z][A-Z./-]{1,19})\s+([A-Z]{2})\s*$", identity)
    if found:
        from .cnh import _CNH_STATES, _clean
        if found.group(3) in _CNH_STATES:
            result.update(identity_document=_clean(found.group(1)),
                          issuing_authority=found.group(2), issuing_state=found.group(3))
    for field, bounds in (
        ("birth_date", (.765, .451, .94, .497)),
        ("cnh_expiration", (.5, .91, .699, .955)),
        ("cnh_first_issue_date", (.72, .91, .94, .955)),
    ):
        match = re.search(r"\d{2}/\d{2}/\d{4}", _read(front, bounds))
        result[field] = _iso_date(match.group()) if match else ""
        result[field + "_display"] = _br_date(result[field])
    father = _name(_read(front, (.5, .55, .94, .64)))
    mother = _name(_read(front, (.5, .65, .94, .755)))
    if father and mother:
        result.update(father_name=father, mother_name=mother)
    if back is not None:
        text = _read(back, (.165, .60, .70, .645))
        match = re.search(r"([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ .'-]+),\s*([A-Z]{2})\b", text)
        if match:
            from .cnh import _CNH_STATES, _clean
            if match.group(2) in _CNH_STATES:
                result["location"] = _clean(match.group(1)) + ", " + match.group(2)
        text = _read(back, (.72, .60, .94, .645))
        match = re.search(r"\d{2}/\d{2}/\d{4}", text)
        result["cnh_issue_date"] = _iso_date(match.group()) if match else ""
        result["cnh_issue_date_display"] = _br_date(result["cnh_issue_date"])
    return result
