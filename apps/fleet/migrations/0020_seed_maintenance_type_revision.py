from django.db import migrations


def create_revision_maintenance_type(apps, schema_editor):
    MaintenanceType = apps.get_model("fleet", "MaintenanceType")

    MaintenanceType.objects.get_or_create(
        name="Revisão",
        defaults={"active": True},
    )


def remove_revision_maintenance_type(apps, schema_editor):
    MaintenanceType = apps.get_model("fleet", "MaintenanceType")

    MaintenanceType.objects.filter(name="Revisão").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0019_seed_maintenance_in_progress_status"),
    ]

    operations = [
        migrations.RunPython(
            create_revision_maintenance_type,
            reverse_code=remove_revision_maintenance_type,
        ),
    ]
