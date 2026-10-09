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
            r"\\b(?:NOME|CPF|REGISTRO|VALIDADE|NASCIMENTO|CATEGORIA|CAT\\.?\\s*HAB)\\b",
            text,
            re.IGNORECASE,
        )) >= 3
        and re.search(
            r"\\d{2}[./-]\\d{2}[./-]\\d{4}|"
            r"\\d{3}\\.?\\d{3}\\.?\\d{3}-?\\d{2}|\\b\\d{9,11}\\b",
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
def _iso_date(value):
    value = _clean(value)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except (TypeError, ValueError):
            continue
    return ""


def _date_field(text, labels):
    for label in labels:
        match = re.search(
            label + r"\s*(?:[:\-]|\n)?\s*(\d{2}[./-]\d{2}[./-]\d{4}|\d{4}-\d{2}-\d{2})",
            text,
            re.IGNORECASE,
        )
        if match:
            normalized = match.group(1).replace(".", "/")
            return _iso_date(normalized)
    return ""


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


def _cpf(text):
    match = re.search(
        r"\bCPF\b\D{0,50}(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b",
        text,
        re.IGNORECASE,
    )
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

    name = _field_value(
        upper,
        [r"NOME\s+E\s+SOBRENOME", r"NOME\s+COMPLETO", r"NOME"],
        stops,
        max_len=100,
    )
    # O leiaute em texto corrido pode trazer o nome na linha seguinte ao rótulo.
    if not name:
        lines = [_clean(line) for line in upper.splitlines() if _clean(line)]
        for i, line in enumerate(lines[:-1]):
            if re.fullmatch(r"NOME(?:\s+E\s+SOBRENOME|\s+COMPLETO)?", line):
                candidate = lines[i + 1]
                if candidate and not re.search(r"\b(CPF|REGISTRO|VALIDADE|NASCIMENTO|CAT\.?)\b", candidate):
                    name = candidate
                    break

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
        cnh_number = ""

    category = _field_value(
        upper,
        [r"CAT\.?\s*HAB\.?", r"CATEGORIA"],
        [r"N[º°O]\s*REGISTRO", r"VALIDADE", r"1[ªA]\s*HABILITA[CÇ][AÃ]O"],
        max_len=20,
    )
    category_match = re.search(r"\b(ACC|[A-E]{1,2})\b", category)
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
        r"DOC\.?\s*IDENTIDADE\s*/\s*ORG\.?\s*EMISSOR\s*/\s*UF\s*([^\n]+)",
        upper,
        re.IGNORECASE,
    )
    if identity_block:
        identity_parts = _clean(identity_block.group(1)).split()
        if identity_parts:
            identity = identity_parts[0]
            if len(identity_parts) >= 2:
                # O nome do órgão pode ser composto; usamos o estado final
                # de duas letras quando o leiaute traz todos os valores na mesma linha.
                if re.fullmatch(r"[A-Z]{2}", identity_parts[-1]):
                    issuing_state = identity_parts[-1]
                    issuing_authority = " ".join(identity_parts[1:-1])
                else:
                    issuing_authority = " ".join(identity_parts[1:])
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
        upper, [r"NACIONALIDADE"], [r"FILIA[CÇ][AÃ]O", r"VALIDADE", r"CAT\.?\s*HAB\.?"], max_len=60
    )
    filiation_lines = [_clean(line) for line in upper.splitlines()]
    parents = []
    for index, line in enumerate(filiation_lines):
        if re.search(r"FILIA[CÇ][AÃ]O", line):
            for candidate in filiation_lines[index + 1:index + 4]:
                if not candidate:
                    continue
                if re.search(r"\b(PERMISS[AÃ]O|ACC|CAT\.?\s*HAB\.?|VALIDADE|REGISTRO|OBSERVA[CÇ][OÕ]ES)\b", candidate):
                    break
                parents.append(candidate)
            break
    if not parents:
        filiation = _field_value(
            upper, [r"FILIA[CÇ][AÃ]O"], [r"PERMISS[AÃ]O", r"ACC", r"CAT\.?\s*HAB\.?", r"OBSERVA[CÇ][OÕ]ES"], max_len=180
        )
        parents = [part for part in re.split(r"\s{2,}", filiation) if _clean(part)]
    father = _clean(parents[0]) if parents else ""
    mother = _clean(parents[1]) if len(parents) > 1 else ""

    location = _field_value(
        upper, [r"LOCAL"], [r"DATA\s+(?:DA\s+)?EMISS[AÃ]O", r"OBSERVA[CÇ][OÕ]ES"], max_len=70
    )

    data = {
        "name": name,
        "cpf": _cpf(upper),
        "identity_document": identity,
        "issuing_authority": issuing_authority or _field_value(upper, [r"ORG\.?\s*EMISSOR", r"ÓRG[ÃA]O\s+EMISSOR"], [r"UF", r"CPF", r"DATA\s+NASCIMENTO"], 50),
        "issuing_state": issuing_state or _field_value(upper, [r"UF"], [r"CPF", r"DATA\s+NASCIMENTO", r"FILIA[CÇ][AÃ]O"], 12),
        "birth_date": _date_field(upper, [r"DATA\s+NASCIMENTO", r"NASCIMENTO"]),
        "cnh_number": cnh_number,
        "cnh_category": category,
        "cnh_expiration": _date_field(upper, [r"VALIDADE"]),
        "cnh_issue_date": _date_field(upper, [r"DATA\s+(?:DA\s+)?EMISS[AÃ]O", r"EMISS[AÃ]O"]),
        "cnh_first_issue_date": _date_field(upper, [r"1[ªA]\s*HABILITA[CÇ][AÃ]O", r"PRIMEIRA\s+HABILITA[CÇ][AÃ]O"]),
        "nationality": nationality,
        "father_name": father,
        "mother_name": mother,
        "location": location,
        "text_extracted": text,
        "text_extraction_succeeded": bool(text.strip()),
    }
    return data
