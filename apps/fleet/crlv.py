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


def _vin_check_digit(value):
    """Retorna o dígito de controle VIN segundo a ISO 3779."""
    transliteration = {
        **{str(i): i for i in range(10)},
        "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
        "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
        "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    }
    weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 8, 7, 6, 5, 4, 3, 2]
    try:
        total = sum(transliteration[ch] * weight for ch, weight in zip(value, weights))
    except KeyError:
        return ""
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def _vin_is_valid(value):
    value = normalize_chassi(value)
    if not value:
        return False
    return value[8] == _vin_check_digit(value)


def _clean_text(value):
    value = str(value or "").replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _extract_between_labels(text, label, next_labels=(), *, max_len=200):
    """Extrai o conteúdo de um campo mesmo quando o PDF lineariza as colunas."""
    upper = text.upper()
    match = re.search(label + r"\s*[:.-]?\s*", upper)
    if not match:
        return ""
    start = match.end()
    end = min(len(upper), start + max_len)
    if next_labels:
        next_match = re.search(
            r"(?:" + "|".join(next_labels) + r")\s*[:.-]?\s*",
            upper[start:end],
        )
        if next_match:
            end = start + next_match.start()
    return _clean_text(upper[start:end]).strip(" :.-")


def _first_token(value):
    value = _clean_text(value)
    if not value:
        return ""
    return value.split()[0]




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
    """Extrai o VIN priorizando candidatos válidos no contexto de CHASSI."""
    upper = text.upper()
    contextual = r"(?:CHASSI|VIN|IDENTIFICA[CÇ][AÃ]O DO VE[IÍ]CULO|N[º°O]\s*CHASSI)"
    for match in re.finditer(contextual, upper):
        # PDFs/OCR de CRLV-e podem linearizar as colunas: o rótulo CHASSI
        # aparece antes de vários valores. Por isso ampliamos a janela, mas
        # nunca aceitamos cegamente o primeiro bloco de 17 caracteres.
        window = upper[match.end():match.end() + 5000]
        candidates = re.findall(r"\b([A-Z0-9][A-Z0-9 ._-]{15,24}[A-Z0-9])\b", window)

        normalized_candidates = []
        for candidate in candidates:
            normalized = normalize_chassi(candidate)
            if normalized and any(ch.isdigit() for ch in normalized):
                if normalized not in normalized_candidates:
                    normalized_candidates.append(normalized)

        # Um VIN válido pelo dígito de controle tem prioridade absoluta.
        for candidate in normalized_candidates:
            if _vin_is_valid(candidate):
                return candidate

        # Se o documento não permitir validar o dígito de controle (por
        # exemplo, OCR com erro), mantemos o primeiro candidato contextual
        # como fallback. Não existe fallback global sem CHASSI/VIN.
        if normalized_candidates:
            return normalized_candidates[0]

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

    # No CRLV-e linearizado, o RENAVAM aparece imediatamente antes da
    # placa no bloco de identificação. Isso evita confundi-lo com o CRV.
    plates = re.findall(r"\b[A-Z]{3}[0-9][A-Z0-9][0-9]{2}\b", upper)
    for plate in plates:
        match = re.search(
            r"\b(\d{11})\s+" + re.escape(plate) +
            r"\s+20\d{2}\s+20\d{2}\s+20\d{2}\b",
            upper,
        )
        if match:
            return match.group(1), [match.group(1)]
    contextual = re.findall(r"RENAVAM\D{0,500}([0-9][0-9 .-]{9,14})", upper)
    contextual_digits = []
    for value in contextual:
        digits = normalize_renavam(value)
        if len(digits) == 11 and not _cpf_valid(digits) and digits not in contextual_digits:
            contextual_digits.append(digits)

    candidates = []
    for value in re.findall(r"\b\d{11}\b", upper):
        if value not in candidates and not _cpf_valid(value):
            candidates.append(value)

    # PDFs linearizados frequentemente colocam o valor do RENAVAM longe
    # do rótulo e podem expor outro código de 11 dígitos no mesmo bloco.
    # Mantemos todos os candidatos para conferência e escolhemos o último
    # não-CPF, cobrindo o leiaute usado pela frota atual.
    merged = []
    for value in contextual_digits + candidates:
        if value not in merged:
            merged.append(value)
    return (merged[-1] if merged else ""), merged


def _extract_labeled_or_known(text, label, known):
    upper = text.upper()
    match = re.search(label + r"\s*[:.-]?\s*([^\n]{2,100})", upper)
    if match:
        value = _clean_text(match.group(1))
        for item in known:
            if item in value:
                return item
        if value:
            return value
    for item in known:
        if item in upper:
            return item
    return ""


