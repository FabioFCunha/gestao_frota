from django.db import migrations, models


def populate_driver_sectors(apps, schema_editor):
    Driver = apps.get_model("fleet", "Driver")
    Sector = apps.get_model("fleet", "Sector")
    BDT = apps.get_model("fleet", "BDT")
    Assignment = apps.get_model("fleet", "VehicleDriverAssignment")
    alias = schema_editor.connection.alias
    sectors = dict(Sector.objects.using(alias).filter(
        slug__in=["adm", "lei-seca"]
    ).values_list("slug", "pk"))
    memberships = {}
    management_sectors = {49: "lei-seca", 125: "adm"}

    for driver_id, management_id, vehicle_slug in BDT.objects.using(alias).exclude(
        driver_id=None
    ).values_list("driver_id", "horus_management_id", "vehicle__sector__slug").iterator():
        slug = management_sectors.get(management_id, vehicle_slug)
        if slug in sectors:
            memberships.setdefault(driver_id, set()).add(slug)

    for driver_id, slug in Assignment.objects.using(alias).filter(
        is_active=True
    ).values_list("driver_id", "vehicle__sector__slug").iterator():
        if slug in sectors:
            memberships.setdefault(driver_id, set()).add(slug)

    through = Driver.sectors.through
    rows = []
    for driver_id in Driver.objects.using(alias).values_list("pk", flat=True).iterator():
        # Existing drivers without operational evidence retain the legacy
        # Lei Seca list. New manual records require an explicit sector.
        slugs = memberships.get(driver_id, {"lei-seca"})
        for slug in slugs:
            if slug in sectors:
                rows.append(through(driver_id=driver_id, sector_id=sectors[slug]))
    through.objects.using(alias).bulk_create(rows, ignore_conflicts=True, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [("fleet", "0041_operational_inspection_access")]

    operations = [
        migrations.AddField(
            model_name="driver",
            name="sectors",
            field=models.ManyToManyField(
                blank=True, related_name="drivers", to="fleet.sector", verbose_name="Setores",
            ),
        ),
        migrations.RunPython(populate_driver_sectors, migrations.RunPython.noop),
    ]
