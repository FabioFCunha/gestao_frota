"""Expande o acautelamento legado sem reconstruir tabelas ou inferir dados."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def derive_custody_links(apps, schema_editor):
    Custody = apps.get_model("fleet", "VehicleCustody")
    Assignment = apps.get_model("fleet", "VehicleDriverAssignment")
    db = schema_editor.connection.alias
    issues = []
    assignment_ids = set()
    derived = []

    for custody in Custody.objects.using(db).select_related("assignment").order_by("id"):
        assignment = custody.assignment
        if assignment is None:
            issues.append(f"custody:{custody.pk}:sem-assignment")
            continue
        if custody.assignment_id in assignment_ids:
            issues.append(f"assignment:{assignment.pk}:multiplas-custodies")
        assignment_ids.add(custody.assignment_id)
        if custody.ended_on and custody.ended_on < custody.started_on:
            issues.append(f"custody:{custody.pk}:fim-anterior-ao-inicio")
        derived.append((custody, assignment))

    open_by_vehicle = {}
    for custody, assignment in derived:
        if custody.ended_on is None:
            open_by_vehicle.setdefault(assignment.vehicle_id, []).append(custody.pk)
    for vehicle_id, custody_ids in open_by_vehicle.items():
        if len(custody_ids) > 1:
            issues.append(f"vehicle:{vehicle_id}:custodias-abertas:{','.join(map(str, custody_ids))}")

    if issues:
        raise RuntimeError(
            "Conversão de acautelamento abortada; corrija com evidência antes de migrar: "
            + "; ".join(issues[:20])
        )

    for custody, assignment in derived:
        custody.vehicle_id = assignment.vehicle_id
        custody.save(update_fields=["vehicle"])
        Assignment.objects.using(db).filter(pk=assignment.pk, custody__isnull=True).update(custody=custody)


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0037_alter_vehicle_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclecustody", name="vehicle",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="custodies", to="fleet.vehicle"),
        ),
        migrations.AddField(
            model_name="vehicledriverassignment", name="custody",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="assignments", to="fleet.vehiclecustody",
                                    verbose_name="Acautelamento"),
        ),
        migrations.AddField(
            model_name="vehiclecustody", name="created_by",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="vehicle_custodies_created", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="vehiclecustody", name="ended_by",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="vehicle_custodies_ended", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(derive_custody_links, migrations.RunPython.noop),
    ]
