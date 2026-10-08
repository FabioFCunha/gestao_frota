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

    def inspection_payload(self):
        kind, _ = VehicleInspectionType.objects.get_or_create(name="Teste")
        status, _ = VehicleInspectionStatus.objects.get_or_create(name="Aprovada")
        return {
            "vehicle": str(self.other.pk),
            "type": str(kind.pk),
            "status": str(status.pk),
            "date": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "inspector_name": "Responsável teste",
            "inspection_moment": "AVULSA",
            **{
                "check_" + code: "CONFORME"
                for code in (
                    "pneus", "luzes", "vidros", "carroceria",
                    "interior", "equipamentos", "vazamentos", "painel",
                )
            },
            "mileage": "100",
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

    def test_inspection_post_preserves_vehicle(self):
        response = self.client.post(
            reverse("inspection_create", args=[self.vehicle.pk]),
            self.inspection_payload(),
        )
        self.assertEqual(response.status_code, 302)
        item = VehicleInspection.objects.get(vehicle=self.vehicle)
        self.assertEqual(item.inspection_moment, "AVULSA")
        self.assertEqual(item.checklist["version"], 1)
        self.assertEqual(len(item.checklist["items"]), 8)
        self.assertEqual(item.inspector_name, "Dossier Teste")
        self.assertEqual(item.created_by, self.user)
        self.assertEqual(response.url, reverse("inspection_list"))
        self.assertFalse(VehicleInspection.objects.filter(vehicle=self.other).exists())

    def test_other_sector_and_inactive_vehicle_are_blocked(self):
        for vehicle in (self.other,):
            self.assertEqual(self.client.get(
                reverse("inspection_create", args=[vehicle.pk]),
            ).status_code, 404)
            self.assertEqual(self.client.get(
                reverse("maintenance_create") + "?vehicle=" + str(vehicle.pk),
            ).status_code, 404)
        self.vehicle.active = False
        self.vehicle.save()
        self.assertEqual(self.client.get(
            reverse("inspection_create", args=[self.vehicle.pk]),
        ).status_code, 404)

    def test_missing_permission_is_blocked(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(
            reverse("inspection_create", args=[self.vehicle.pk]),
        ).status_code, 403)
        self.assertEqual(self.client.get(
            reverse("maintenance_create") + "?vehicle=" + str(self.vehicle.pk),
        ).status_code, 403)

    def test_invalid_forms_do_not_create_records(self):
        self.assertEqual(self.client.post(
            reverse("inspection_create", args=[self.vehicle.pk]), {},
        ).status_code, 200)
        self.assertEqual(self.client.post(
            reverse("maintenance_create") + "?vehicle=" + str(self.vehicle.pk), {},
        ).status_code, 200)
        self.assertFalse(VehicleInspection.objects.filter(vehicle=self.vehicle).exists())
        self.assertFalse(Maintenance.objects.filter(vehicle=self.vehicle).exists())


    def test_problem_requires_observation(self):
        payload = self.inspection_payload()
        payload["check_pneus"] = "PROBLEMA"
        response = self.client.post(
            reverse("inspection_create", args=[self.vehicle.pk]), payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("note_pneus", response.context["form"].errors)
        self.assertFalse(VehicleInspection.objects.filter(vehicle=self.vehicle).exists())


    def test_operational_group_can_register_inspection(self):
        from django.contrib.auth.models import Group
        self.user.user_permissions.clear()
        self.user.groups.add(Group.objects.get(name="Operacional"))
        self.assertEqual(self.client.get(
            reverse("inspection_create", args=[self.vehicle.pk]),
        ).status_code, 200)
        response = self.client.post(
            reverse("inspection_create", args=[self.vehicle.pk]),
            self.inspection_payload(),
        )
        self.assertEqual(response.status_code, 302)
        item = VehicleInspection.objects.get(vehicle=self.vehicle)
        self.assertEqual(item.created_by, self.user)
        self.assertEqual(len(item.checklist["items"]), 8)
        self.assertEqual(self.client.get(
            reverse("inspection_create", args=[self.other.pk]),
        ).status_code, 404)

    def test_checklist_history_renders_and_escapes_observations(self):
        from django.template.loader import render_to_string
        payload = self.inspection_payload()
        payload["check_pneus"] = "PROBLEMA"
        payload["note_pneus"] = "<script>alert(1)</script>"
        response = self.client.post(
            reverse("inspection_create", args=[self.vehicle.pk]), payload,
        )
        self.assertEqual(response.status_code, 302)
        inspection = VehicleInspection.objects.get(vehicle=self.vehicle)
        html = render_to_string(
            "ui/inspection_checklist.html", {"inspection": inspection},
        )
        self.assertIn("Ver checklist", html)
        self.assertIn("Com problema", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        inspection.checklist = {}
        self.assertNotIn("Ver checklist", render_to_string(
            "ui/inspection_checklist.html", {"inspection": inspection},
        ))
