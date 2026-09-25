from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0023_remove_driver_sei_acautelamento"),
    ]

    operations = [
        migrations.AddField(
            model_name="maintenance",
            name="completion_mileage",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
