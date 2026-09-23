from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="functional_id",
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                unique=True,
                verbose_name="ID funcional",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="whatsapp",
            field=models.CharField(
                blank=True,
                max_length=30,
                verbose_name="WhatsApp",
            ),
        ),
    ]
