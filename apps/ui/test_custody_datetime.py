from datetime import timedelta
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.fleet.models import Driver, VehicleCustody, VehicleDriverAssignment
from . import test_dossier_actions as dossier


@override_settings(ALLOWED_HOSTS=['testserver'], TIME_ZONE='America/Sao_Paulo')
class CustodyDatetimeTests(TestCase):
    def setUp(self):
        dossier.DossierActionsTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='fleet', codename__in=['view_vehicle', 'change_vehiclecustody']))
        self.driver = Driver.objects.create(name='Responsável inicial')
        self.next_driver = Driver.objects.create(name='Novo responsável')
        self.assignment = VehicleDriverAssignment.objects.create(vehicle=self.vehicle, driver=self.driver,
            starts_on=timezone.now()-timedelta(days=2))
        self.custody = VehicleCustody.objects.create(vehicle=self.vehicle, assignment=self.assignment,
            sei_number='SEI TESTE', started_on=timezone.localdate()-timedelta(days=2))
        self.assignment.custody = self.custody
        self.assignment.save()
        self.url = reverse('vehicle_dossier', args=[self.vehicle.pk])
        self.instant = (timezone.localtime()-timedelta(hours=1)).replace(second=0, microsecond=0)

    def test_form_uses_datetime_inputs(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'type="datetime-local" name="transferred_at"')
        self.assertContains(response, 'type="datetime-local" name="assignment_ended_at"')
        self.assertNotContains(response, '2026-10-06T14:30:00-03:00')

    def test_transfer_converts_local_time_and_preserves_history(self):
        response = self.client.post(self.url, {'action': 'transfer_custody',
            'new_driver': str(self.next_driver.pk), 'transferred_at': self.instant.strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.is_active)
        self.assertEqual(self.assignment.ends_on, self.instant)
        current = VehicleDriverAssignment.objects.get(vehicle=self.vehicle, is_active=True)
        self.assertEqual(current.driver_id, self.next_driver.pk)
        self.assertEqual(current.starts_on, self.instant)

    def test_end_converts_local_time(self):
        self.client.post(self.url, {'action': 'end_custody', 'ended_on': self.instant.date().isoformat(),
            'assignment_ended_at': self.instant.strftime('%Y-%m-%dT%H:%M')})
        self.custody.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.custody.ended_on, self.instant.date())
        self.assertEqual(self.assignment.ends_on, self.instant)

    def test_invalid_time_does_not_transfer_or_close(self):
        for action, field in [('transfer_custody', 'transferred_at'), ('end_custody', 'assignment_ended_at')]:
            response = self.client.post(self.url, {'action': action, field: 'horário inválido',
                'new_driver': str(self.next_driver.pk), 'ended_on': self.instant.date().isoformat()})
            self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.custody.refresh_from_db()
        self.assertTrue(self.assignment.is_active)
        self.assertIsNone(self.custody.ended_on)

    def test_operational_photo_requires_current_driver_photo_and_permission(self):
        from apps.fleet.models import Document, DocumentType, DocumentStatus, DriverCNHPhoto
        photo_url = reverse('driver_cnh_photo', args=[self.driver.pk])
        self.assertNotContains(self.client.get(self.url), photo_url)
        doc = Document.objects.create(title='CNH teste', created_by=self.user,
            document_type=DocumentType.objects.get_or_create(name='CNH')[0],
            status=DocumentStatus.objects.get_or_create(name='Ativo')[0])
        DriverCNHPhoto.objects.create(driver=self.driver, document=doc, image=b'portrait')
        self.assertNotContains(self.client.get(self.url), photo_url)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='fleet', codename='view_driver'))
        self.assertContains(self.client.get(self.url), photo_url)
        DriverCNHPhoto.objects.filter(driver=self.driver).update(active=False)
        self.assertNotContains(self.client.get(self.url), photo_url)
