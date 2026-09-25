from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0024_maintenance_completion_mileage"),
    ]

    operations = [
        migrations.AddField(
            model_name="maintenance",
            name="workshop_name",
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