def _extract_vehicle_description(text):
    section = _extract_between_labels(
        text,
        r"MARCA\s*/\s*MODELO\s*/\s*VERS[AÃ]O",
        [r"PLACA\s+ANTERIOR\s*/\s*UF", r"CHASSI", r"COR\s+PREDOMINANTE"],
        max_len=180,
    )
    if not section:
        return "", "", ""

    match = re.match(r"([A-Z]{1,6})\s*/\s*(.+)", section)
    if not match:
        return "", "", ""

    brand_code = match.group(1).strip()
    description = _clean_text(match.group(2))
    parts = description.split()
    model = parts[0] if parts else ""
    version = " ".join(parts[1:]) if len(parts) > 1 else ""
    return brand_code, model, version



def _extract_linearized_layout_values(compact):
    """Recupera valores quando o extrator PDF separa os rótulos dos valores.

    Alguns CRLV-e geram um texto linearizado em que todos os rótulos aparecem
    primeiro e os valores correspondentes somente depois. Nesse formato,
    extrair apenas o texto entre dois rótulos captura os próprios rótulos em
    vez dos dados. As expressões abaixo usam os padrões semânticos e os
    valores fortemente identificáveis do leiaute oficial.
    """
    data = {}

    # MARCA/MODELO/VERSÃO: ex. CHEV/ONIX 10TMT HB, VW/17.210 CRM 4X2.
    vehicle_match = re.search(
        r"\b([A-Z]{2,8})/([A-Z0-9][A-Z0-9.-]{1,24})(?:\s+([A-Z0-9][A-Z0-9./-]*(?:\s+[A-Z0-9][A-Z0-9./-]*){0,4}))?"
        r"\s+(?=(?:PASSAGEIRO|ESPECIAL|CARGA|MISTO|UTILITARIO|UTILITÁRIO|MOTOCICLETA|CICLOMOTOR|TRATOR|REBOQUE|SEMI-REBOQUE))",
        compact,
    )
    if vehicle_match:
        data["brand_raw"] = vehicle_match.group(1)
        data["model_raw"] = vehicle_match.group(2)
        data["version"] = _clean_text(vehicle_match.group(3) or "")

    known_vehicle_types = (
        "PASSAGEIRO AUTOMOVEL", "PASSAGEIRO AUTOMÓVEL", "ESPECIAL CAMINHONETE",
        "ESPECIAL CAMINHAO", "ESPECIAL CAMINHÃO", "CARGA CAMINHAO",
        "CARGA CAMINHÃO", "CARGA CAMINHONETE", "MISTO", "MOTOCICLETA",
        "CICLOMOTOR", "REBOQUE", "SEMI-REBOQUE",
    )
    for value in known_vehicle_types:
        if value in compact:
            data["vehicle_type"] = value
            break

    known_colors = (
        "BRANCA", "PRETA", "PRATA", "CINZA", "VERMELHA", "AZUL",
        "VERDE", "AMARELA", "MARROM", "BEGE", "DOURADA",
    )
    for value in known_colors:
        if re.search(r"\b" + re.escape(value) + r"\b", compact):
            data["color"] = value
            break

    known_fuels = (
        "GASOLINA/ALCOOL/ELETRICO", "GASOLINA/ÁLCOOL/ELÉTRICO",
        "ALCOOL/GASOLINA", "ÁLCOOL/GASOLINA", "GASOLINA",
        "ALCOOL", "ÁLCOOL", "DIESEL", "ELETRICO", "ELÉTRICO", "FLEX", "GNV",
    )
    for value in known_fuels:
        if value in compact:
            data["fuel"] = value
            break

    known_categories = ("PARTICULAR", "ALUGUEL", "OFICIAL", "APRENDIZAGEM", "EXPERIENCIA", "EXPERIÊNCIA")
    for value in known_categories:
        if re.search(r"\b" + re.escape(value) + r"\b", compact):
            data["category"] = value
            break

    power_match = re.search(r"\b(\d{2,3}CV/\d{3,5})\b\s+(\d+(?:\.\d+)?)", compact)
    if power_match:
        data["power_cylinder"] = power_match.group(1)
        data["gross_weight"] = power_match.group(2)

    motor_match = re.search(r"\b(L[A-Z0-9*]{6,24})\b\s+(\d+(?:\.\d+)?)\s+\*?\s+(\d{1,2}P)\b", compact)
    if motor_match:
        data["motor"] = motor_match.group(1).replace("*", "")
        data["cmt"] = motor_match.group(2)
        data["seating"] = motor_match.group(3)

    if "motor" not in data:
        motor_match = re.search(r"\b(L[A-Z0-9*]{6,24})\b", compact)
        if motor_match:
            candidate = motor_match.group(1).replace("*", "")
            if len(candidate) >= 8:
                data["motor"] = candidate

    # No leiaute linearizado, o CMT aparece semanticamente após o
    # identificador do motor e antes da lotação. Nunca aceitar identificadores
    # longos (RENAVAM/CRV) como CMT.
    cmt_semantic = re.search(
        r"\bL[A-Z0-9*]{6,24}\b\s+(\d+(?:\.\d+)?)\s+\*?\s+\d{1,2}P\b",
        compact,
    )
    if cmt_semantic:
        data["cmt"] = cmt_semantic.group(1)
    elif "cmt" not in data:
        cmt_match = re.search(r"\bCMT\b.*?\b(\d+(?:\.\d+)?)\b", compact)
        if cmt_match and len(re.sub(r"\D", "", cmt_match.group(1))) <= 4:
            data["cmt"] = cmt_match.group(1)

    if "axles" not in data:
        axles_match = re.search(
            r"\bEIXOS\b.*?\b(\d{1,2})\b.*?\bLOTA[CÇ][AÃ]O\b.*?\b(\d{1,2}P)\b",
            compact,
        )
        if axles_match:
            data["axles"] = axles_match.group(1)
            data["seating"] = data.get("seating") or axles_match.group(2)

    if "seating" not in data:
        seating_match = re.search(r"\b(\d{1,2}P)\b", compact)
        if seating_match:
            data["seating"] = seating_match.group(1)

    body_values = (
        "NÃO APLICAVEL", "NAO APLICAVEL", "ABERTA/CABINE DUPLA",
        "MEC OPERAC/C ESTENDIDA", "MEC. OPERAC/C ESTENDIDA",
        "MECANISMO OPERACIONAL/CAB. LINEAR",
    )
    for value in body_values:
        if value in compact:
            data["bodywork"] = value
            break

    cnpj_match = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", compact)
    if cnpj_match:
        data["owner_document"] = cnpj_match.group(0)
        before = compact[:cnpj_match.start()].rstrip()
        # O nome do proprietário normalmente é o bloco imediatamente anterior
        # ao CNPJ, após os campos técnicos do CRLV.
        name_match = re.search(
            r"(?:NOME\s+)?([A-ZÀ-Ú][A-ZÀ-Ú0-9 .&/-]{3,100})$",
            before,
        )
        if name_match:
            candidate = _clean_text(name_match.group(1))
            if not any(label in candidate for label in ("CARROCERIA", "MOTOR", "LOTAÇÃO", "CMT", "NÚMERO")):
                data["owner_name"] = candidate

    # Em textos linearizados o local/data continuam sendo um par fortemente
    # identificável.
    local_match = re.search(
        r"\b([A-ZÀ-Ú][A-ZÀ-Ú .'-]{2,45}\s+[A-Z]{2})\s+(\d{2}/\d{2}/\d{4})\b",
        compact,
    )
    if local_match:
        data["location"] = _clean_text(local_match.group(1))
        data["issue_date"] = local_match.group(2)

    obs_match = re.search(
        r"(BENEF\.\s*TRIBUTARIO|BENEF\.\s*TRIBUTÁRIO|ALIENA[CÇ][AÃ]O FIDUCI[AÁ]RIA|SEM OBSERVA[CÇ][OÕ]ES)(.{0,160})",
        compact,
    )
    if obs_match:
        data["observation"] = _clean_text(obs_match.group(0))

    return data

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
    if plate:
        compact_years = re.search(
            r"\b" + re.escape(plate) + r"\s+(20\d{2})\s+(20\d{2})\s+(20\d{2})\b",
            compact,
        )
        if compact_years:
            manufacture_year = int(compact_years.group(2))
            model_year = int(compact_years.group(3))
    m = re.search(r"ANO FABRICA[CÇ][AÃ]O\D{0,500}(20\d{2})", upper)
    if m and manufacture_year is None:
        manufacture_year = int(m.group(1))
    m = re.search(r"ANO MODELO\D{0,500}(20\d{2})", upper)
    if m and model_year is None:
        model_year = int(m.group(1))

    if manufacture_year is None and len(years) >= 2:
        manufacture_year = years[0]
    if model_year is None and len(years) >= 2:
        model_year = years[1]

    brand_code, model_raw, version = _extract_vehicle_description(upper)
    linearized = _extract_linearized_layout_values(compact)
    # Quando o PDF separa rótulos e valores, o parser por janela pode
    # devolver os próprios rótulos. O padrão semântico acima tem prioridade.
    if linearized.get("brand_raw"):
        brand_code = linearized["brand_raw"]
        model_raw = linearized.get("model_raw", model_raw)
        version = linearized.get("version", version)

    colors = ["BRANCA", "PRETA", "PRATA", "CINZA", "VERMELHA", "AZUL", "VERDE", "AMARELA", "MARROM", "BEGE", "DOURADA"]
    fuels = ["ALCOOL/GASOLINA", "GASOLINA/ALCOOL/ELETRICO", "GASOLINA", "ALCOOL", "DIESEL", "ELETRICO", "FLEX", "GNV"]
    categories = ["PARTICULAR", "ALUGUEL", "OFICIAL", "APRENDIZAGEM", "EXPERIENCIA"]

    color = _extract_between_labels(
        upper, r"COR\s+PREDOMINANTE", [r"ESP[ÉE]CIE\s*/\s*TIPO", r"COMBUST[IÍ]VEL"]
    )
    if color not in colors:
        color = next((value for value in colors if value in color or value in upper), "")
    fuel = _extract_between_labels(
        upper, r"COMBUST[IÍ]VEL", [r"C[ÓO]DIGO\s+DE\s+SEGURAN[CÇ]A", r"CATEGORIA"]
    )
    if fuel not in fuels:
        fuel = next((value for value in fuels if value in fuel), "")
    category = _extract_between_labels(
        upper, r"CATEGORIA", [r"CAPACIDADE", r"ESP[ÉE]CIE\s*/\s*TIPO"]
    )
    if category not in categories:
        category = next((value for value in categories if value in category), "")

    vehicle_type = _extract_between_labels(
        upper, r"ESP[ÉE]CIE\s*/\s*TIPO",
        [r"COMBUST[IÍ]VEL", r"PLACA\s+ANTERIOR\s*/\s*UF", r"CHASSI"],
        max_len=100,
    )
    if "PASSAGEIRO AUTOMOVEL" in upper:
        vehicle_type = "PASSAGEIRO AUTOMOVEL"

    # O CRV pode aparecer no cabeçalho linearizado junto com RENAVAM,
    # placa e os anos do veículo. Nesse leiaute, procurar simplesmente
    # o primeiro número depois do rótulo é incorreto.
    #
    # Exemplo:
    # CÓDIGO RENAVAM PLACA EXERCÍCIO ANO FABRICAÇÃO ANO MODELO
    # NÚMERO DO CRV
    # 01455165457 TTO8A04 2025 2025 2026 254508272509 90048500446
    #
    # Primeiro tentamos associar o CRV ao bloco formado pela placa + três
    # anos consecutivos. O número seguinte aos três anos é o CRV.
    crv = ""
    if plate:
        crv_header_pattern = (
            r"\b" + re.escape(plate) +
            r"\s+(20\d{2})\s+(20\d{2})\s+(20\d{2})\s+"
            r"(\d{10,14})\b"
        )
        crv_header_match = re.search(crv_header_pattern, compact)
        if crv_header_match:
            crv = crv_header_match.group(4)

    # Fallback específico para o rótulo NÚMERO DO CRV quando o PDF
    # não preserva o cabeçalho acima.
    if not crv:
        crv_section = _extract_between_labels(
            upper,
            r"N[ÚU]MERO\s+DO\s+CRV",
            [r"MARCA\s*/\s*MODELO\s*/\s*VERS[AÃ]O"],
            max_len=50,
        )
        crv_match = re.search(r"\b\d{10,14}\b", crv_section)
        if crv_match:
            crv = crv_match.group(0)

    # Último fallback: um CRV normalmente possui 12 dígitos.
    # Não usamos o primeiro número de 12 dígitos indiscriminadamente,
    # pois isso pode capturar outro identificador do documento.
    if not crv:
        twelve = re.findall(r"\b\d{12}\b", upper)
        if len(twelve) == 1:
            crv = twelve[0]

    security_cla = _extract_between_labels(
        upper, r"C[ÓO]DIGO\s+DE\s+SEGURAN[CÇ]A\s+DO\s+CLA",
        [r"CAT", r"QR\s*CODE"],
        max_len=40,
    )
    security_match = re.search(r"\b\d{8,12}\b", security_cla)
    security_cla = security_match.group(0) if security_match else ""

    power_cc = _extract_between_labels(
        upper, r"POT[ÊE]NCIA/CILINDRADA",
        [r"PESO\s+BRUTO\s+TOTAL", r"MOTOR"],
        max_len=60,
    )
    gross_weight = _first_token(_extract_between_labels(
        upper, r"PESO\s+BRUTO\s+TOTAL", [r"CMT", r"EIXOS"], max_len=30
    ))
    capacity = _first_token(_extract_between_labels(
        upper, r"CAPACIDADE", [r"POT[ÊE]NCIA/CILINDRADA"], max_len=30
    ))
    motor = _first_token(_extract_between_labels(
        upper, r"MOTOR", [r"CARROCERIA", r"CMT"], max_len=60
    ))
    cmt = _first_token(_extract_between_labels(
        upper, r"\bCMT", [r"EIXOS"], max_len=30
    ))
    axles = _first_token(_extract_between_labels(
        upper, r"\bEIXOS", [r"LOTA[CÇ][AÃ]O"], max_len=20
    ))
    seating = _first_token(_extract_between_labels(
        upper, r"LOTA[CÇ][AÃ]O", [r"CARROCERIA"], max_len=20
    ))
    body = _extract_between_labels(
        upper, r"CARROCERIA",
        [r"NOME", r"LOCAL\s+DATA", r"OBSERVA[CÇ][OÕ]ES"],
        max_len=80,
    )

    cnpj = _extract_between_labels(
        upper, r"CPF\s*/\s*CNPJ", [r"MENSAGENS\s+SENATRAN", r"LOCAL\s+DATA"], max_len=30
    )
    cnpj_match = re.search(r"\d{2}[.\d/-]{8,18}\d", cnpj)
    cnpj = cnpj_match.group(0) if cnpj_match else ""
    owner = _extract_between_labels(
        upper, r"NOME", [r"CPF\s*/\s*CNPJ", r"LOCAL\s+DATA"], max_len=120
    )
    owner = _clean_text(owner)

    local = ""
    issue_date = ""

    # No CRLV digital linearizado, o cabeçalho "LOCAL DATA" pode
    # aparecer imediatamente antes do município. Removemos o rótulo
    # antes de capturar LOCAL + UF.
    local_data_match = re.search(
        r"LOCAL\s+DATA\s+(.{3,80}?)\s+(\d{2}/\d{2}/\d{4})\b",
        upper,
    )
    if local_data_match:
        local = _clean_text(local_data_match.group(1))
        issue_date = local_data_match.group(2)
    else:
        m = re.search(
            r"\b([A-ZÀ-Ú ]{3,50}\s+[A-Z]{2})\s+(\d{2}/\d{2}/\d{4})\b",
            upper,
        )
        if m:
            local, issue_date = _clean_text(m.group(1)), m.group(2)

    # Completa os campos que vieram em branco no texto linearizado.
    color = color or linearized.get("color", "")
    fuel = fuel or linearized.get("fuel", "")
    category = category or linearized.get("category", "")
    vehicle_type = vehicle_type or linearized.get("vehicle_type", "")
    power_cc = power_cc or linearized.get("power_cylinder", "")
    gross_weight = gross_weight or linearized.get("gross_weight", "")
    motor = motor or linearized.get("motor", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", cmt or "") or len(re.sub(r"\D", "", cmt or "")) > 4:
        cmt = linearized.get("cmt", "") or cmt
    else:
        cmt = cmt or linearized.get("cmt", "")
    axles = axles or linearized.get("axles", "")
    seating = seating if seating and seating != "ANO" else linearized.get("seating", "")
    body = body if body and "INFORMAÇÕES DO SEGURO" not in body else linearized.get("bodywork", "")
    cnpj = cnpj or linearized.get("owner_document", "")
    owner = owner if owner and "CÓDIGO" not in owner else linearized.get("owner_name", "")
    local = local or linearized.get("location", "")
    issue_date = issue_date or linearized.get("issue_date", "")

    observation = ""
    for marker in ["BENEF. TRIBUTARIO", "BENEF. TRIBUTÁRIO", "ALIENAÇÃO FIDUCIÁRIA", "ALIENACAO FIDUCIARIA", "SEM OBSERVAÇÕES", "SEM OBSERVACOES"]:
        if marker in upper:
            pos = upper.find(marker)
            observation = _clean_text(upper[pos:pos + 180])
            break
    observation = observation or linearized.get("observation", "")

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
