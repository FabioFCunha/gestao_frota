# -*- coding: utf-8 -*-
"""Leitura e extração de dados de CNH em PDF, com OCR como fallback."""

import io
import re
from datetime import datetime


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip(" \t\r\n:.-")


def _all_text(raw):
    """Extrai texto nativo e usa OCR quando o PDF só contém cabeçalhos/QR."""
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        text = ""

    # Alguns PDFs oficiais têm uma camada de texto mínima (cabeçalho e
    # instruções do QR-Code), enquanto os dados da CNH estão só na imagem.
    # Portanto, texto não vazio não significa que a CNH foi efetivamente lida.
    useful_text = bool(
        len(re.findall(
            r"\b(?:NOME|CPF|REGISTRO|VALIDADE|NASCIMENTO|CATEGORIA|CAT\.?\s*HAB)\b",
            text,
            re.IGNORECASE,
        )) >= 3
        and re.search(
            r"\d{2}[./-]\d{2}[./-]\d{4}|"
            r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\b\d{9,11}\b",
            text,
        )
    )
    if useful_text:
        return text

    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(raw, dpi=300)
        ocr_text = "\n".join(
            pytesseract.image_to_string(page, lang="por+eng", config="--psm 6")
            for page in pages
        )
        # Mantém o texto nativo como complemento, mas prioriza a camada OCR
        # para que os campos impressos na imagem também possam ser analisados.
        return "\n".join(part for part in (ocr_text, text) if part.strip())
    except Exception:
        # A extração nativa ainda pode permitir preenchimento manual, mesmo
        # quando o ambiente não dispõe de OCR/Poppler.
        return text


def _cnh_field_text(raw):
    """OCR complementar da coluna da CNH, sem incluir o QR Code."""
    try:
        from pypdf import PdfReader
        import pytesseract

        reader = PdfReader(io.BytesIO(raw))
        for page in reader.pages:
            for embedded in page.images:
                image = embedded.image.convert("RGB")
                if image.width < 500 or image.width <= image.height:
                    continue
                image = image.resize((image.width * 2, image.height * 2))
                words = pytesseract.image_to_data(
                    image, lang="por+eng", config="--psm 6",
                    output_type=pytesseract.Output.DICT,
                )
                for index, word in enumerate(words["text"]):
                    token = re.sub(r"[^A-Z]", "", word.upper())
                    if token not in ("DOC", "DOCIDENTIDADE"):
                        continue
                    left = max(0, words["left"][index] - round(image.width * 0.035))
                    top = max(0, words["top"][index] - 8)
                    text = pytesseract.image_to_string(
                        image.crop((left, top, image.width, image.height)),
                        lang="por+eng", config="--psm 6",
                    )
                    if re.search(r"(?:[OÓ]RG\.?|[OÓ]RG[ÃA]O)\s*EMISSOR\s*/?\s*UF", text, re.IGNORECASE):
                        return text
    except Exception:
        # Falha no recurso complementar preserva a extração original.
        return ""
    return ""

def _iso_date(value):
    value = _clean(value)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except (TypeError, ValueError):
            continue
    return ""


def _br_date(value):
    normalized = _iso_date(value)
    if not normalized:
        return ""
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _date_field(text, labels):
    date_pattern = r"(\d{2}[./-]\d{2}[./-]\d{4}|\d{4}-\d{2}-\d{2})"
    for label in labels:
        match = re.search(
            label + r"\s*(?:[:\-]|\n)?\s*" + date_pattern,
            text,
            re.IGNORECASE,
        )
        if match:
            return _iso_date(match.group(1).replace(".", "/"))

        # OCR may put the field label and its value in different columns.
        match = re.search(label, text, re.IGNORECASE)
        if match:
            window = text[match.end():match.end() + 100]
            date_match = re.search(date_pattern, window)
            if date_match:
                return _iso_date(date_match.group(1).replace(".", "/"))
    return ""


