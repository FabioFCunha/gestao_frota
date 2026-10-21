import uuid
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.fleet.models import BDT, VehicleExitOrder
from .tests_tenants import scope
from . import tests_integration as integration
from .horus_panel import status_of


@override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.company_urls',
    MANAGEMENT_ORIGIN='https://gestao.test', DRIVER_APP_ORIGIN='https://app.test',
    ALLOWED_HOSTS=['testserver', 'gestao.test', 'app.test'], MIDDLEWARE=integration.middleware)
class HorusPanelTests(TestCase):
    setUp = integration.CentralAccountsTests.setUp

    def order(self, **extra):
        return VehicleExitOrder.objects.create(vehicle=self.vehicle.vehicle, driver=self.driver,
            departed_at=timezone.now()-timedelta(hours=2), destination='Destino', reason='Serviço',
            opened_by=self.manager, number=str(uuid.uuid4())[:20], **extra)

    def bdt(self, **extra):
        values = dict(external_id=uuid.uuid4(), vehicle=self.vehicle.vehicle, driver=self.driver,
                      started_at=timezone.now()-timedelta(hours=1), started_km='100')
        values.update(extra)
        return BDT.objects.create(**values)

    def page(self, **params):
        return self.client.get('/gestao/bdts/', params, HTTP_HOST='gestao.test')

    def test_horus_default_and_os_metrics(self):
        with scope(self.company, self.manager):
            order = self.order()
            bdt = self.bdt(ended_at=timezone.now(), ended_km='145')
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acompanhamento de BDTs — Hórus')
        self.assertContains(response, order.number)
        self.assertContains(response, '45 km')
        self.assertNotContains(response, 'tile.openstreetmap')
        row = response.context['page_obj'][0]
        self.assertEqual(row['bdt'].pk, bdt.pk)
        self.assertEqual(row['state'], 'closed')

    def test_missing_os_filters_and_foreign_records(self):
        with scope(self.company, self.manager):
            order = self.order()
        with scope(self.other, self.foreign_user):
            BDT.objects.create(external_id=uuid.uuid4(), driver=self.foreign_driver,
                               started_at=timezone.now(), started_km='100')
        response = self.page(source='horus', status='missing')
        self.assertContains(response, order.number)
        self.assertContains(response, 'Sem BDT localizado')
        self.assertNotContains(response, 'Motorista secreto')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        response = self.page(source='horus', driver=str(self.foreign_driver.pk))
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_next_order_and_wrong_driver_do_not_match(self):
        with scope(self.company, self.manager):
            first = self.order(state='CLOSED', returned_at=timezone.now()-timedelta(minutes=90))
            second = self.order()
            second.departed_at = timezone.now()-timedelta(minutes=80)
            second.save()
            self.bdt()
        response = self.page(status='missing')
        self.assertContains(response, first.number)
        self.assertNotContains(response, second.number)
        with scope(self.company, self.manager):
            BDT.objects.update(driver=None)
        response = self.page(status='missing')
        self.assertContains(response, second.number)

    def test_invalid_dates_are_safe_and_status_is_explicit(self):
        response = self.page(source='horus', start='2026-10-30', end='2026-10-01')
        self.assertContains(response, 'Informe um período')
        with scope(self.company, self.manager):
            self.assertEqual(status_of(self.bdt(ended_at=timezone.now(), ended_km='90')), 'inconsistent')
            self.assertEqual(status_of(self.bdt(horus_active=False)), 'incomplete')

    def test_app_companies_keep_existing_monitor(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'driverops/dashboard.html')

    def test_segov_keeps_original_bdt_list_and_has_no_monitor_menu(self):
        with self.settings(HORUS_COMPANY_IDS=(str(self.company.pk),)):
            response = self.page()
            self.assertRedirects(response, '/bdts/', fetch_redirect_response=False)
            response = self.client.get('/bdts/', HTTP_HOST='gestao.test')
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'ui/bdt_list.html')
            self.assertContains(response, 'href="/bdts/"')
            self.assertNotContains(response, 'Acompanhamento de BDTs')
            self.assertNotContains(response, 'href="/gestao/bdts/"')
            self.assertRedirects(self.page(source='app'), '/bdts/', fetch_redirect_response=False)
