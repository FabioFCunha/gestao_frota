from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0045_vehicle_crlv_complete_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="driver",
            name="cpf",
            field=models.CharField(blank=True, max_length=14, verbose_name="CPF"),
        ),
        migrations.AddField(
            model_name="driver",
            name="birth_date",
            field=models.DateField(blank=True, null=True, verbose_name="Data de nascimento"),
        ),
    ]
