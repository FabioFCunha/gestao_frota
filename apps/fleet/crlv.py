# -*- coding: utf-8 -*-
import io
import re

def normalize_plate(value): return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
def normalize_renavam(value): return re.sub(r"\D", "", value or "")

def normalize_chassi(value):
    if not value:
        return ""
    value = str(value).upper()
    value = re.sub(r"[^A-Z0-9]", "", value)
    if len(value) != 17:
        return ""
    # VIN cannot contain I, O, Q. We treat them as OCR errors for 1, 0, 0.
    value = value.replace('O', '0').replace('Q', '0').replace('I', '1')
    return value

def extract_chassi(text):
    text_upper = text.upper()
    pattern = r'(?:CHASSI|VIN|IDENTIFICA[CÇ][AÃ]O DO VE[IÍ]CULO|N[º°O]\s*CHASSI)'
    
    for m in re.finditer(pattern, text_upper):
        after_label = text_upper[m.end():m.end()+800]
        
        # 1. Look for a contiguous 17-char alphanumeric string
        match = re.search(r'\b([A-Z0-9]{17})\b', after_label)
        if match:
            return normalize_chassi(match.group(1))
            
        # 2. Look for space-separated chassi (e.g. 9BW ZZZ 377 VT004251)
        match2 = re.search(r'\b([A-Z0-9][A-Z0-9\s.-]{15,25}[A-Z0-9])\b', after_label)
        if match2:
            candidate = re.sub(r"[^A-Z0-9]", "", match2.group(1))
            if len(candidate) == 17 and re.search(r'\d', candidate):
                return normalize_chassi(candidate)
                
    return ""

def extract_crlv_data(file_obj):
    name = (getattr(file_obj, 'name', '') or '').lower()
    raw = file_obj.read()
    file_obj.seek(0)
    text = ''
    if name.endswith('.pdf'):
        try:
            from pypdf import PdfReader
            text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
        except Exception:
            pass
    if not text.strip():
        try:
            import pytesseract
            from PIL import Image
            if name.endswith('.pdf'):
                from pdf2image import convert_from_bytes
                text = '\n'.join(pytesseract.image_to_string(p, lang='por') for p in convert_from_bytes(raw, first_page=1, last_page=1, dpi=250))
            else:
                text = pytesseract.image_to_string(Image.open(io.BytesIO(raw)), lang='por')
        except Exception:
            pass

    text_upper = text.upper()

    plate = re.search(r'\b([A-Z]{3})[\s.-]?([0-9])([A-Z0-9])([0-9]{2})\b', text_upper)
    if not plate:
        plate = re.search(r'\b([A-Z0-9]{3})[\s.-]?([0-9])([A-Z0-9])([0-9]{2})\b', text_upper)

    renavam = re.search(r'RENAVAM\D{0,200}?([0-9. -]{9,16})', text_upper)
    if not renavam:
        renavam_matches = re.findall(r'\b(\d{11})\b', text_upper)
        if renavam_matches:
            # Heurística de fallback: em CRLVs digitais, o OCR pode embaralhar as posições.
            # Como a distância até o rótulo CÓDIGO RENAVAM não é confiável (o OCR joga os valores para o final),
            # pegamos as chaves de 11 dígitos. Precisamos filtrar os CPFs que também têm 11 dígitos e ficam no fim da página.
            def is_cpf(cpf):
                try:
                    d = [int(x) for x in cpf]
                    d1 = (sum(d[i] * (10 - i) for i in range(9)) * 10 % 11) % 10
                    d2 = (sum(d[i] * (11 - i) for i in range(10)) * 10 % 11) % 10
                    return d[-2] == d1 and d[-1] == d2
                except:
                    return False
            
            cands = [r for r in renavam_matches if not is_cpf(r)]
            if cands:
                # Limitação documentada: na ausência de proximidade ao rótulo, e assumindo que o CRV e o RENAVAM são 
                # extraídos, no layout digital o RENAVAM costuma ser lido por último pelo Tesseract/PyPDF na coluna principal.
                # (E evitamos pegar o CPF do proprietário graças ao filtro is_cpf).
                renavam = type('obj', (object,), {'group': lambda self, x: cands[-1]})()

    exercise = None
    plate_str = ''.join(plate.groups()) if plate else ''
    plate_raw = plate.group(0) if plate else ''
    if plate_str:
        regex_plate_year = r'\b' + re.escape(plate_raw) + r'\s+(20\d{2})\b'
        match_plate_year = re.search(regex_plate_year, text_upper)
        if match_plate_year:
            exercise = type('obj', (object,), {'group': lambda self, x: match_plate_year.group(1)})()

    if not exercise:
        exercise = re.search(r'(?:EXERC[ÍI]CIO|LICENCIAMENTO)\D{0,800}?(20\d{2})', text_upper)
        
    if not exercise:
        years = re.findall(r'\b(20\d{2})\b', text_upper)
        if years:
            exercise_match = min([y for y in years if 2000 <= int(y) <= 2100])
            exercise = type('obj', (object,), {'group': lambda self, x: exercise_match})()

    chassi = extract_chassi(text)

    return {
        'plate': plate_str,
        'renavam': normalize_renavam(renavam.group(1)) if renavam else '',
        'chassi': chassi,
        'exercise': int(exercise.group(1)) if exercise else None,
        'text_extracted': bool(text.strip())
    }