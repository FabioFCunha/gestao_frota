from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0036_administrador_adm_permission"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="vehicle",
            options={
                "permissions": [
                    (
                        "manage_vehicle_status",
                        "Pode gerenciar situação administrativa da viatura",
                    ),
                ],
            },
        ),
    ]
