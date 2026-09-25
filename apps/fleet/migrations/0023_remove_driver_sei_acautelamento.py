from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0022_vehiclecustody"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="driver",
            name="sei_acautelamento",
        ),
    ]
