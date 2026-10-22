from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.fleet.models import (
    Vehicle, VehiclePlate, VehicleStatus, Sector,
    Maintenance, MaintenanceType, MaintenanceStatus, Workshop,
    VehicleInspection, VehicleInspectionType, VehicleInspectionStatus,
)


@override_settings(ALLOWED_HOSTS=["testserver"])
class DossierActionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dossier-test",
            email="dossier-test@example.com",
            first_name="Dossier",
            last_name="Teste",
            password="test-only",
        )
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="fleet",
            codename__in=["add_maintenance", "add_vehicleinspection"],
        ))
        adm, _ = Sector.objects.get_or_create(
            slug="adm", defaults={"name": "ADM"},
        )
        other_sector, _ = Sector.objects.get_or_create(
            slug="lei-seca", defaults={"name": "Lei Seca teste"},
        )
        self.user.sectors.add(adm)
        status, _ = VehicleStatus.objects.get_or_create(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=status, sector=adm)
        self.other = Vehicle.objects.create(status=status, sector=other_sector)
        VehiclePlate.objects.create(
            vehicle=self.vehicle, plate="ABC1D23", kind="CURRENT",
        )
        VehiclePlate.objects.create(
            vehicle=self.other, plate="XYZ9A87", kind="CURRENT",
        )
        self.client.force_login(self.user)

    def maintenance_payload(self):
        kind, _ = MaintenanceType.objects.get_or_create(name="Corretiva")
        status, _ = MaintenanceStatus.objects.get_or_create(name="Aberta")
        workshop, _ = Workshop.objects.get_or_create(name="Oficina teste")
        return {
            "plate": "XYZ9A87",
            "vehicle": str(self.other.pk),
            "type": str(kind.pk),
            "status": str(status.pk),
            "workshop": str(workshop.pk),
            "mileage": "100",
            "service": "Teste de vínculo",
            "entered_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "notes": "Teste",
        }

    def test_maintenance_post_preserves_vehicle(self):
        url = reverse("maintenance_create") + "?vehicle=" + str(self.vehicle.pk)
        response = self.client.post(url, self.maintenance_payload())
        self.assertEqual(response.status_code, 302)
        item = Maintenance.objects.get(vehicle=self.vehicle)
        from apps.fleet.models import AuditLog
        audit = AuditLog.objects.get(
            entity_type="maintenance", entity_id=item.pk,
            action="REGISTRO DE MANUTENÇÃO",
        )
        self.assertEqual(audit.user, self.user)
        self.assertEqual(
            response.url,
            reverse("vehicle_dossier", kwargs={"pk": self.vehicle.pk}),
        )
        self.assertFalse(Maintenance.objects.filter(vehicle=self.other).exists())

    def test_retired_routes_cannot_read_or_create_inspections(self):
        before = VehicleInspection.objects.count()
        for url in ("/vistorias/", f"/vistorias/nova/{self.vehicle.pk}/",
                    "/api/vehicle-inspections/"):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.assertEqual(VehicleInspection.objects.count(), before)

    def test_menu_and_dossier_omit_retired_section(self):
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="fleet", codename="view_vehicle",
        ))
        response = self.client.get(reverse("vehicle_dossier", args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Vistorias")
        self.assertNotContains(response, "/vistorias/")
        self.assertContains(response, "Multas")

    def test_legacy_operational_group_has_no_new_access(self):
        from django.contrib.auth.models import Group
        self.user.groups.add(Group.objects.get(name="Operacional"))
        response = self.client.get("/")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response)
