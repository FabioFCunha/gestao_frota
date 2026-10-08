import io
import re

def normalize_plate(value): return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
def normalize_renavam(value): return re.sub(r"\D", "", value or "")

def extract_crlv_data(file_obj):
    name=(getattr(file_obj,'name','') or '').lower(); raw=file_obj.read(); file_obj.seek(0); text=''
    if name.endswith('.pdf'):
        try:
            from pypdf import PdfReader
            text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
        except Exception: pass
    if not text.strip():
        try:
            import pytesseract
            from PIL import Image
            if name.endswith('.pdf'):
                from pdf2image import convert_from_bytes
                text='\n'.join(pytesseract.image_to_string(p,lang='por') for p in convert_from_bytes(raw,first_page=1,last_page=1,dpi=250))
            else: text=pytesseract.image_to_string(Image.open(io.BytesIO(raw)),lang='por')
        except Exception: pass
    plate=re.search(r'\b([A-Z]{3})[\s.-]?([0-9])([A-Z0-9])([0-9]{2})\b',text.upper())
    renavam=re.search(r'RENAVAM\D{0,25}([0-9. -]{9,16})',text.upper())
    exercise=re.search(r'(?:EXERC[ÍI]CIO|LICENCIAMENTO)\D{0,20}(20\d{2})',text.upper()) or re.search(r'\b(20\d{2})\b',text)
    return {'plate': ''.join(plate.groups()) if plate else '', 'renavam':normalize_renavam(renavam.group(1)) if renavam else '', 'exercise':int(exercise.group(1)) if exercise else None, 'text_extracted':bool(text.strip())}
