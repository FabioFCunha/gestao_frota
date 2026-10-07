from django.db import migrations, models


def alter_object_id_postgresql(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        ALTER TABLE fleet_seiprocessrelation
        DROP CONSTRAINT IF EXISTS fleet_seiprocessrelation_object_id_check;
        """
    )

    schema_editor.execute(
        """
        ALTER TABLE fleet_seiprocessrelation
        ALTER COLUMN object_id TYPE uuid
        USING (
            md5(object_id::text || '-fleet')::uuid
        );
        """
    )


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0012_remove_contract_sei_number_and_more"),
    ]

    operations = [
        migrations.RunPython(
            alter_object_id_postgresql,
            reverse_code=migrations.RunPython.noop,
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="seiprocessrelation",
                    name="object_id",
                    field=models.UUIDField(db_index=True),
                ),
            ],
        ),
    ]