def _mrz_dates(text):
    """Read birth and expiration dates from the driver's license MRZ line."""
    for line in text.splitlines():
        compact = re.sub(r"\s+", "", line.upper())
        match = re.search(r"(\d{6})\d[MF<](\d{6})\d", compact)
        if not match:
            continue
        birth_raw, expiry_raw = match.groups()

        def parse_mrz_date(value, field="birth"):
            yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
            if field == "expiry":
                # Expiration dates normally belong to this century. Using
                # the birth-date pivot incorrectly turns YY=34 into 1934.
                year = 2000 + yy
                if year > datetime.now().year + 20:
                    year -= 100
            else:
                # Birth dates use a pivot: YY=87 resolves to 1987.
                year = (1900 if yy > 30 else 2000) + yy
            try:
                return datetime(year, mm, dd).date().isoformat()
            except ValueError:
                return ""

        return parse_mrz_date(birth_raw), parse_mrz_date(expiry_raw, "expiry")
    return "", ""

def _field_value(text, labels, stop_labels, max_len=120):
    for label in labels:
        match = re.search(label + r"\s*(?:[:\-]|\n)?\s*", text, re.IGNORECASE)
        if not match:
            continue
        tail = text[match.end():match.end() + max_len]
        if stop_labels:
            stop = re.search(r"(?:" + "|".join(stop_labels) + r")\s*(?:[:\-]|\n)?", tail, re.IGNORECASE)
            if stop:
                tail = tail[:stop.start()]
        value = _clean(tail)
        if value:
            return value
    return ""


def _name_field(text):
    """Extrai o nome sem confundir o rótulo SOBRENOME com o campo NOME."""
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    label_re = re.compile(
        r"(?<![A-ZÀ-Ü])(?:NOME\s+E\s+SOBRENOME|NOME\s+COMPLETO|NOME)(?![A-ZÀ-Ü])",
        re.IGNORECASE,
    )
    stop_re = re.compile(
        r"\b(?:CPF|DOC\.?\s*IDENTIDADE|IDENTIDADE|DATA\s+NASCIMENTO|"
        r"NASCIMENTO|FILIA[CÇ][AÃ]O|VALIDADE|CAT\.?\s*HAB\.?|CATEGORIA|"
        r"N[º°O]\s*REGISTRO|REGISTRO|1[ªA]\s*HABILITA[CÇ][AÃ]O|"
        r"DATA\s+(?:DA\s+)?EMISS[AÃ]O|NACIONALIDADE|OBSERVA[CÇ][OÕ]ES|LOCAL)\b",
        re.IGNORECASE,
    )
    name_re = re.compile(
        r"[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’.-]*"
        r"(?:\s+[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’.-]*){1,7}\Z"
    )

    def valid_name(candidate):
        candidate = _clean(candidate)
        stop = stop_re.search(candidate)
        if stop:
            candidate = _clean(candidate[:stop.start()])
        date = re.search(r"\b\d{2}[./-]\d{2}[./-]\d{4}\b", candidate)
        if date:
            candidate = _clean(candidate[:date.start()])
        if not candidate or len(candidate) > 80:
            return ""
        if not name_re.fullmatch(candidate):
            return ""
        return candidate

    for index, line in enumerate(lines):
        match = label_re.search(line)
        if not match:
            continue
        # Tenta apenas o restante da mesma linha, sem consumir o restante da página.
        candidate = valid_name(line[match.end():])
        if candidate:
            return candidate
        # Em leiautes com o valor na linha seguinte, aceita somente uma linha
        # que tenha aparência de nome, nunca cabeçalhos, datas ou números.
        if index + 1 < len(lines):
            candidate = valid_name(lines[index + 1])
            if candidate:
                return candidate
    return ""


