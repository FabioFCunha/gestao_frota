from django.db import migrations


def create_maintenance_in_progress_status(apps, schema_editor):
    MaintenanceStatus = apps.get_model("fleet", "MaintenanceStatus")

    MaintenanceStatus.objects.get_or_create(
        name="Em andamento",
        defaults={"active": True},
    )


def remove_maintenance_in_progress_status(apps, schema_editor):
    # N?o remover o status no rollback para preservar dados hist?ricos.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0018_driver_cnh_category_driver_cnh_expiration_and_more"),
    ]

    operations = [
        migrations.RunPython(
            create_maintenance_in_progress_status,
            reverse_code=remove_maintenance_in_progress_status,
        ),
    ]
