import uuid
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from apps.fleet.models import Driver, VehicleExitOrder
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
from .models import Member, Trip
from . import tests_integration as integration


@override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.company_urls',
    MANAGEMENT_ORIGIN='https://gestao.test', DRIVER_APP_ORIGIN='https://app.test',
    ALLOWED_HOSTS=['testserver', 'gestao.test', 'app.test'], MIDDLEWARE=integration.middleware)
class CompanyRolesTests(TestCase):
    setUp = integration.CentralAccountsTests.setUp
    values = integration.CentralAccountsTests.values

    def desktop(self, role):
        user = get_user_model().objects.create_user(username=role+'@empresa.com', email=role+'@empresa.com', password='Pessoal-segura-987')
        Member.objects.create(company=self.company, user=user, role=role)
        return user

    def driver_client(self):
        user = get_user_model().objects.create_user(username='driver@empresa.com', email='driver@empresa.com', password='Pessoal-segura-987')
        member = Member.objects.create(company=self.company, user=user, driver=self.driver, role=Member.DRIVER)
        client = Client()
        client.force_login(user)
        return client, member

    def open_os(self):
        operator = self.desktop(Member.OPERATOR)
        self.client.force_login(operator)
        response = self.client.post('/ordens-saida/nova/', {
            'vehicle': str(self.vehicle.vehicle_id), 'driver': str(self.driver.pk),
            'departed_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'destination': 'Destino de serviço', 'reason': 'Serviço', 'notes': '',
        }, HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 302, response.content)
        return VehicleExitOrder.objects.get()

    def post_trip(self, client, **extra):
        return client.post('/api/driver/trips/', {'vehicle': self.vehicle.pk, 'destinations': ['Destino'], **extra},
            content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()), HTTP_HOST='app.test')

    def test_manager_creates_operator_and_viewer_without_vehicle_grants(self):
        for role in (Member.OPERATOR, Member.VIEWER):
            response = self.client.post('/usuarios/novo/', self.values(role=role, driver='', email=role+'@empresa.com'), HTTP_HOST='gestao.test')
            self.assertEqual(response.status_code, 302)
            member = Member.objects.get(user__email=role+'@empresa.com')
            self.assertEqual(member.role, role)
            self.assertIsNone(member.driver_id)
        response = self.client.get('/usuarios/novo/', HTTP_HOST='gestao.test')
        self.assertNotContains(response, 'name="vehicles"')
        self.assertContains(response, 'Operador')
        self.assertContains(response, 'Consulta')

    def test_new_desktop_roles_login_to_main_and_cannot_manage_users(self):
        for role in (Member.OPERATOR, Member.VIEWER):
            user = self.desktop(role)
            client = Client()
            response = client.post('/entrar/', {'username': user.email, 'password': 'Pessoal-segura-987'}, HTTP_HOST='app.test')
            self.assertEqual(response.url, 'https://gestao.test/')
            self.assertEqual(client.get('/usuarios/', HTTP_HOST='gestao.test').status_code, 403)
            self.assertEqual(client.get('/gestao/bdts/', HTTP_HOST='gestao.test').status_code, 200)

    def test_viewer_is_read_only_even_with_legacy_administrator_group(self):
        viewer = self.desktop(Member.VIEWER)
        group = Group.objects.create(name='Administrador legado para teste')
        group.permissions.set(Permission.objects.filter(content_type__app_label='fleet'))
        viewer.groups.add(group)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get('/veiculos/', HTTP_HOST='gestao.test').status_code, 200)
        self.assertEqual(self.client.get('/ordens-saida/nova/', HTTP_HOST='gestao.test').status_code, 403)
        self.assertEqual(self.client.post('/ordens-saida/nova/', {}, HTTP_HOST='gestao.test').status_code, 403)
        self.assertEqual(self.client.post('/api/vehicles/', {}, HTTP_HOST='gestao.test').status_code, 403)
        self.assertEqual(self.client.get('/api/vehicles/', HTTP_HOST='gestao.test').status_code, 200)
        token = set_scope(Scope(company_id=self.company.pk))
        try:
            self.assertTrue(viewer.has_perm('fleet.view_vehicle'))
            self.assertFalse(viewer.has_perm('fleet.add_vehicle'))
        finally:
            reset_scope(token)

    def test_os_creation_authorizes_app_without_grants_and_closure_revokes_new_trip(self):
        client, member = self.driver_client()
        self.vehicle.drivers.add(member)  # Old grants must not authorize a new trip.
        boot = client.get('/api/driver/bootstrap/', HTTP_HOST='app.test').json()
        self.assertTrue(boot['requires_exit_order'])
        self.assertEqual(boot['vehicles'], [])
        self.assertEqual(self.post_trip(client).status_code, 400)
        order = self.open_os()
        self.vehicle.drivers.clear()
        boot = client.get('/api/driver/bootstrap/', HTTP_HOST='app.test').json()
        self.assertEqual([v['id'] for v in boot['vehicles']], [self.vehicle.pk])
        self.assertEqual(boot['exit_orders'][0]['id'], str(order.pk))
        response = self.post_trip(client, exit_order=str(order.pk))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Trip.objects.get().exit_order_id, order.pk)

    def test_foreign_driver_or_closed_os_does_not_authorize_trip(self):
        client, _ = self.driver_client()
        order = self.open_os()
        VehicleExitOrder.objects.filter(pk=order.pk).update(state='CLOSED')
        self.assertEqual(self.post_trip(client, exit_order=str(order.pk)).status_code, 400)
        self.assertEqual(client.get('/api/driver/bootstrap/', HTTP_HOST='app.test').json()['vehicles'], [])
        self.assertFalse(Trip.objects.exists())

    def test_active_bdt_preserves_driver_of_os_and_cannot_close_os_early(self):
        client, _ = self.driver_client()
        order = self.open_os()
        self.assertEqual(self.post_trip(client, exit_order=str(order.pk)).status_code, 200)
        token = set_scope(Scope(company_id=self.company.pk))
        try:
            other = Driver.objects.create(name='Outro motorista da empresa')
        finally:
            reset_scope(token)
        response = self.client.post(f'/ordens-saida/{order.pk}/editar/', {
            'driver': str(other.pk), 'departed_at': timezone.localtime(order.departed_at).strftime('%Y-%m-%dT%H:%M'),
            'destination': order.destination, 'reason': order.reason, 'notes': '', 'version': order.updated_at.isoformat(),
        }, HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Encerre o BDT')
        order.refresh_from_db()
        self.assertEqual(order.driver_id, self.driver.pk)
        from apps.fleet.services import close_vehicle_exit_order
        token = set_scope(Scope(company_id=self.company.pk))
        try:
            with self.assertRaisesMessage(ValueError, 'Encerre o BDT'):
                close_vehicle_exit_order(order_id=order.pk, returned_at=timezone.now(), return_notes='', user=order.opened_by)
        finally:
            reset_scope(token)

    def test_another_operator_can_close_company_order_but_foreign_operator_cannot(self):
        order = self.open_os()
        operator = get_user_model().objects.create_user(username='second-operator@empresa.com')
        Member.objects.create(company=self.company, user=operator, role=Member.OPERATOR)
        self.client.force_login(self.foreign_user)
        url = f'/ordens-saida/{order.pk}/retorno/'
        self.assertEqual(self.client.post(url, {}, HTTP_HOST='gestao.test').status_code, 404)
        self.client.force_login(operator)
        response = self.client.post(url, {
            'returned_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'return_notes': 'Retorno registrado por outro operador',
        }, HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.closed_by_id, operator.pk)
        self.assertNotEqual(order.opened_by_id, operator.pk)
