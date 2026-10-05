from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fleet", "0031_add_geocoded_addresses")]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="revision_reference_km",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="revision_reference_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="revision_reference_source",
            field=models.CharField(max_length=100, blank=True),
        ),
    ]
