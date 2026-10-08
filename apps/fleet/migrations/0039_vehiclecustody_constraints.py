import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fleet", "0038_vehiclecustody_expand")]

    operations = [
        migrations.AlterModelOptions(
            name="vehiclecustody",
            options={"ordering": ["-started_on", "-created_at"]},
        ),
        migrations.AlterField(
            model_name="vehiclecustody", name="vehicle",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name="custodies", to="fleet.vehicle"),
        ),
        migrations.AddConstraint(
            model_name="vehiclecustody",
            constraint=models.UniqueConstraint(fields=("vehicle",), condition=models.Q(("ended_on__isnull", True)), name="unique_open_custody_per_vehicle"),
        ),
        migrations.AddConstraint(
            model_name="vehiclecustody",
            constraint=models.CheckConstraint(condition=models.Q(("ended_on__isnull", True), ("ended_on__gte", models.F("started_on")), _connector="OR"), name="custody_ended_on_after_started_on"),
        ),
    ]
