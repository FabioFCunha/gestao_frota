from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.fleet.models import AuditLog, BDT, Driver, Sector, Vehicle, VehicleExitOrder, VehiclePlate, VehicleStatus


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

    def test_only_one_pending_order_and_another_operator_can_close(self):
        self.client.post(reverse('exit_order_create'), self.payload())
        response = self.client.post(reverse('exit_order_create'), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VehicleExitOrder.objects.count(), 1)
        order = VehicleExitOrder.objects.get()
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('exit_order_detail', args=[order.id])), 'Registrar retorno')
        self.assertContains(self.client.get(reverse('vehicle_dossier', args=[self.vehicle.id])), 'Registrar retorno')
        before = order.departed_at - timedelta(minutes=1)
        response = self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(before).strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.state, VehicleExitOrder.State.CLOSED)
        self.assertEqual(order.opened_by_id, self.user.pk)
        self.assertEqual(order.closed_by_id, self.other.pk)
        self.assertEqual(AuditLog.objects.get(action='ENCERRAMENTO OS SAÍDA', entity_id=order.pk).user_id, self.other.pk)
        detail = self.client.get(reverse('exit_order_detail', args=[order.pk]))
        self.assertContains(detail, 'BDT — abertura e fechamento')
        self.assertContains(detail, 'Imprimir')
        self.assertNotContains(detail, 'Log de auditoria')
        self.assertEqual(self.client.post(reverse('exit_order_return', args=[order.id]), {'returned_at': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')}).status_code, 200)

    def test_edit_closed_order_changes_vehicle_and_preserves_return(self):
        VehiclePlate.objects.create(vehicle=self.other_vehicle, plate='DEF4G56', kind=VehiclePlate.CURRENT)
        payload = self.payload()
        self.client.post(reverse('exit_order_create'), payload)
        order = VehicleExitOrder.objects.get()
        self.client.post(reverse('exit_order_return', args=[order.pk]), {
            'returned_at': payload['departed_at'], 'return_notes': 'Retorno registrado',
        })
        order.refresh_from_db()
        returned_at = order.returned_at
        previous_bdt = BDT.objects.create(
            external_id=uuid4(), vehicle=self.vehicle, driver=self.driver,
            started_at=order.departed_at, started_km='321',
        )
        BDT.objects.create(
            external_id=uuid4(), vehicle=self.other_vehicle, driver=self.driver,
            started_at=order.departed_at, started_km='654',
        )
        url = reverse('exit_order_edit', args=[order.pk])
        edit = self.client.get(url)
        form = edit.context['form']
        self.assertEqual(str(form['vehicle'].value()), str(self.vehicle.pk))
        self.assertContains(edit, 'DEF4G56')

        response = self.client.post(url, {
            **payload, 'vehicle': str(self.other_vehicle.pk), 'version': order.updated_at.isoformat(),
        })
        self.assertRedirects(response, reverse('exit_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.vehicle_id, self.other_vehicle.pk)
        self.assertEqual(order.state, VehicleExitOrder.State.CLOSED)
        self.assertEqual(order.returned_at, returned_at)
        self.assertEqual(order.return_notes, 'Retorno registrado')
        detail = self.client.get(response.url)
        self.assertContains(detail, 'DEF4G56')
        self.assertContains(detail, '<strong>654</strong>', html=True)
        self.assertNotContains(detail, '<strong>321</strong>', html=True)
        previous_bdt.refresh_from_db()
        self.assertEqual(previous_bdt.vehicle_id, self.vehicle.pk)
        audit = AuditLog.objects.get(action='EDIÇÃO OS SAÍDA', entity_id=order.pk)
        self.assertEqual(audit.old_values['vehicle_id'], str(self.vehicle.pk))
        self.assertEqual(audit.new_values['vehicle_id'], str(self.other_vehicle.pk))
        self.assertIn('ABC1D23', audit.reason)
        self.assertIn('DEF4G56', audit.reason)

    def test_edit_pending_order_rejects_occupied_and_out_of_scope_vehicles(self):
        payload = self.payload()
        self.client.post(reverse('exit_order_create'), payload)
        order = VehicleExitOrder.objects.get()
        url = reverse('exit_order_edit', args=[order.pk])
        self.client.post(reverse('exit_order_create'), {**payload, 'vehicle': str(self.other_vehicle.pk)})
        data = {**payload, 'vehicle': str(self.other_vehicle.pk), 'version': order.updated_at.isoformat()}
        response = self.client.post(url, data)
        self.assertIn('Esta viatura já possui uma OS pendente de retorno.', response.context['form'].errors['vehicle'])

        Vehicle.objects.filter(pk=self.other_vehicle.pk).update(sector=Sector.objects.get(slug='lei-seca'))
        response = self.client.post(url, data)
        self.assertIn('vehicle', response.context['form'].errors)
        order.refresh_from_db()
        self.assertEqual(order.vehicle_id, self.vehicle.pk)
        self.assertFalse(AuditLog.objects.filter(action='EDIÇÃO OS SAÍDA', entity_id=order.pk).exists())

    def test_required_fields_and_permissions(self):
        self.assertEqual(self.client.post(reverse('exit_order_create'), {}).status_code, 200)
        self.client.logout()
        unprivileged = User.objects.create_user(username='os-reader', password='secret')
        self.client.force_login(unprivileged)
        self.assertEqual(self.client.get(reverse('exit_order_list')).status_code, 403)

    def test_operator_without_close_permission_is_blocked_in_ui_and_service(self):
        self.client.post(reverse('exit_order_create'), self.payload())
        order = VehicleExitOrder.objects.get()
        self.other.user_permissions.remove(Permission.objects.get(codename='change_vehicleexitorder'))
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('exit_order_detail', args=[order.pk])), 'Registrar retorno')
        self.assertEqual(self.client.post(reverse('exit_order_return', args=[order.pk]),
            {'returned_at': self.payload()['departed_at']}).status_code, 403)
        from apps.fleet.services import close_vehicle_exit_order
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            close_vehicle_exit_order(order_id=order.pk, returned_at=timezone.now(), return_notes='', user=self.other)
        order.refresh_from_db()
        self.assertEqual(order.state, VehicleExitOrder.State.PENDING)
