import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


LEGACY_TABLE = "fleet_vehiclecustody"
LEGACY_TABLE_RENAMED = "fleet_vehiclecustody_legacy_0019"


def migrate_legacy_vehicle_custody(apps, schema_editor):
    VehicleCustody = apps.get_model("fleet", "VehicleCustody")
    VehicleDriverAssignment = apps.get_model(
        "fleet",
        "VehicleDriverAssignment",
    )

    connection = schema_editor.connection
    quote = connection.ops.quote_name

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                id,
                active,
                created_at,
                updated_at,
                sei_number,
                started_on,
                ended_on,
                notes,
                assignment_id
            FROM {quote(LEGACY_TABLE_RENAMED)}
            """
        )
        rows = cursor.fetchall()

    for (
        custody_id,
        active,
        created_at,
        updated_at,
        sei_number,
        started_on,
        ended_on,
        notes,
        assignment_id,
    ) in rows:
        assignment = VehicleDriverAssignment.objects.get(
            pk=assignment_id
        )

        custody = VehicleCustody(
            id=custody_id,
            active=active,
            created_at=created_at,
            updated_at=updated_at,
            vehicle_id=assignment.vehicle_id,
            kind="ACAUTELAMENTO",
            reference=sei_number,
            starts_on=started_on,
            ends_on=ended_on,
            notes=notes or "",
            created_by_id=None,
        )

        custody.save(force_insert=True)


def cleanup_legacy_vehicle_custody(apps, schema_editor):
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    table_names = connection.introspection.table_names()

    if LEGACY_TABLE_RENAMED in table_names:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE {quote(LEGACY_TABLE_RENAMED)}"
            )


class Migration(migrations.Migration):

    dependencies = [
        (
            "fleet",
            "0018_driver_cnh_category_driver_cnh_expiration_and_more",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f"ALTER TABLE {LEGACY_TABLE} "
                        f"RENAME TO {LEGACY_TABLE_RENAMED}"
                    ),
                    reverse_sql=(
                        f"ALTER TABLE {LEGACY_TABLE_RENAMED} "
                        f"RENAME TO {LEGACY_TABLE}"
                    ),
                ),
                migrations.CreateModel(
                    name="VehicleCustody",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        (
                            "active",
                            models.BooleanField(default=True),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(auto_now_add=True),
                        ),
                        (
                            "updated_at",
                            models.DateTimeField(auto_now=True),
                        ),
                        (
                            "kind",
                            models.CharField(
                                choices=[
                                    ("SEI", "SEI"),
                                    ("ACAUTELAMENTO", "Acautelamento"),
                                    ("OUTRO", "Outro"),
                                    ("LEGADO", "Registro legado"),
                                ],
                                default="OUTRO",
                                max_length=20,
                            ),
                        ),
                        (
                            "reference",
                            models.CharField(max_length=120),
                        ),
                        (
                            "starts_on",
                            models.DateTimeField(
                                default=django.utils.timezone.now,
                            ),
                        ),
                        (
                            "ends_on",
                            models.DateTimeField(
                                blank=True,
                                null=True,
                            ),
                        ),
                        (
                            "notes",
                            models.TextField(blank=True),
                        ),
                        (
                            "created_by",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="vehicle_custodies_created",
                                to="accounts.user",
                            ),
                        ),
                        (
                            "vehicle",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="custody_records",
                                to="fleet.vehicle",
                            ),
                        ),
                    ],
                    options={
                        "ordering": ["-starts_on", "-created_at"],
                    },
                ),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="VehicleCustody",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        (
                            "active",
                            models.BooleanField(default=True),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(auto_now_add=True),
                        ),
                        (
                            "updated_at",
                            models.DateTimeField(auto_now=True),
                        ),
                        (
                            "kind",
                            models.CharField(
                                choices=[
                                    ("SEI", "SEI"),
                                    ("ACAUTELAMENTO", "Acautelamento"),
                                    ("OUTRO", "Outro"),
                                    ("LEGADO", "Registro legado"),
                                ],
                                default="OUTRO",
                                max_length=20,
                            ),
                        ),
                        (
                            "reference",
                            models.CharField(max_length=120),
                        ),
                        (
                            "starts_on",
                            models.DateTimeField(
                                default=django.utils.timezone.now,
                            ),
                        ),
                        (
                            "ends_on",
                            models.DateTimeField(
                                blank=True,
                                null=True,
                            ),
                        ),
                        (
                            "notes",
                            models.TextField(blank=True),
                        ),
                        (
                            "created_by",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="vehicle_custodies_created",
                                to="accounts.user",
                            ),
                        ),
                        (
                            "vehicle",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="custody_records",
                                to="fleet.vehicle",
                            ),
                        ),
                    ],
                    options={
                        "ordering": ["-starts_on", "-created_at"],
                    },
                ),
            ],
        ),
        migrations.RunPython(
            migrate_legacy_vehicle_custody,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            cleanup_legacy_vehicle_custody,
            migrations.RunPython.noop,
        ),
    ]
