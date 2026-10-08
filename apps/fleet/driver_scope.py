"""Persistent driver membership and access to ADM / Lei Seca records."""
from .sector_scope import allowed_sector_slugs


KNOWN_SECTORS = {"adm", "lei-seca"}
MANAGEMENT_SECTORS = {49: "lei-seca", 125: "adm"}


def effective_driver_sector_slugs(user, requested_sector=None):
    allowed = allowed_sector_slugs(user)
    allowed = KNOWN_SECTORS.copy() if allowed is None else allowed & KNOWN_SECTORS
    if len(allowed) > 1 and requested_sector in KNOWN_SECTORS:
        return allowed & {requested_sector}
    return allowed


def apply_driver_sector_scope(queryset, user, requested_sector=None):
    return queryset.filter(
        sectors__slug__in=effective_driver_sector_slugs(user, requested_sector)
    ).distinct()


def apply_driver_vehicle_scope(queryset, user, requested_sector=None, lookup="sector__slug"):
    return queryset.filter(**{
        lookup + "__in": effective_driver_sector_slugs(user, requested_sector)
    })


def can_show_driver_sector_filter(user):
    return bool(
        user and user.is_authenticated
        and (user.email or "").strip().casefold() == "fabiocunhaosp@gmail.com"
        and (user.is_superuser or getattr(user, "is_system_creator", False))
    )


def sync_driver_sectors_from_bdts(bdts):
    """Add source-confirmed memberships; never remove another sector."""
    from .models import Driver, Sector

    sectors = dict(Sector.objects.filter(slug__in=KNOWN_SECTORS).values_list("slug", "pk"))
    pairs = set()
    for driver_id, management_id in bdts.exclude(driver_id=None).values_list(
        "driver_id", "horus_management_id"
    ):
        slug = MANAGEMENT_SECTORS.get(management_id)
        if slug in sectors:
            pairs.add((driver_id, sectors[slug]))

    through = Driver.sectors.through
    through.objects.bulk_create(
        [through(driver_id=driver_id, sector_id=sector_id) for driver_id, sector_id in pairs],
        ignore_conflicts=True, batch_size=1000,
    )
