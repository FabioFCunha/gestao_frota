"""Triagem de possíveis ocorrências relatadas nas observações do BDT."""
import re
import unicodedata

_RULES = (
    ("Colisão ou acidente", r"\b(?:sinistr\w*|colis\w*|acidente\w*|abalro\w*|capot\w*|tombamento|batida|bateu|batemos|atropel\w*)\b"),
    ("Pneu ou roda", r"\b(?:pneu\w*\s+(?:(?:dianteiro|traseiro|esquerdo|direito)\s+)*(?:fur\w*|estour\w*|rasg\w*|danific\w*|vazi\w*)|fur\w*\s+(?:o\s+|um\s+)?pneu|roda\s+(?:quebr\w*|danific\w*))\b"),
    ("Avaria", r"\b(?:avaria\w*|amass\w*|arranh\w*|riscad\w*|quebrad\w*|quebrou|trinc\w*|para[- ]?brisa\s+(?:quebr\w*|trinc\w*))\b"),
    ("Incêndio", r"\b(?:incendio|pegou\s+fogo|principio\s+de\s+incendio)\b"),
    ("Roubo ou furto", r"\b(?:roub\w*|furt\w*)\b"),
    ("Alagamento", r"\b(?:alag\w*|inund\w*)\b"),
)
_NEGATIVE = re.compile(
    r"\b(?:sem|nenhum|nenhuma|nao|negou|nega|ausencia\s+de)\b"
)
_RESET = re.compile(r"\b(?:mas|porem|entretanto|contudo)\b")


def detect_bdt_incident(note):
    """Sinaliza indícios para conferência; não confirma sinistro nem altera status."""
    normalized = unicodedata.normalize("NFKD", str(note or "").lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    categories = []
    for label, pattern in _RULES:
        for match in re.finditer(pattern, normalized):
            # Limita negações à oração e reinicia após "mas"/"porém".
            prefix = re.split(r"[.!?;\n,]", normalized[:match.start()])[-1]
            prefix = _RESET.split(prefix)[-1]
            if _NEGATIVE.search(" ".join(prefix.split()[-6:])):
                continue
            categories.append(label)
            break
    if not categories:
        return None
    return {
        "label": "Possível sinistro / avaria",
        "categories": categories,
        "message": "Indício nas observações do motorista. Conferir o relato antes de confirmar a ocorrência.",
    }
