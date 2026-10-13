from django.db import migrations, models


def normalized(field):
    return models.Func(
        models.F(field), models.Value(r"[^0-9]"), models.Value(""), models.Value("g"),
        function="REGEXP_REPLACE", output_field=models.CharField(),
    )


def verify_existing(apps, schema_editor):
    Driver = apps.get_model("fleet", "Driver")
    for field in ("cpf", "cnh_number"):
        duplicates = (
            Driver.objects.using(schema_editor.connection.alias)
            .annotate(identity_key=normalized(field)).exclude(identity_key="")
            .values("identity_key").annotate(total=models.Count("pk")).filter(total__gt=1)
        )
        if duplicates.exists():
            raise RuntimeError(f"Há {field} duplicado. Migração interrompida sem alterar os cadastros.")


class Migration(migrations.Migration):
    dependencies = [("fleet", "0046_driver_cnh_personal_data")]
    operations = [
        migrations.RunPython(verify_existing, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="driver",
            constraint=models.UniqueConstraint(
                normalized("cpf"), condition=models.Q(cpf__regex=r"[0-9]"),
                name="unique_driver_normalized_cpf",
                violation_error_message="CPF já cadastrado em outro motorista.",
            ),
        ),
        migrations.AddConstraint(
            model_name="driver",
            constraint=models.UniqueConstraint(
                normalized("cnh_number"), condition=models.Q(cnh_number__regex=r"[0-9]"),
                name="unique_driver_normalized_cnh",
                violation_error_message="Registro de CNH já cadastrado em outro motorista.",
            ),
        ),
    ]
