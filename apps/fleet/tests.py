from django.contrib.auth import get_user_model
from django.test import TestCase
from .models import Brand, Maintenance, MaintenanceStatus, MaintenanceType, Vehicle, VehicleHistory, VehicleStatus
from .services import open_maintenance


class MaintenanceOpeningTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operador", password="segura")
        self.active = VehicleStatus.objects.get(name="Ativo")
        self.in_maintenance = VehicleStatus.objects.get(name="Em manutenção")
        self.open = MaintenanceStatus.objects.get(name="Aberta")
        self.vehicle = Vehicle.objects.create(brand=Brand.objects.create(name="Toyota"), status=self.active, created_by=self.user)
        from .services import change_vehicle_plate
        from .models import VehiclePlate
        change_vehicle_plate(vehicle=self.vehicle, plate="ABC1D23", kind=VehiclePlate.CURRENT, user=self.user)

    def test_opening_maintenance_changes_vehicle_status_and_keeps_history(self):
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=MaintenanceType.objects.create(name="Preventiva"), status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        self.vehicle.refresh_from_db()
        maintenance.refresh_from_db()
        self.assertEqual(self.vehicle.status, self.in_maintenance)
        self.assertEqual(maintenance.vehicle_status_before_opening, self.active)
        event = VehicleHistory.objects.get(vehicle=self.vehicle, field="status")
        self.assertEqual(event.reason, "Abertura de manutenção")
        self.assertEqual(event.old_value["name"], "Ativo")
        self.assertEqual(event.new_value["name"], "Em manutenção")

class DriverAssignmentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="admin", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)
        from .models import Driver
        self.driver1 = Driver.objects.create(name="João")
        self.driver2 = Driver.objects.create(name="Maria")

    def test_assign_first_driver(self):
        from .services import assign_driver_to_vehicle
        from .models import VehicleDriverAssignment, VehicleHistory
        
        assign_driver_to_vehicle(vehicle=self.vehicle, driver=self.driver1, user=self.user)
        
        assignment = VehicleDriverAssignment.objects.get(vehicle=self.vehicle, is_active=True)
        self.assertEqual(assignment.driver, self.driver1)
        
        history = VehicleHistory.objects.get(vehicle=self.vehicle, field="driver")
        self.assertEqual(history.new_value["name"], "João")
        self.assertIsNone(history.old_value)

    def test_change_driver(self):
        from .services import assign_driver_to_vehicle
        from .models import VehicleDriverAssignment
        
        assign_driver_to_vehicle(vehicle=self.vehicle, driver=self.driver1, user=self.user)
        assign_driver_to_vehicle(vehicle=self.vehicle, driver=self.driver2, user=self.user)
        
        assignments = VehicleDriverAssignment.objects.filter(vehicle=self.vehicle).order_by("starts_on")
        self.assertEqual(assignments.count(), 2)
        
        self.assertFalse(assignments[0].is_active)
        self.assertIsNotNone(assignments[0].ends_on)
        self.assertEqual(assignments[0].driver, self.driver1)
        
        self.assertTrue(assignments[1].is_active)
        self.assertIsNone(assignments[1].ends_on)
        self.assertEqual(assignments[1].driver, self.driver2)

    def test_unassign_driver(self):
        from .services import assign_driver_to_vehicle, unassign_driver_from_vehicle
        from .models import VehicleDriverAssignment
        
        assign_driver_to_vehicle(vehicle=self.vehicle, driver=self.driver1, user=self.user)
        unassign_driver_from_vehicle(vehicle=self.vehicle, user=self.user)
        
        active = VehicleDriverAssignment.objects.filter(vehicle=self.vehicle, is_active=True).first()
        self.assertIsNone(active)

class VehiclePlateServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="admin_plate", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)

    def test_set_initial_current_plate(self):
        from .services import change_vehicle_plate
        from .models import VehiclePlate, VehicleHistory
        
        plate = change_vehicle_plate(vehicle=self.vehicle, plate=" abc-1234 ", kind=VehiclePlate.CURRENT, user=self.user)
        self.assertEqual(plate.plate, "ABC1234")
        self.assertTrue(plate.kind, VehiclePlate.CURRENT)
        
        active = VehiclePlate.objects.filter(vehicle=self.vehicle, kind=VehiclePlate.CURRENT, ends_on__isnull=True)
        self.assertEqual(active.count(), 1)
        
        history = VehicleHistory.objects.get(vehicle=self.vehicle, field="current_plate")
        self.assertEqual(history.new_value, "ABC1234")
        self.assertIsNone(history.old_value)

    def test_change_current_plate(self):
        from .services import change_vehicle_plate
        from .models import VehiclePlate
        
        change_vehicle_plate(vehicle=self.vehicle, plate="AAA0000", kind=VehiclePlate.CURRENT, user=self.user)
        change_vehicle_plate(vehicle=self.vehicle, plate="BBB1111", kind=VehiclePlate.CURRENT, user=self.user)
        
        plates = VehiclePlate.objects.filter(vehicle=self.vehicle, kind=VehiclePlate.CURRENT).order_by("starts_on")
        self.assertEqual(plates.count(), 2)
        
        self.assertIsNotNone(plates[0].ends_on)
        self.assertEqual(plates[0].plate, "AAA0000")
        
        self.assertIsNone(plates[1].ends_on)
        self.assertEqual(plates[1].plate, "BBB1111")

    def test_set_reserved_plate(self):
        from .services import change_vehicle_plate
        from .models import VehiclePlate
        
        change_vehicle_plate(vehicle=self.vehicle, plate="AAA0000", kind=VehiclePlate.CURRENT, user=self.user)
        change_vehicle_plate(vehicle=self.vehicle, plate="RES0000", kind=VehiclePlate.RESERVED, user=self.user)
        
        current = VehiclePlate.objects.filter(vehicle=self.vehicle, kind=VehiclePlate.CURRENT, ends_on__isnull=True).first()
        reserved = VehiclePlate.objects.filter(vehicle=self.vehicle, kind=VehiclePlate.RESERVED, ends_on__isnull=True).first()
        
        self.assertEqual(current.plate, "AAA0000")
        self.assertEqual(reserved.plate, "RES0000")

class VehicleStatusServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="admin_status", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.unavailable_status = VehicleStatus.objects.get(name="Indisponível")
        self.reserve_status = VehicleStatus.objects.get(name="Reserva")
        self.maintenance_status = VehicleStatus.objects.get(name="Em manutenção")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)

    def test_change_to_unavailable(self):
        from .services import change_vehicle_status
        from .models import VehicleHistory, AuditLog
        
        change_vehicle_status(vehicle=self.vehicle, status_name="Indisponível", user=self.user, reason="Quebrou")
        
        self.assertEqual(self.vehicle.status, self.unavailable_status)
        history = VehicleHistory.objects.get(vehicle=self.vehicle, field="status")
        self.assertEqual(history.old_value["name"], "Ativo")
        self.assertEqual(history.new_value["name"], "Indisponível")
        self.assertEqual(history.reason, "Quebrou")
        
        audit = AuditLog.objects.get(entity_id=self.vehicle.id, action="ALTERAÇÃO DE STATUS")
        self.assertEqual(audit.old_values["status"], "Ativo")
        self.assertEqual(audit.new_values["status"], "Indisponível")

    def test_change_to_reserve(self):
        from .services import change_vehicle_status
        change_vehicle_status(vehicle=self.vehicle, status_name="Reserva", user=self.user)
        self.assertEqual(self.vehicle.status, self.reserve_status)

    def test_change_to_maintenance(self):
        from .services import change_vehicle_status
        change_vehicle_status(vehicle=self.vehicle, status_name="Em manutenção", user=self.user)
        self.assertEqual(self.vehicle.status, self.maintenance_status)

    def test_invalid_status(self):
        from .services import change_vehicle_status
        with self.assertRaises(ValueError):
            change_vehicle_status(vehicle=self.vehicle, status_name="Inexistente", user=self.user)

    def test_same_status_no_history(self):
        from .services import change_vehicle_status
        from .models import VehicleHistory
        
        change_vehicle_status(vehicle=self.vehicle, status_name="Ativo", user=self.user)
        self.assertEqual(self.vehicle.status, self.active_status)
        self.assertFalse(VehicleHistory.objects.filter(vehicle=self.vehicle, field="status").exists())

class MaintenanceCompletionCancellationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="maint_admin", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.maintenance_status = VehicleStatus.objects.get(name="Em manutenção")
        self.reserve_status = VehicleStatus.objects.get(name="Reserva")
        self.unavailable_status = VehicleStatus.objects.get(name="Indisponível")
        
        self.open = MaintenanceStatus.objects.get(name="Aberta")
        self.in_progress = MaintenanceStatus.objects.get(name="Em andamento")
        self.concluded = MaintenanceStatus.objects.get(name="Concluída")
        self.canceled = MaintenanceStatus.objects.get(name="Cancelada")
        
        self.type = MaintenanceType.objects.create(name="Preventiva")
        
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)

    def test_complete_maintenance_to_active(self):
        from .services import complete_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")
        
        self.vehicle.refresh_from_db()
        maintenance.refresh_from_db()
        
        self.assertEqual(maintenance.status, self.concluded)
        self.assertEqual(self.vehicle.status, self.active_status)
        self.assertEqual(maintenance.resolved_by, self.user)
        self.assertIsNotNone(maintenance.exited_at)

    def test_complete_maintenance_to_reserve(self):
        from .services import complete_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Reserva")
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, self.reserve_status)

    def test_complete_maintenance_to_unavailable(self):
        from .services import complete_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Indisponível")
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, self.unavailable_status)

    def test_complete_without_status_raises_error(self):
        from .services import complete_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        with self.assertRaises(ValueError):
            complete_maintenance(maintenance=maintenance, user=self.user)

    def test_prevent_double_completion(self):
        from .services import complete_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")
        with self.assertRaises(ValueError):
            complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")

    def test_cancel_maintenance(self):
        from .services import cancel_maintenance, open_maintenance
        from .models import AuditLog
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        cancel_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")
        maintenance.refresh_from_db()
        
        self.assertEqual(maintenance.status, self.canceled)
        self.assertIsNotNone(maintenance.exited_at)
        self.assertTrue(AuditLog.objects.filter(entity_id=maintenance.id, action="CANCELAMENTO").exists())

    def test_prevent_cancel_of_concluded(self):
        from .services import complete_maintenance, cancel_maintenance, open_maintenance
        maintenance = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=maintenance, user=self.user)
        
        complete_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")
        with self.assertRaises(ValueError):
            cancel_maintenance(maintenance=maintenance, user=self.user, resulting_status="Ativo")

    def test_status_em_andamento_exists(self):
        self.assertTrue(self.in_progress.active)

    def test_prevent_new_maintenance_when_existing_is_in_progress(self):
        from .services import open_maintenance

        existing = Maintenance.objects.create(
            vehicle=self.vehicle,
            type=self.type,
            status=self.in_progress,
        )

        new_maintenance = Maintenance.objects.create(
            vehicle=self.vehicle,
            type=self.type,
            status=self.open,
        )

        with self.assertRaises(ValueError):
            open_maintenance(
                maintenance=new_maintenance,
                user=self.user,
            )

        existing.refresh_from_db()
        new_maintenance.refresh_from_db()

        self.assertEqual(existing.status, self.in_progress)
        self.assertEqual(new_maintenance.status, self.open)

    def test_prevent_multiple_open_maintenances(self):
        from .services import open_maintenance
        m1 = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        open_maintenance(maintenance=m1, user=self.user)
        
        m2 = Maintenance.objects.create(vehicle=self.vehicle, type=self.type, status=self.open)
        with self.assertRaises(ValueError):
            open_maintenance(maintenance=m2, user=self.user)

class InfraMigrationTests(TestCase):
    def test_migration_creates_default_statuses(self):
        # Como o Django já roda as migrations no setup do test DB, 
        # os status já devem existir. Vamos testar a idempotência 
        # chamando a função da migration manualmente.
        import importlib
        migration_module = importlib.import_module("apps.fleet.migrations.0004_auto_20260921_1403")
        create_default_statuses = migration_module.create_default_statuses
        
        initial_vehicle_count = VehicleStatus.objects.count()
        initial_maint_count = MaintenanceStatus.objects.count()
        
        # Altera um status existente para verificar se a migration não o sobrescreve indevidamente
        ativo = VehicleStatus.objects.get(name="Ativo")
        ativo.active = False
        ativo.save()
        
        # Roda a lógica da migration de novo (idempotência)
        from django.apps import apps
        create_default_statuses(apps=apps, schema_editor=None)
        
        # Confirma ausência de duplicação
        self.assertEqual(VehicleStatus.objects.count(), initial_vehicle_count)
        self.assertEqual(MaintenanceStatus.objects.count(), initial_maint_count)
        
        # Confirma que não sobrescreveu o que já existia (o 'Ativo' deve continuar False)
        ativo.refresh_from_db()
        self.assertFalse(ativo.active)

class VehicleMileageServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="maint_admin", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)

    def test_record_first_mileage(self):
        from .services import record_vehicle_mileage
        record_vehicle_mileage(vehicle=self.vehicle, mileage=10000, user=self.user)
        self.assertEqual(self.vehicle.mileage_history.count(), 1)
        self.assertEqual(self.vehicle.mileage_history.first().mileage, 10000)

    def test_record_second_reading_and_preserve_history(self):
        from .services import record_vehicle_mileage
        import time
        record_vehicle_mileage(vehicle=self.vehicle, mileage=10000, user=self.user)
        time.sleep(0.01)
        record_vehicle_mileage(vehicle=self.vehicle, mileage=10500, user=self.user)
        self.assertEqual(self.vehicle.mileage_history.count(), 2)
        
        from .models import Vehicle
        v = Vehicle.objects.get(id=self.vehicle.id)
        self.assertEqual(v.mileage_history.first().mileage, 10500)

    def test_get_current_mileage(self):
        from .services import record_vehicle_mileage
        from .serializers import VehicleSerializer
        import time
        record_vehicle_mileage(vehicle=self.vehicle, mileage=5000, user=self.user)
        time.sleep(0.01) # ensure created_at is different for ordering
        record_vehicle_mileage(vehicle=self.vehicle, mileage=5100, user=self.user)
        
        # Reload vehicle from DB to get correct ordering
        from .models import Vehicle
        v = Vehicle.objects.get(id=self.vehicle.id)
        serializer = VehicleSerializer(v)
        self.assertEqual(serializer.data["current_mileage"], 5100)

    def test_manual_origin_and_user_recorded(self):
        from .services import record_vehicle_mileage
        record_vehicle_mileage(vehicle=self.vehicle, mileage=2000, user=self.user)
        m = self.vehicle.mileage_history.first()
        self.assertEqual(m.origin, "MANUAL")
        self.assertEqual(m.recorded_by, self.user)

    def test_reject_negative_mileage(self):
        from .services import record_vehicle_mileage
        with self.assertRaises(ValueError):
            record_vehicle_mileage(vehicle=self.vehicle, mileage=-10, user=self.user)

    def test_reject_silent_regression(self):
        from .services import record_vehicle_mileage
        record_vehicle_mileage(vehicle=self.vehicle, mileage=5000, user=self.user)
        with self.assertRaises(ValueError):
            record_vehicle_mileage(vehicle=self.vehicle, mileage=4000, user=self.user)

    def test_allow_correction_with_flag(self):
        from .services import record_vehicle_mileage
        record_vehicle_mileage(vehicle=self.vehicle, mileage=5000, user=self.user)
        record_vehicle_mileage(vehicle=self.vehicle, mileage=4000, user=self.user, is_correction=True)
        self.assertEqual(self.vehicle.mileage_history.count(), 2)

    def test_audit_registered(self):
        from .services import record_vehicle_mileage
        from .models import AuditLog
        record_vehicle_mileage(vehicle=self.vehicle, mileage=1000, user=self.user, notes="Motivo")
        log = AuditLog.objects.get(entity_id=self.vehicle.id, action="REGISTRO DE QUILOMETRAGEM")
        self.assertEqual(log.old_values["mileage"], 0)
        self.assertEqual(log.new_values["mileage"], 1000)
        self.assertEqual(log.reason, "Motivo")

class VehicleMileageAPITests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        from django.contrib.auth.models import Permission
        self.user = get_user_model().objects.create_user(username="maint_admin", password="123")
        perm = Permission.objects.get(codename="add_vehiclemileage")
        self.user.user_permissions.add(perm)
        self.readonly_user = get_user_model().objects.create_user(username="viewer", password="123")
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)

    def test_record_mileage_api_auth(self):
        # Without auth
        response = self.client.post(f"/api/vehicles/{self.vehicle.id}/record_mileage/", {"mileage": 5000})
        self.assertEqual(response.status_code, 403)
        
        # With readonly auth
        self.client.force_authenticate(user=self.readonly_user)
        response = self.client.post(f"/api/vehicles/{self.vehicle.id}/record_mileage/", {"mileage": 5000})
        self.assertEqual(response.status_code, 403)
        
        # With authorized auth
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/vehicles/{self.vehicle.id}/record_mileage/", {"mileage": 5000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.vehicle.mileage_history.first().mileage, 5000)

    def test_mileage_history_api(self):
        from .services import record_vehicle_mileage
        record_vehicle_mileage(vehicle=self.vehicle, mileage=1000, user=self.user)
        record_vehicle_mileage(vehicle=self.vehicle, mileage=2000, user=self.user)
        
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/vehicles/{self.vehicle.id}/mileage_history/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(set(d["mileage"] for d in response.data), {1000, 2000})

class VehicleInspectionTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="insp_admin", password="123")
        self.readonly_user = get_user_model().objects.create_user(username="insp_viewer", password="123")
        
        # O DRF exige permissões apropriadas, como não estamos usando DjangoModelPermissions global, 
        # para a API de vistorias o ViewSet default usa IsAuthenticated. Mas pra ser seguro 
        # se adicionarem, vamos garantir permissões:
        from django.contrib.auth.models import Permission
        try:
            perm = Permission.objects.get(codename="add_vehicleinspection")
            self.user.user_permissions.add(perm)
        except Permission.DoesNotExist:
            pass # Pode ainda não estar carregado
            
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)
        from .models import VehicleInspectionType, VehicleInspectionStatus
        self.type = VehicleInspectionType.objects.get(name="Rotina")
        self.status = VehicleInspectionStatus.objects.get(name="Aprovada")

    def test_record_inspection_with_mileage_updates_history(self):
        from .services import record_vehicle_inspection
        record_vehicle_inspection(
            vehicle=self.vehicle,
            type=self.type,
            status=self.status,
            user=self.user,
            mileage=25000,
            inspector_name="João"
        )
        self.assertEqual(self.vehicle.inspections.count(), 1)
        # Check mileage
        self.assertEqual(self.vehicle.mileage_history.first().mileage, 25000)

    def test_latest_inspection_in_serializer(self):
        from .services import record_vehicle_inspection
        from .serializers import VehicleSerializer
        record_vehicle_inspection(
            vehicle=self.vehicle, type=self.type, status=self.status, user=self.user
        )
        serializer = VehicleSerializer(self.vehicle)
        self.assertEqual(serializer.data["latest_inspection_status"], "Aprovada")
        self.assertIsNotNone(serializer.data["latest_inspection_date"])

    def test_inspection_audit_log(self):
        from .services import record_vehicle_inspection
        from .models import AuditLog
        insp = record_vehicle_inspection(
            vehicle=self.vehicle, type=self.type, status=self.status, user=self.user, notes="Teste"
        )
        log = AuditLog.objects.get(entity_id=insp.id, action="REGISTRO DE VISTORIA")
        self.assertEqual(log.new_values["status"], "Aprovada")

    def test_vehicle_status_is_not_changed_silently(self):
        from .services import record_vehicle_inspection
        from .models import VehicleInspectionStatus
        reprovada = VehicleInspectionStatus.objects.get(name="Reprovada")
        record_vehicle_inspection(
            vehicle=self.vehicle, type=self.type, status=reprovada, user=self.user
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status.name, "Ativo") # Manteve o original

    def test_api_record_inspection(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "vehicle": self.vehicle.id,
            "type": self.type.id,
            "status": self.status.id,
            "inspector_name": "Maria",
            "mileage": 30000
        }
        response = self.client.post("/api/vehicle-inspections/", payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.vehicle.inspections.count(), 1)
        self.assertEqual(self.vehicle.mileage_history.count(), 1)

    def test_api_readonly_user_cannot_delete(self):
        # ViewSet uses permission_classes (IsAuthenticated). Deletion should be denied manually in perform_destroy.
        from .services import record_vehicle_inspection
        insp = record_vehicle_inspection(
            vehicle=self.vehicle, type=self.type, status=self.status, user=self.user
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/vehicle-inspections/{insp.id}/")
        self.assertEqual(response.status_code, 403) # PermissionDenied


class VehicleFineTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="fine_admin", password="123")
        self.readonly_user = get_user_model().objects.create_user(username="fine_viewer", password="123")
        
        from django.contrib.auth.models import Permission
        try:
            perm_add = Permission.objects.get(codename="add_vehiclefine")
            perm_change = Permission.objects.get(codename="change_vehiclefine")
            self.user.user_permissions.add(perm_add, perm_change)
        except Permission.DoesNotExist:
            pass
            
        self.active_status = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=self.active_status, created_by=self.user)
        from .models import VehicleFineStatus
        self.status_pendente = VehicleFineStatus.objects.get(name="Pendente")
        self.status_paga = VehicleFineStatus.objects.get(name="Paga")

    def test_create_fine_service(self):
        from .services import create_vehicle_fine
        from django.utils import timezone
        fine = create_vehicle_fine(
            vehicle=self.vehicle,
            auto_number="A123",
            agency="DETRAN",
            status=self.status_pendente,
            date=timezone.now(),
            user=self.user,
            process_number="PROC-001"
        )
        self.assertEqual(fine.auto_number, "A123")
        self.assertEqual(self.vehicle.fines.count(), 1)

    def test_update_fine_service_and_audit(self):
        from .services import create_vehicle_fine, update_vehicle_fine
        from .models import AuditLog
        from django.utils import timezone
        fine = create_vehicle_fine(
            vehicle=self.vehicle,
            auto_number="A123",
            agency="DETRAN",
            status=self.status_pendente,
            date=timezone.now(),
            user=self.user
        )
        
        updated_fine = update_vehicle_fine(fine=fine, user=self.user, status=self.status_paga, amount=130.16)
        self.assertEqual(updated_fine.status.name, "Paga")
        self.assertEqual(updated_fine.amount, 130.16)
        
        log = AuditLog.objects.filter(entity_id=fine.id, action="ALTERAÇÃO DE MULTA").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.old_values["status"], "Pendente")
        self.assertEqual(log.new_values["status"], "Paga")

    def test_fine_does_not_change_vehicle_status(self):
        from .services import create_vehicle_fine
        from django.utils import timezone
        create_vehicle_fine(
            vehicle=self.vehicle, auto_number="A123", agency="DETRAN", status=self.status_pendente, date=timezone.now(), user=self.user
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status.name, "Ativo")

    def test_api_create_fine(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "vehicle": self.vehicle.id,
            "auto_number": "A123",
            "agency": "DETRAN",
            "status": self.status_pendente.id,
            "date": "2023-10-01T12:00:00Z"
        }
        response = self.client.post("/api/vehicle-fines/", payload)
        self.assertEqual(response.status_code, 201)

    def test_api_filters(self):
        from .services import create_vehicle_fine
        from django.utils import timezone
        create_vehicle_fine(vehicle=self.vehicle, auto_number="A123", agency="DETRAN", status=self.status_pendente, date=timezone.now(), user=self.user)
        
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/vehicle-fines/?auto_number=A123")
        self.assertEqual(len(response.data["results"]), 1)

    def test_api_readonly_user(self):
        self.client.force_authenticate(user=self.readonly_user)
        payload = {
            "vehicle": self.vehicle.id,
            "auto_number": "A123",
            "agency": "DETRAN",
            "status": self.status_pendente.id,
            "date": "2023-10-01T12:00:00Z"
        }
        response = self.client.post("/api/vehicle-fines/", payload)
        self.assertEqual(response.status_code, 403)
        
    def test_api_prevent_delete(self):
        from .services import create_vehicle_fine
        from django.utils import timezone
        fine = create_vehicle_fine(vehicle=self.vehicle, auto_number="A123", agency="DETRAN", status=self.status_pendente, date=timezone.now(), user=self.user)
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/vehicle-fines/{fine.id}/")
        self.assertEqual(response.status_code, 403)
        
        self.client.force_authenticate(user=self.readonly_user)
        response = self.client.patch(f"/api/vehicle-fines/{fine.id}/", {"amount": 100})
        self.assertEqual(response.status_code, 403)


class SEIProcessTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="sei_admin", password="123")
        self.readonly_user = get_user_model().objects.create_user(username="sei_viewer", password="123")
        
        from django.contrib.auth.models import Permission
        try:
            perm_add = Permission.objects.get(codename="add_seiprocess")
            perm_change = Permission.objects.get(codename="change_seiprocess")
            self.user.user_permissions.add(perm_add, perm_change)
        except Permission.DoesNotExist:
            pass
            
        from .models import SEIProcessStatus
        self.status_aberto = SEIProcessStatus.objects.get(name="Aberto")
        self.status_cancelado = SEIProcessStatus.objects.get(name="Cancelado")
        self.status_encerrado = SEIProcessStatus.objects.get(name="Encerrado")

    def test_create_process(self):
        from .services import create_sei_process
        process = create_sei_process(
            sei_number="SEI-12345",
            status=self.status_aberto,
            user=self.user,
            title="Aquisição de Veículos"
        )
        self.assertEqual(process.sei_number, "SEI-12345")
        
    def test_prevent_duplicate_process(self):
        from .services import create_sei_process
        create_sei_process(sei_number="SEI-DUPE", status=self.status_aberto, user=self.user)
        with self.assertRaises(ValueError):
            create_sei_process(sei_number="SEI-DUPE", status=self.status_aberto, user=self.user)

    def test_update_process_closes_date(self):
        from .services import create_sei_process, update_sei_process
        process = create_sei_process(sei_number="SEI-CLOSE", status=self.status_aberto, user=self.user)
        self.assertIsNone(process.closing_date)
        
        updated = update_sei_process(process=process, user=self.user, status=self.status_encerrado)
        self.assertIsNotNone(updated.closing_date)
        self.assertEqual(updated.status.name, "Encerrado")

    def test_link_process_to_vehicle(self):
        from .services import create_sei_process, link_sei_process
        from .models import Vehicle, VehicleStatus
        active = VehicleStatus.objects.get(name="Ativo")
        vehicle = Vehicle.objects.create(status=active, created_by=self.user)
        
        process = create_sei_process(sei_number="SEI-LINK", status=self.status_aberto, user=self.user)
        link_sei_process(process=process, obj=vehicle, user=self.user)
        
        self.assertEqual(vehicle.sei_processes.count(), 1)
        self.assertEqual(vehicle.sei_processes.first().process.sei_number, "SEI-LINK")

    def test_api_readonly_permissions(self):
        self.client.force_authenticate(user=self.readonly_user)
        response = self.client.post("/api/sei-processes/", {
            "sei_number": "SEI-API-RO",
            "status": self.status_aberto.id
        })
        self.assertEqual(response.status_code, 403)
        
    def test_api_prevent_delete(self):
        from .services import create_sei_process
        process = create_sei_process(sei_number="SEI-DEL", status=self.status_aberto, user=self.user)
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/sei-processes/{process.id}/")
        self.assertEqual(response.status_code, 403)


class DocumentTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="doc_admin", password="123")
        self.readonly_user = get_user_model().objects.create_user(username="doc_viewer", password="123")
        
        try:
            p1 = Permission.objects.get(codename="add_document")
            p2 = Permission.objects.get(codename="change_document")
            p3 = Permission.objects.get(codename="view_document")
            self.user.user_permissions.add(p1, p2, p3)
            self.readonly_user.user_permissions.add(p3)
        except Permission.DoesNotExist:
            pass
            
        from .models import DocumentType, DocumentStatus, Vehicle, VehicleStatus
        self.doc_type = DocumentType.objects.get(name="Contrato")
        self.doc_type_sei = DocumentType.objects.get(name="SEI")
        self.status_ativo = DocumentStatus.objects.get(name="Ativo")
        
        active = VehicleStatus.objects.get(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=active, created_by=self.user)

    def test_document_creation_and_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document
        
        file_obj = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        
        doc = create_document(
            title="Doc Test",
            document_type_id=self.doc_type.id,
            document_date="2023-01-01",
            file_obj=file_obj,
            user=self.user
        )
        
        self.assertEqual(doc.title, "Doc Test")
        self.assertEqual(doc.versions.count(), 1)
        self.assertEqual(doc.versions.first().original_filename, "test.pdf")

    def test_upload_invalid_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document
        
        file_obj = SimpleUploadedFile("malware.exe", b"bad_content", content_type="application/x-msdownload")
        
        with self.assertRaises(ValueError):
            create_document(
                title="Bad Doc",
                document_type_id=self.doc_type.id,
                document_date="2023-01-01",
                file_obj=file_obj,
                user=self.user
            )

    def test_upload_large_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document
        import io
        
        # Cria arquivo virtual com 11MB (acima dos 10MB)
        # Ao invez de alocar memoria para 11MB, mockamos o atributo size
        file_obj = SimpleUploadedFile("large.pdf", b"x", content_type="application/pdf")
        file_obj.size = 11 * 1024 * 1024 
        
        with self.assertRaises(ValueError):
            create_document(
                title="Large Doc",
                document_type_id=self.doc_type.id,
                document_date="2023-01-01",
                file_obj=file_obj,
                user=self.user
            )

    def test_add_version(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document, add_document_version
        
        f1 = SimpleUploadedFile("v1.pdf", b"1", content_type="application/pdf")
        doc = create_document(title="Doc V1", document_type_id=self.doc_type.id, document_date="2023-01-01", file_obj=f1, user=self.user)
        
        f2 = SimpleUploadedFile("v2.pdf", b"2", content_type="application/pdf")
        add_document_version(document=doc, file_obj=f2, user=self.user)
        
        self.assertEqual(doc.versions.count(), 2)

    def test_link_document_to_multiple_entities(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document, link_document
        from .services import create_sei_process
        from .models import SEIProcessStatus
        
        f1 = SimpleUploadedFile("v1.pdf", b"1", content_type="application/pdf")
        doc = create_document(title="Doc Rel", document_type_id=self.doc_type.id, document_date="2023-01-01", file_obj=f1, user=self.user)
        
        status_aberto = SEIProcessStatus.objects.get(name="Aberto")
        process = create_sei_process(sei_number="SEI-DOC-REL", status=status_aberto, user=self.user)
        
        link_document(document=doc, obj=self.vehicle, user=self.user)
        link_document(document=doc, obj=process, user=self.user)
        
        self.assertEqual(doc.relations.count(), 2)
        self.assertEqual(self.vehicle.documents.count(), 1)
        self.assertEqual(process.documents.count(), 1)

    def test_archive_document(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document, archive_document
        
        f1 = SimpleUploadedFile("v1.pdf", b"1", content_type="application/pdf")
        doc = create_document(title="Doc Arc", document_type_id=self.doc_type.id, document_date="2023-01-01", file_obj=f1, user=self.user)
        
        archive_document(document=doc, user=self.user, reason="Sem utilidade")
        self.assertEqual(doc.status.name, "Arquivado")

    def test_api_download_forbidden_for_readonly(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services import create_document
        f1 = SimpleUploadedFile("v1.pdf", b"1", content_type="application/pdf")
        doc = create_document(title="Doc RO", document_type_id=self.doc_type.id, document_date="2023-01-01", file_obj=f1, user=self.user)
        
        # User without view_document permission should get 403.
        # Wait, self.readonly_user HAS view_document!
        # Ah, self.readonly_user has p3 (view_document).
        # We need a user WITHOUT view_document.
        from django.contrib.auth import get_user_model
        no_perm_user = get_user_model().objects.create_user(username="no_perm", password="123")
        
        self.client.force_authenticate(user=no_perm_user)
        response = self.client.get(f"/api/documents/{doc.id}/download/")
        self.assertEqual(response.status_code, 403)
        
        # Now test that readonly user cannot POST (because they lack add_document)
        self.client.force_authenticate(user=self.readonly_user)
        response = self.client.post("/api/documents/", {
            "title": "Test", 
            "document_type": self.doc_type.id,
            "file": SimpleUploadedFile("v1.pdf", b"1", content_type="application/pdf")
        })
        self.assertEqual(response.status_code, 403)


class DashboardTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="dash_user", password="123")
        
        try:
            p = Permission.objects.get(codename="view_vehicle")
            self.user.user_permissions.add(p)
        except Permission.DoesNotExist:
            pass
            
        from .models import Vehicle, VehicleStatus, Contract, Renter
        import datetime
        active = VehicleStatus.objects.get(name="Ativo")
        self.v1 = Vehicle.objects.create(status=active, created_by=self.user)
        
        renter = Renter.objects.create(name="Locadora X")
        c1 = Contract.objects.create(number="CT-123", renter=renter, starts_on=datetime.date(2023,1,1), ends_on=datetime.date(2025,1,1), administrative_status="VIGENTE")
        c1.vehicles.add(self.v1)

    def test_dashboard_endpoint(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn("metrics", data)
        self.assertIn("alerts", data)
        
        metrics = data["metrics"]
        self.assertEqual(metrics["fleet"]["total"], 1)
        self.assertEqual(metrics["contracts"]["total"], 1)

    def test_dossier_endpoint(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/vehicles/{self.v1.id}/dossier/")
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn("vehicle", data)
        self.assertIn("history", data)
        self.assertIn("inspections", data)
        self.assertIn("maintenances", data)
        self.assertIn("fines", data)
        self.assertIn("documents", data)
        self.assertIn("sei_processes", data)
        
        self.assertEqual(data["vehicle"]["id"], str(self.v1.id))

