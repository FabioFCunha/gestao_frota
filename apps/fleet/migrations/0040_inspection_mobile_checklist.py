from django.db import migrations, models


def grant_operational_inspection_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    alias = schema_editor.connection.alias

    group, _ = Group.objects.using(alias).get_or_create(name="Operacional")
    definitions = [
        ("vehicleinspection", "add_vehicleinspection", "Can add vehicle inspection"),
        ("vehicleinspection", "view_vehicleinspection", "Can view vehicle inspection"),
        ("vehicle", "view_vehicle", "Can view vehicle"),
    ]
    for model, codename, name in definitions:
        content_type, _ = ContentType.objects.using(alias).get_or_create(
            app_label="fleet", model=model,
        )
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0039_vehiclecustody_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicleinspection",
            name="inspection_moment",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("SAIDA", "Saída"),
                    ("RETORNO", "Retorno"),
                    ("AVULSA", "Vistoria avulsa"),
                ],
                blank=True,
                default="",
            ),
        ),
        migrations.AddField(
            model_name="vehicleinspection",
            name="checklist",
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.RunPython(
            grant_operational_inspection_permissions,
            migrations.RunPython.noop,
        ),
    ]
