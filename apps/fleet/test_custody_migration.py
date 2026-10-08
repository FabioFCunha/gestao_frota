import unittest

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@unittest.skipUnless(connection.vendor == "postgresql", "requer PostgreSQL isolado")
class VehicleCustodyConversionMigrationTests(TransactionTestCase):
    """Valida a conversão da estrutura legada de acautelamento em PostgreSQL."""

    migrate_from = [("fleet", "0037_alter_vehicle_options")]
    migrate_to = [("fleet", "0039_vehiclecustody_constraints")]

    def tearDown(self):
        """
        Restaura o schema para 0039 somente quando o teste realmente
        alcançou a migration alvo.

        Os cenários que provocam falha em 0038 permanecem em 0037,
        portanto não tentamos reaplicar a migration que acabou de falhar.
        """
        if getattr(self, "_migration_reached_target", False):
            self.migrate(self.migrate_to)

        super().tearDown()

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def make_legacy(self, *, duplicate=False, invalid_date=False):
        apps = self.migrate(self.migrate_from)

        Status = apps.get_model("fleet", "VehicleStatus")
        Vehicle = apps.get_model("fleet", "Vehicle")
        Driver = apps.get_model("fleet", "Driver")
        Assignment = apps.get_model("fleet", "VehicleDriverAssignment")
        Custody = apps.get_model("fleet", "VehicleCustody")

        status = Status.objects.create(name="Ativo")
        vehicle = Vehicle.objects.create(status=status)
        driver = Driver.objects.create(name="Motorista")
        assignment = Assignment.objects.create(
            vehicle=vehicle,
            driver=driver,
        )
        custody = Custody.objects.create(
            assignment=assignment,
            sei_number="SEI-001",
            started_on="2026-01-01",
            notes="preservar",
        )

        if duplicate:
            Custody.objects.create(
                assignment=assignment,
                sei_number="SEI-002",
                started_on="2026-01-02",
            )

        if invalid_date:
            Custody.objects.filter(pk=custody.pk).update(
                ended_on="2025-12-31"
            )

        return custody.pk, assignment.pk, vehicle.pk

    def test_conversion_preserves_legacy_and_new_links(self):
        custody_id, assignment_id, vehicle_id = self.make_legacy()

        apps = self.migrate(self.migrate_to)
        self._migration_reached_target = True

        Custody = apps.get_model("fleet", "VehicleCustody")
        Assignment = apps.get_model("fleet", "VehicleDriverAssignment")

        custody = Custody.objects.get(pk=custody_id)
        assignment = Assignment.objects.get(pk=assignment_id)

        self.assertEqual(custody.vehicle_id, vehicle_id)
        self.assertEqual(custody.assignment_id, assignment_id)
        self.assertEqual(assignment.custody_id, custody_id)
        self.assertEqual(custody.sei_number, "SEI-001")
        self.assertEqual(str(custody.started_on), "2026-01-01")
        self.assertEqual(custody.notes, "preservar")
        self.assertIsNone(custody.created_by_id)
        self.assertIsNone(custody.ended_by_id)

    def test_duplicate_assignment_aborts_without_mutating_legacy_data(self):
        self.make_legacy(duplicate=True)

        with self.assertRaises(RuntimeError):
            self.migrate([("fleet", "0038_vehiclecustody_expand")])

        apps = MigrationExecutor(connection).loader.project_state(
            self.migrate_from
        ).apps

        Custody = apps.get_model("fleet", "VehicleCustody")

        self.assertEqual(Custody.objects.count(), 2)

    def test_invalid_dates_abort_without_adjustment(self):
        custody_id, _, _ = self.make_legacy(invalid_date=True)

        with self.assertRaises(RuntimeError):
            self.migrate([("fleet", "0038_vehiclecustody_expand")])

        apps = MigrationExecutor(connection).loader.project_state(
            self.migrate_from
        ).apps

        Custody = apps.get_model("fleet", "VehicleCustody")

        self.assertEqual(
            str(Custody.objects.get(pk=custody_id).ended_on),
            "2025-12-31",
        )
