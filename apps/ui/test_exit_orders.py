from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.fleet.models import Driver, Vehicle, VehicleExitOrder, VehiclePlate, VehicleStatus, Sector


class VehicleExitOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='os-author', password='secret')
        self.other = User.objects.create_user(username='os-other', password='secret')
        permissions = Permission.objects.filter(codename__in=['view_vehicle', 'add_vehicleexitorder', 'change_vehicleexitorder', 'view_vehicleexitorder'])
        self.user.user_permissions.add(*permissions)
        self.other.user_permissions.add(*permissions)
        self.status = VehicleStatus.objects.create(name='Ativo')
        self.sector = Sector.objects.get(slug="adm")
        self.user.sectors.add(self.sector)
        self.other.sectors.add(self.sector)
        self.vehicle = Vehicle.objects.create(status=self.status, sector=self.sector)
        self.other_vehicle = Vehicle.objects.create(status=self.status, sector=self.sector)
        VehiclePlate.objects.create(vehicle=self.vehicle, plate='ABC1D23', kind=VehiclePlate.CURRENT)
        self.driver = Driver.objects.create(name='Motorista OS')
        self.client.force_login(self.user)

    def payload(self, **override):
        data = {'vehicle': str(self.vehicle.id), 'driver': str(self.driver.id), 'departed_at': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'), 'destination': 'Destino', 'reason': 'Motivo', 'notes': ''}
        data.update(override)
        return data

    def test_general_and_linked_opening_preserve_vehicle_status_and_assignment(self):
        response = self.client.post(reverse('exit_order_create'), self.payload())
        self.assertEqual(response.status_code, 302)
        order = VehicleExitOrder.objects.get()
        self.assertEqual(order.vehicle_id, self.vehicle.id)
        self.assertEqual(order.opened_by_id, self.user.id)
        self.assertEqual(order.state, VehicleExitOrder.State.PENDING)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status_id, self.status.id)
        order.delete()  # only test cleanup; deletion is not exposed by the UI.
        linked = reverse('exit_order_create') + f'?vehicle={self.vehicle.id}'
        response = self.client.post(linked, self.payload(vehicle=str(self.other_vehicle.id)))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VehicleExitOrder.objects.get().vehicle_id, self.vehicle.id)

    def test_general_and_linked_get_render_vehicle_labels_and_return_pages(self):
        general = self.client.get(reverse('exit_order_create'))
        self.assertEqual(general.status_code, 200)
        self.assertContains(general, 'ABC1D23')
        self.assertContains(general, 'name="vehicle"')

        linked_url = reverse('exit_order_create') + f'?vehicle={self.vehicle.id}'
        linked = self.client.get(linked_url)
        self.assertEqual(linked.status_code, 200)
        self.assertContains(linked, 'Viatura vinculada:')
        self.assertNotContains(linked, 'name="vehicle"')

        self.client.post(reverse('exit_order_create'), self.payload())
        order = VehicleExitOrder.objects.get()
        self.assertEqual(self.client.get(reverse('exit_order_detail', args=[order.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('exit_order_return', args=[order.id])).status_code, 200)

    def test_only_one_pending_order_and_only_author_can_close(self):
        self.client.post(reverse('exit_order_create'), self.payload())
        response = self.client.post(reverse('exit_order_create'), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VehicleExitOrder.objects.count(), 1)
        order = VehicleExitOrder.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': self.payload()['departed_at']}).status_code, 403)
        self.client.force_login(self.user)
        before = order.departed_at - timedelta(minutes=1)
        response = self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(before).strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.state, VehicleExitOrder.State.CLOSED)
        self.assertEqual(self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')}).status_code, 200)

    def test_required_fields_and_permissions(self):
        self.assertEqual(self.client.post(reverse('exit_order_create'), {}).status_code, 200)
        self.client.logout()
        unprivileged = User.objects.create_user(username='os-reader', password='secret')
        self.client.force_login(unprivileged)
        self.assertEqual(self.client.get(reverse('exit_order_list')).status_code, 403)
