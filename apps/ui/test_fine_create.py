from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.fleet.models import Vehicle, VehicleFine, VehicleFineStatus, VehicleStatus, Sector


class FineCreateRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fine-create", email="fabiocunhaosp@gmail.com", password="safe-password"
        )
        self.client.force_login(self.user)
        self.sector = Sector.objects.get(slug="adm")
        self.user.sectors.add(self.sector)
        status = VehicleStatus.objects.create(name="Ativo")
        self.vehicle = Vehicle.objects.create(status=status, sector=self.sector)
        self.other_vehicle = Vehicle.objects.create(status=status, sector=self.sector)
        self.fine_status = VehicleFineStatus.objects.create(name="Pendente")

    def payload(self, vehicle):
        return {
            "vehicle": str(vehicle.id), "auto_number": "AUTO-1", "agency": "PRF",
            "status": str(self.fine_status.id), "date": "2026-10-05T10:00",
        }

    def test_general_get_renders_new_form(self):
        self.assertEqual(self.client.get(reverse("fine_create")).status_code, 200)

    def test_general_post_uses_the_selected_vehicle(self):
        response = self.client.post(reverse("fine_create"), self.payload(self.vehicle))

        self.assertRedirects(response, reverse("fine_list"))
        self.assertEqual(VehicleFine.objects.get(auto_number="AUTO-1").vehicle_id, self.vehicle.id)

    def test_linked_get_and_post_lock_vehicle(self):
        url = f"{reverse('fine_create')}?vehicle={self.vehicle.id}"
        self.assertContains(self.client.get(url), "Nova multa para a viatura")
        response = self.client.post(url, self.payload(self.other_vehicle))
        self.assertRedirects(response, reverse("vehicle_dossier", kwargs={"pk": self.vehicle.id}))
        self.assertEqual(VehicleFine.objects.get(auto_number="AUTO-1").vehicle_id, self.vehicle.id)

    def test_invalid_form_renders_errors_without_relation_error(self):
        response = self.client.post(reverse("fine_create"), {"agency": "PRF"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Este campo é obrigatório")

    def test_existing_fine_can_still_open_the_edit_flows(self):
        fine = VehicleFine.objects.create(
            vehicle=self.vehicle,
            auto_number="AUTO-EDIT",
            agency="PRF",
            status=self.fine_status,
            date="2026-10-05T10:00:00Z",
            created_by=self.user,
        )

        self.assertEqual(self.client.get(reverse("fine_edit", args=[fine.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("fine_full_edit", args=[fine.id])).status_code, 200)
        response = self.client.post(
            reverse("fine_edit", args=[fine.id]), {"status": str(self.fine_status.id)}
        )
        self.assertRedirects(response, reverse("fine_list"))
        fine.refresh_from_db()
        self.assertEqual(fine.vehicle_id, self.vehicle.id)
