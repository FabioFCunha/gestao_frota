# -*- coding: utf-8 -*-
"""Extração tolerante de dados de CRLV-e.

O CRLV-e pode chegar como PDF com texto estruturado, PDF cujo texto foi
linearizado em uma ordem diferente da visual ou como imagem. Por isso a
extração usa camadas: texto do PDF, OCR quando necessário e heurísticas
específicas para o leiaute oficial.
"""

import io
import re


def normalize_plate(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_renavam(value):
    return re.sub(r"\D", "", value or "")


def normalize_chassi(value):
    if not value:
        return ""
    value = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if len(value) != 17:
        return ""
    return value.replace("O", "0").replace("Q", "0").replace("I", "1")


def _clean_text(value):
    value = str(value or "").replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _all_text(raw, name):
    text = ""
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            text = ""

    if not text.strip():
        try:
            import pytesseract
            from PIL import Image
            if name.endswith(".pdf"):
                from pdf2image import convert_from_bytes
                pages = convert_from_bytes(raw, dpi=250)
                text = "\n".join(pytesseract.image_to_string(page, lang="por") for page in pages)
            else:
                text = pytesseract.image_to_string(Image.open(io.BytesIO(raw)), lang="por")
        except Exception:
            text = ""

    return text


def _find_years(text):
    return [int(x) for x in re.findall(r"\b(20\d{2})\b", text)]


def _cpf_valid(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    try:
        d = [int(x) for x in digits]
        d1 = (sum(d[i] * (10 - i) for i in range(9)) * 10 % 11) % 10
        d2 = (sum(d[i] * (11 - i) for i in range(10)) * 10 % 11) % 10
        return d[-2] == d1 and d[-1] == d2
    except Exception:
        return False


def extract_chassi(text):
    """Extrai VIN/CHASSI mesmo quando o PDF separa rótulos e valores."""
    upper = text.upper()
    contextual = r"(?:CHASSI|VIN|IDENTIFICA[CÇ][AÃ]O DO VE[IÍ]CULO|N[º°O]\s*CHASSI)"
    for match in re.finditer(contextual, upper):
        window = upper[match.end():match.end() + 1200]
        candidates = re.findall(r"\b([A-HJ-NPR-Z0-9][A-HJ-NPR-Z0-9 ._-]{15,24}[A-HJ-NPR-Z0-9])\b", window)
        for candidate in candidates:
            normalized = normalize_chassi(candidate)
            if normalized and any(ch.isdigit() for ch in normalized):
                return normalized

    # CRLV-e padrão contém um único VIN de 17 posições. O fallback global
    # exige formato de VIN para evitar capturar hashes/assinaturas.
    for candidate in re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", upper):
        normalized = normalize_chassi(candidate)
        if normalized and any(ch.isdigit() for ch in normalized):
            return normalized
    return ""


def _plate_candidates(text):
    upper = text.upper()
    patterns = [
        r"\b[A-Z]{3}[0-9][A-Z0-9][0-9]{2}\b",
        r"\b[A-Z]{3}[ -]?[0-9][A-Z0-9][ -]?[0-9]{2}\b",
    ]
    found = []
    for pattern in patterns:
        for value in re.findall(pattern, upper):
            value = normalize_plate(value)
            if len(value) == 7 and value not in found:
                found.append(value)
    return found


def _extract_renavam(text):
    upper = text.upper()
    contextual = re.findall(r"RENAVAM\D{0,80}([0-9][0-9 .-]{9,14})", upper)
    for value in contextual:
        digits = normalize_renavam(value)
        if len(digits) == 11 and not _cpf_valid(digits):
            return digits, [digits]

    candidates = []
    for value in re.findall(r"\b\d{11}\b", upper):
        if value not in candidates and not _cpf_valid(value):
            candidates.append(value)

    # PDFs linearizados frequentemente colocam o valor do RENAVAM longe
    # do rótulo. Mantemos todos os candidatos para conferência e escolhemos
    # o último não-CPF, que cobre o leiaute usado pela frota atual.
    return (candidates[-1] if candidates else ""), candidates


def _extract_labeled_or_known(text, label, known):
    upper = text.upper()
    match = re.search(label + r"\s*[:.-]?\s*([^\n]{2,100})", upper)
    if match:
        value = _clean_text(match.group(1))
        if value:
            return value
    for item in known:
        if item in upper:
            return item
    return ""


def _extract_vehicle_description(text):
    upper = text.upper()
    match = re.search(r"\b([A-Z]{1,4})\s*/\s*([A-Z0-9][A-Z0-9 ._-]{2,80})", upper)
    if not match:
        return "", "", ""
    brand_code = match.group(1).strip()
    description = _clean_text(match.group(2))
    # Para não consumir o próximo campo do documento, limita a descrição à
    # primeira linha/padrão plausível.
    description = re.split(r"\s+(?:ESP[ÉE]CIE|PASSAGEIRO|CARGA|ESPECIAL)\b", description)[0].strip()
    parts = description.split()
    model = " ".join(parts[:1]) if parts else ""
    version = " ".join(parts[1:]) if len(parts) > 1 else ""
    return brand_code, model, version


def extract_crlv_data(file_obj):
    name = (getattr(file_obj, "name", "") or "").lower()
    raw = file_obj.read()
    file_obj.seek(0)
    text = _all_text(raw, name)
    upper = text.upper()
    compact = re.sub(r"\s+", " ", upper).strip()

    plates = _plate_candidates(upper)
    plate = plates[0] if plates else ""

    renavam, renavam_candidates = _extract_renavam(upper)

    years = _find_years(upper)
    exercise = None
    # Em CRLV-e o exercício aparece junto da placa; esse padrão tem prioridade.
    if plate:
        m = re.search(r"\b" + re.escape(plate) + r"\s+(20\d{2})\b", compact)
        if m:
            exercise = int(m.group(1))
    if exercise is None:
        m = re.search(r"(?:EXERC[ÍI]CIO|LICENCIAMENTO)\D{0,1200}(20\d{2})", upper)
        if m:
            exercise = int(m.group(1))
    if exercise is None and years:
        # O exercício é normalmente o maior ano do bloco de identificação,
        # enquanto fabricação/modelo podem ser iguais ou anteriores.
        exercise = max(years)

    chassi = extract_chassi(upper)

    def first(patterns):
        for pattern in patterns:
            m = re.search(pattern, upper)
            if m:
                return _clean_text(m.group(1))
        return ""

    manufacture_year = None
    model_year = None
    m = re.search(r"ANO FABRICA[CÇ][AÃ]O\D{0,500}(20\d{2})", upper)
    if m:
        manufacture_year = int(m.group(1))
    m = re.search(r"ANO MODELO\D{0,500}(20\d{2})", upper)
    if m:
        model_year = int(m.group(1))

    if manufacture_year is None and len(years) >= 2:
        manufacture_year = years[0]
    if model_year is None and len(years) >= 2:
        model_year = years[1]

    brand_code, model_raw, version = _extract_vehicle_description(upper)

    colors = ["BRANCA", "PRETA", "PRATA", "CINZA", "VERMELHA", "AZUL", "VERDE", "AMARELA", "MARROM", "BEGE", "DOURADA"]
    fuels = ["ALCOOL/GASOLINA", "GASOLINA/ALCOOL/ELETRICO", "GASOLINA", "ALCOOL", "DIESEL", "ELETRICO", "FLEX", "GNV"]
    categories = ["PARTICULAR", "ALUGUEL", "OFICIAL", "APRENDIZAGEM", "EXPERIENCIA"]
    color = _extract_labeled_or_known(upper, r"COR PREDOMINANTE", colors)
    fuel = _extract_labeled_or_known(upper, r"COMBUST[IÍ]VEL", fuels)
    category = _extract_labeled_or_known(upper, r"CATEGORIA", categories)

    vehicle_type = first([
        r"ESP[ÉE]CIE\s*/\s*TIPO\s*[:.-]?\s*([^\n]{3,80})",
    ])
    if not vehicle_type:
        for value in ["PASSAGEIRO AUTOMOVEL", "CARGA CAMINHONETE", "ESPECIAL CAMINHAO", "MISTO UTILITARIO"]:
            if value in upper:
                vehicle_type = value
                break

    crv = first([
        r"N[ÚU]MERO DO CRV\s*[:.-]?\s*(\d{10,14})",
        r"N[ÚU]MERO CRV\s*[:.-]?\s*(\d{10,14})",
    ])
    if not crv:
        twelve = re.findall(r"\b\d{12}\b", upper)
        if twelve:
            crv = twelve[0]

    security_cla = first([r"C[ÓO]DIGO DE SEGURAN[CÇ]A DO CLA\s*[:.-]?\s*(\d{11})"])
    if not security_cla:
        security_candidates = [x for x in re.findall(r"\b\d{11}\b", upper) if x != renavam and not _cpf_valid(x)]
        if security_candidates:
            security_cla = security_candidates[-1]

    power_cc = first([r"POT[ÊE]NCIA/CILINDRADA\s*[:.-]?\s*([^\n]{3,40})"])
    gross_weight = first([r"PESO BRUTO TOTAL\s*[:.-]?\s*([^\n]{1,20})"])
    capacity = first([r"CAPACIDADE\s*[:.-]?\s*([^\n]{1,20})"])
    motor = first([r"MOTOR\s*[:.-]?\s*([A-Z0-9*.-]{4,30})"])
    cmt = first([r"\bCMT\s*[:.-]?\s*([^\n]{1,20})"])
    axles = first([r"\bEIXOS\s*[:.-]?\s*([0-9*]{1,3})"])
    seating = first([r"\bLOTA[CÇ][AÃ]O\s*[:.-]?\s*([0-9]{1,2}P?)"])
    body = first([r"CARROCERIA\s*[:.-]?\s*([^\n]{2,60})"])

    cnpj = first([r"CPF\s*/\s*CNPJ\s*[:.-]?\s*([0-9./-]{11,20})"])
    owner = ""
    if cnpj:
        pos = upper.find(cnpj)
        before = upper[max(0, pos - 160):pos]
        lines = [x.strip() for x in re.split(r"\n+", before) if x.strip()]
        if lines:
            owner = lines[-1]
            owner = re.sub(r"^(?:NOME|LOCAL|DATA)\s*", "", owner).strip()
    if not owner:
        m = re.search(r"NOME\s+([A-Z][A-Z .&'-]{3,100})\s+CPF", upper)
        if m:
            owner = _clean_text(m.group(1))

    local = ""
    issue_date = ""
    m = re.search(r"\b([A-ZÀ-Ú ]{3,50}\s+[A-Z]{2})\s+(\d{2}/\d{2}/\d{4})\b", upper)
    if m:
        local, issue_date = _clean_text(m.group(1)), m.group(2)

    observation = ""
    for marker in ["BENEF. TRIBUTARIO", "ALIENAÇÃO FIDUCIÁRIA", "ALIENACAO FIDUCIARIA", "SEM OBSERVAÇÕES", "SEM OBSERVACOES"]:
        if marker in upper:
            pos = upper.find(marker)
            observation = _clean_text(upper[pos:pos + 180])
            break

    extracted = {
        "plate": plate,
        "plate_candidates": plates,
        "renavam": normalize_renavam(renavam),
        "renavam_candidates": renavam_candidates,
        "chassi": chassi,
        "exercise": exercise,
        "manufacture_year": manufacture_year,
        "model_year": model_year,
        "brand_raw": brand_code,
        "model_raw": model_raw,
        "version": version,
        "color": color,
        "fuel": fuel,
        "category": category,
        "vehicle_type": vehicle_type,
        "crv_number": crv,
        "security_code_cla": security_cla,
        "capacity": capacity,
        "power_cylinder": power_cc,
        "gross_weight": gross_weight,
        "motor": motor,
        "cmt": cmt,
        "axles": axles,
        "seating": seating,
        "bodywork": body,
        "owner_name": owner,
        "owner_document": cnpj,
        "location": local,
        "issue_date": issue_date,
        "observation": observation,
        "text_extracted": bool(text.strip()),
        "raw_text": text,
    }
    return extracted
