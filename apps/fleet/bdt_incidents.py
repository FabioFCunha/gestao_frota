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


def can_manage_bdt_incidents(user):
    from .tenant_scope import company_id

    return bool(user and user.is_authenticated and user.is_active and (
        user.has_perm("fleet.change_bdt")
        or (not company_id() and user.is_system_creator)
    ))


def update_bdt_incident(*, bdt_id, vehicle_id, user, status, responsible,
                        note, expected_revision, requested_sector=None):
    """Registra uma providência sem modificar campos recebidos do Hórus."""
    from django.core.exceptions import PermissionDenied, ValidationError
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from .models import BDT, BDTIncidentFollowUp, BDTIncidentUpdate, AuditLog, Vehicle
    from .sector_scope import validate_vehicle_scope

    if not can_manage_bdt_incidents(user):
        raise PermissionDenied
    responsible, note = responsible.strip(), note.strip()
    if status not in BDTIncidentFollowUp.Status.values:
        raise ValidationError("Situação inválida.")
    if not responsible or len(responsible) > 150 or not note or len(note) > 5000:
        raise ValidationError("Informe responsável e providência (até 5.000 caracteres).")

    with transaction.atomic():
        vehicle = get_object_or_404(Vehicle.objects.all(), pk=vehicle_id)
        validate_vehicle_scope(user, vehicle, requested_sector)
        # Serializa inclusive a criação do primeiro acompanhamento.
        bdt = get_object_or_404(
            BDT.objects.select_for_update(), pk=bdt_id, vehicle_id=vehicle_id,
        )
        followup = BDTIncidentFollowUp.objects.filter(bdt=bdt).first()
        if followup is None and not detect_bdt_incident(bdt.note):
            raise ValidationError("Este BDT não possui indício de avaria para acompanhar.")
        revision = followup.revision if followup else 0
        if expected_revision != revision:
            raise ValidationError("O acompanhamento foi atualizado por outra pessoa. Recarregue o prontuário antes de salvar.")
        old = {"status": followup.status if followup else "PENDING",
               "responsible": followup.responsible if followup else "", "revision": revision}
        if followup is None:
            followup = BDTIncidentFollowUp(bdt=bdt)
        followup.status, followup.responsible = status, responsible
        followup.revision = revision + 1
        followup.save()
        BDTIncidentUpdate.objects.create(
            followup=followup, status=status, responsible=responsible, note=note, author=user,
        )
        AuditLog.objects.create(
            user=user, module="bdts", action="ACOMPANHAMENTO DE AVARIA",
            entity_type="bdt", entity_id=bdt.pk, old_values=old,
            new_values={"status": status, "responsible": responsible, "revision": followup.revision},
            reason=note,
        )
        return followup
