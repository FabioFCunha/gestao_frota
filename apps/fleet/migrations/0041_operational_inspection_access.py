from django.db import migrations


def remove_vehicle_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    alias = schema_editor.connection.alias
    group = Group.objects.using(alias).filter(name="Operacional").first()
    if group:
        permissions = Permission.objects.using(alias).filter(
            content_type__app_label="fleet",
            content_type__model="vehicle",
            codename="view_vehicle",
        )
        group.permissions.remove(*permissions)


def restore_vehicle_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    alias = schema_editor.connection.alias
    group = Group.objects.using(alias).filter(name="Operacional").first()
    if group:
        permissions = Permission.objects.using(alias).filter(
            content_type__app_label="fleet",
            content_type__model="vehicle",
            codename="view_vehicle",
        )
        group.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0040_inspection_mobile_checklist"),
    ]
    operations = [
        migrations.RunPython(
            remove_vehicle_permission,
            restore_vehicle_permission,
        ),
    ]
