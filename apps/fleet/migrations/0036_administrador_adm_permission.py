from django.db import migrations


def create_adm_manager_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="fleet",
        model="vehicle",
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="manage_vehicle_status",
        defaults={"name": "Pode gerenciar situação administrativa da viatura"},
    )

    group, _ = Group.objects.get_or_create(name="Administrador ADM")
    group.permissions.add(permission)


def remove_adm_manager_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    group = Group.objects.filter(name="Administrador ADM").first()
    content_type = ContentType.objects.filter(app_label="fleet", model="vehicle").first()
    permission = Permission.objects.filter(
        content_type=content_type,
        codename="manage_vehicle_status",
    ).first() if content_type else None

    if group and permission:
        group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0035_populate_initial_sectors"),
    ]

    operations = [
        migrations.RunPython(
            create_adm_manager_role,
            reverse_code=remove_adm_manager_role,
        ),
    ]
