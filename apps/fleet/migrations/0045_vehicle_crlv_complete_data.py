from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0044_vehicle_chassi_vehiclecrlv_chassi"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="version",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="manufacture_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="model_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="fuel",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="category",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="vehicle_type",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="motor",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="power_cylinder",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="gross_weight",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="cmt",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="axles",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="seating",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="bodywork",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="crv_number",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="security_code_cla",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="owner_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="owner_document",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="location",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="issue_date",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="vehiclecrlv",
            name="observation",
            field=models.TextField(blank=True),
        ),
    ]