def _cpf(text):
    pattern = r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)"
    match = re.search(r"\bCPF\b.{0,100}?" + pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        # OCR may separate the CPF value from its label with neighboring fields.
        match = re.search(pattern, text)
    if not match:
        return ""
    digits = re.sub(r"\D", "", match.group(1))
    if len(digits) != 11:
        return ""
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

def extract_cnh_data(file_obj):
    """Extrai os dados mais comuns de CNHs brasileiras; valores devem ser conferidos."""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    raw = file_obj.read() if hasattr(file_obj, "read") else bytes(file_obj)
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    text = _all_text(raw)
    upper = text.upper()
    stops = [
        r"CPF", r"DOC\.?\s*IDENTIDADE", r"IDENTIDADE", r"DATA\s+NASCIMENTO",
        r"FILIA[CÇ][AÃ]O", r"VALIDADE", r"CAT\.?\s*HAB\.?", r"CATEGORIA",
        r"N[º°O]\s*REGISTRO", r"REGISTRO", r"1[ªA]\s*HABILITA[CÇ][AÃ]O",
        r"DATA\s+(?:DA\s+)?EMISS[AÃ]O", r"NACIONALIDADE", r"OBSERVA[CÇ][OÕ]ES",
    ]

    name = _name_field(upper)

    cnh_number = _field_value(
        upper,
        [r"N[º°O]\s*(?:DE\s*)?REGISTRO", r"N[ÚU]MERO\s+DE\s+REGISTRO", r"REGISTRO"],
        [r"VALIDADE", r"CAT\.?\s*HAB\.?", r"CATEGORIA", r"1[ªA]\s*HABILITA[CÇ][AÃ]O"],
        max_len=50,
    )
    number_match = re.search(r"\b\d{9,11}\b", cnh_number)
    if number_match:
        cnh_number = number_match.group(0)
    else:
        # Fallback for OCR layouts where the registration label is displaced.
        candidates = re.findall(r"(?<!\d)\d{11}(?!\d)", upper)
        cpf_digits = re.sub(r"\D", "", _cpf(upper))
        candidates = [value for value in candidates if value != cpf_digits]
        cnh_number = candidates[0] if len(candidates) == 1 else ""

    category = _field_value(
        upper,
        [r"CAT\.?\s*HAB\.?", r"CATEGORIA"],
        [r"N[º°O]\s*REGISTRO", r"VALIDADE", r"1[ªA]\s*HABILITA[CÇ][AÃ]O"],
        max_len=80,
    )
    # No leiaute de colunas, a linha de valores contém CPF, registro e categoria.
    category = re.split(
        r"\b(?:NACIONALIDADE|FILIA[CÇ][AÃ]O|DOC\.?\s*IDENTIDADE)\b",
        category,
        maxsplit=1,
    )[0]
    category_match = re.search(
        r"\b\d{9,11}\b\s*[|:; ]*(ACC|A[BCDE]?|[BCDE])\b", category,
    ) or re.search(r"\b(ACC|[A-E]{1,2})\b", category)
    if category_match:
        category = category_match.group(1)
    else:
        category = ""

    identity = _field_value(
        upper,
        [r"DOC\.?\s*IDENTIDADE", r"IDENTIDADE"],
        [r"CPF", r"DATA\s+NASCIMENTO", r"FILIA[CÇ][AÃ]O"],
        max_len=70,
    )
    identity = re.sub(r"^\s*/?\s*ORG\.?\s*EMISSOR\s*/?\s*UF\s*", "", identity, flags=re.IGNORECASE)
    identity = re.sub(r"^\s*/\s*", "", identity)
    identity_match = re.search(r"\b\d[\d .-]{4,19}\b", identity)
    identity = _clean(identity_match.group(0)) if identity_match else _clean(re.split(r"\s*/\s*", identity)[0])

    identity_block = re.search(
        r"DOC\.?\s*IDENTIDADE\s*/?\s*ORG\.?\s*EMISSOR\s*/?\s*UF",
        upper,
        re.IGNORECASE,
    )
    if identity_block:
        identity_tail = upper[identity_block.end():identity_block.end() + 180]
        identity_tail = re.split(
            r"\b(?:CPF|DATA\s+NASCIMENTO|FILIA[CÇ][AÃ]O|NACIONALIDADE|VALIDADE|OBSERVA[CÇ][OÕ]ES)\b",
            identity_tail,
            maxsplit=1,
        )[0]
        identity_match = re.search(r"(?<!\d)\d[\d .-]{4,19}(?!\d)", identity_tail)
        if identity_match:
            identity = _clean(identity_match.group(0))
            identity_remainder = identity_tail[identity_match.end():]
            identity_remainder = re.sub(
                r"/?\s*ORG\.?\s*EMISSOR\s*/?\s*UF\s*",
                " ",
                identity_remainder,
                flags=re.IGNORECASE,
            )
            tokens = re.findall(r"\b[A-Z]{2,}\b", identity_remainder)
            if len(tokens) >= 2 and tokens[1] in {
                "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
                "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
                "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
            }:
                issuing_state = tokens[1]
                issuing_authority = tokens[0]
            elif tokens:
                issuing_authority = tokens[0]
                issuing_state = ""
            else:
                issuing_authority = ""
                issuing_state = ""
        else:
            issuing_authority = ""
            issuing_state = ""
    else:
        issuing_authority = ""
        issuing_state = ""

    nationality = _field_value(
        upper,
        [r"NACIONALIDADE"],
        [r"FILIA[CÇ][AÃ]O", r"VALIDADE", r"CAT\.?\s*HAB\.?", r"CATEGORIA"],
        max_len=60,
    )
    # Quando o OCR mistura o texto da MRZ com os campos, prioriza o valor
    # explícito da CNH em vez de devolver ruído como "NAN UL BA...".
    nationality_match = re.search(r"\b(BRASILEIR[OA](?:\s*\([A-Z]\))?)(?![A-Z])", upper)
    if nationality_match:
        nationality = nationality_match.group(1).replace(" ", "")
    parents = []
    filiation_match = re.search(r"FILIA[CÇ][AÃ]O", upper, re.IGNORECASE)
    if filiation_match:
        filiation_tail = upper[filiation_match.end():filiation_match.end() + 240]
        stop = re.search(
            r"\b(?:PERMISS[AÃ]O|ACC|CAT\.?\s*HAB\.?|VALIDADE|REGISTRO|"
            r"OBSERVA[CÇ][OÕ]ES|NACIONALIDADE|LOCAL|DATA\s+(?:DA\s+)?EMISS[AÃ]O|I<)\b",
            filiation_tail,
            re.IGNORECASE,
        )
        if stop:
            filiation_tail = filiation_tail[:stop.start()]
        parents = [
            _clean(line)
            for line in filiation_tail.splitlines()
            if _clean(line)
            and not re.fullmatch(r"[-:/ ]+", _clean(line))
            and not re.search(
                r"\b(?:FILIA[CÇ][AÃ]O|FILIATION|FILIACIÓN|PAI|M[AÃ]E|NACIONALIDADE|"
                r"BRASILEIR[OA]|LOCAL|VALIDADE|CATEGORIA|REGISTRO|OBSERVA[CÇ][OÕ]ES)\b",
                _clean(line),
                re.IGNORECASE,
            )
            and re.fullmatch(r"[A-ZÀ-ÖØ-Þ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ'’.-]+){1,7}", _clean(line))
        ]
        if len(parents) < 2:
            inline_filiation = _clean(filiation_tail)
            inline_filiation = re.sub(
                r"\b(?:FILIA[CÇ][AÃ]O|FILIATION|FILIACIÓN|PAI|M[AÃ]E)\b",
                " ",
                inline_filiation,
                flags=re.IGNORECASE,
            )
            # Em OCR de colunas, dois nomes podem aparecer separados por barras
            # ou múltiplos espaços na mesma linha.
            parts = [
                _clean(part)
                for part in re.split(r"\s{2,}|\\s*/\\s*", inline_filiation)
                if re.fullmatch(r"[A-ZÀ-ÖØ-Þ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ'’.-]+){1,7}", _clean(part))
            ]
            if len(parts) >= 2:
                parents = parts[:2]
    father = _clean(parents[0]) if parents else ""
    mother = _clean(parents[1]) if len(parents) > 1 else ""

    if not father or not mother or not re.fullmatch(
        r"BRASILEIR[OA](?:\([A-Z]\))?", nationality,
    ):
        field_text = _cnh_field_text(raw).upper()
        if field_text:
            clean_nationality = re.search(
                r"\b(BRASILEIR[OA](?:\s*\([A-Z]\))?)(?![A-Z])", field_text,
            )
            if clean_nationality and not re.fullmatch(
                r"BRASILEIR[OA](?:\([A-Z]\))?", nationality,
            ):
                nationality = clean_nationality.group(1).replace(" ", "")
            clean_filiation = re.search(
                r"FILIA[CÇ][AÃ]O\s*\n(.*)", field_text, re.DOTALL,
            )
            if clean_filiation:
                parent_block = re.split(
                    r"\b(?:ASSINATURA|OBSERVA[CÇ][OÕ]ES|LOCAL|VALIDADE|"
                    r"NACIONALIDADE|CAT\.?\s*HAB\.?|REGISTRO)\b",
                    clean_filiation.group(1), maxsplit=1,
                )[0]
                clean_parents = [
                    _clean(line).strip(" |")
                    for line in parent_block.splitlines()
                    if re.fullmatch(
                        r"[A-ZÀ-ÖØ-Þ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ'’.-]+)+",
                        _clean(line).strip(" |"),
                    )
                ]
                # Só associa pai/mãe quando os dois nomes estão disponíveis.
                if len(clean_parents) == 2:
                    father = father or clean_parents[0]
                    mother = mother or clean_parents[1]

    location = _field_value(
        upper,
        [
            r"LOCAL\s+DE\s+EMISS[AÃ]O",
            r"LOCAL\s+DA\s+EMISS[AÃ]O",
            r"LOCAL\s+DE\s+EXPEDI[CÇ][AÃ]O",
            r"(?m)^\s*LOCAL\s*$",
            r"(?m)^\s*LOCAL\s+(?!(?:DE\s+NASCIMENTO|E\s+UF))",
        ],
        [r"DATA\s+(?:DA\s+)?EMISS[AÃ]O", r"OBSERVA[CÇ][OÕ]ES", r"I<", r"^\d{6}\d[MF<]"],
        max_len=70,
    )

    mrz_birth_date, mrz_expiration = _mrz_dates(upper)
    birth_date = _date_field(upper, [r"DATA\s+NASCIMENTO", r"NASCIMENTO"]) or mrz_birth_date
    expiration_date = mrz_expiration or _date_field(upper, [r"VALIDADE"])
    issue_date = _date_field(upper, [r"DATA\s+(?:DA\s+)?EMISS[AÃ]O", r"EMISS[AÃ]O"])
    first_issue_date = _date_field(
        upper,
        [r"1[ªº°A]\s*HABILITA[CÇ][AÃ]O", r"PRIMEIRA\s+HABILITA[CÇ][AÃ]O"],
    )

    data = {
        "name": name,
        "cpf": _cpf(upper),
        "identity_document": identity,
        "issuing_authority": issuing_authority or _field_value(upper, [r"ORG\.?\s*EMISSOR", r"ÓRG[ÃA]O\s+EMISSOR"], [r"UF", r"CPF", r"DATA\s+NASCIMENTO"], 50),
        "issuing_state": issuing_state or _field_value(upper, [r"UF"], [r"CPF", r"DATA\s+NASCIMENTO", r"FILIA[CÇ][AÃ]O"], 12),
        "birth_date": birth_date,
        "birth_date_display": _br_date(birth_date),
        "cnh_number": cnh_number,
        "cnh_category": category,
        "cnh_expiration": expiration_date,
        "cnh_expiration_display": _br_date(expiration_date),
        "cnh_issue_date": issue_date,
        "cnh_issue_date_display": _br_date(issue_date),
        "cnh_first_issue_date": first_issue_date,
        "cnh_first_issue_date_display": _br_date(first_issue_date),
        "nationality": nationality,
        "father_name": father,
        "mother_name": mother,
        "location": location,
        "text_extracted": text,
        "text_extraction_succeeded": bool(name or _cpf(upper) or cnh_number or category or _date_field(upper, [r"DATA\s+NASCIMENTO", r"NASCIMENTO"]) or _date_field(upper, [r"VALIDADE"])),
    }
    return data
