from django.db.models import Q


ADM_SLUG = "adm"
LEI_SECA_SLUG = "lei-seca"
SECTOR_PARAM = "sector"


def is_general_admin(user):
    """General administrator bypasses sector visualization scope."""
    return bool(user and user.is_authenticated and user.is_superuser)


def allowed_sector_slugs(user):
    if is_general_admin(user):
        return None

    if not user or not user.is_authenticated:
        return set()

    return set(user.sectors.values_list("slug", flat=True))


def sector_filter_q(user, requested_sector=None, lookup="sector"):
    """
    Return a Q object representing the data scope for the user.

    - General administrators: no restriction.
    - One sector: only that sector.
    - Both sectors: both, optionally narrowed by ?sector=adm|lei-seca.
    - No sector: no records.
    """
    allowed = allowed_sector_slugs(user)

    if allowed is None:
        return Q()

    allowed &= {ADM_SLUG, LEI_SECA_SLUG}

    if not allowed:
        return Q(pk__isnull=True)

    if len(allowed) == 2 and requested_sector in {ADM_SLUG, LEI_SECA_SLUG}:
        allowed = {requested_sector}

    return Q(**{f"{lookup}__slug__in": allowed})


def apply_sector_scope(queryset, user, requested_sector=None, lookup="sector"):
    return queryset.filter(sector_filter_q(user, requested_sector, lookup))


def user_can_access_vehicle(user, vehicle, requested_sector=None):
    if vehicle is None:
        return False

    allowed = allowed_sector_slugs(user)
    if allowed is None:
        return True

    allowed &= {ADM_SLUG, LEI_SECA_SLUG}
    vehicle_slug = getattr(getattr(vehicle, "sector", None), "slug", None)

    if vehicle_slug not in allowed:
        return False

    if len(allowed) == 2 and requested_sector in {ADM_SLUG, LEI_SECA_SLUG}:
        return vehicle_slug == requested_sector

    return True


def validate_vehicle_scope(user, vehicle, requested_sector=None):
    if not user_can_access_vehicle(user, vehicle, requested_sector):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Veículo fora do setor autorizado para este usuário.")
\n\ndef can_manage_vehicle_status(user):\n    """Permissão administrativa específica para gestão da situação das viaturas da ADM."""\n    if not user or not user.is_authenticated:\n        return False\n    if getattr(user, "is_system_creator", False) or user.is_superuser:\n        return True\n    return (\n        user.has_perm("fleet.manage_vehicle_status")\n        and user.sectors.filter(slug=ADM_SLUG).exists()\n    )\n

def can_manage_vehicle_status(user):
    """Permissão administrativa específica para gestão da situação das viaturas da ADM."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_system_creator", False) or user.is_superuser:
        return True
    return user.has_perm("fleet.manage_vehicle_status") and user.sectors.filter(slug=ADM_SLUG).exists()
