from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from apps.fleet.models import Vehicle, VehicleStatus, Driver, AuditLog
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
from .models import Company, Member, CompanyVehicle

middleware = list(settings.MIDDLEWARE)
if 'apps.driverops.surfaces.AppSurfaceMiddleware' not in middleware:
    middleware.insert(middleware.index('apps.driverops.middleware.CompanyBoundaryMiddleware'), 'apps.driverops.surfaces.AppSurfaceMiddleware')


@override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.company_urls',
    MANAGEMENT_ORIGIN='https://gestao.test', DRIVER_APP_ORIGIN='https://app.test',
    ALLOWED_HOSTS=['testserver', 'gestao.test', 'app.test'], MIDDLEWARE=middleware)
class CentralAccountsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        User = get_user_model()
        self.company = Company.objects.create(name='Empresa central')
        self.other = Company.objects.create(name='Outra empresa')
        self.manager = User.objects.create_user(username='gestor@empresa.com', email='gestor@empresa.com', password='Senha-segura-987')
        self.member = Member.objects.create(company=self.company, user=self.manager, role=Member.MANAGER)
        token = set_scope(Scope(company_id=self.company.pk, actor_id=self.manager.pk))
        try:
            self.driver = Driver.objects.create(name='Motorista cadastrado pela CNH')
            vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name='Disponível'))
            self.vehicle = CompanyVehicle.objects.get(vehicle=vehicle)
        finally:
            reset_scope(token)
        self.foreign_user = User.objects.create_user(username='outro@empresa.com', email='outro@empresa.com')
        self.foreign = Member.objects.create(user=self.foreign_user, company=self.other, role=Member.MANAGER)
        self.foreign_driver = Driver.objects.create(name='Motorista secreto')
        another = User.objects.create_user(username='motorista-secreto')
        Member.objects.create(company=self.other, user=another, driver=self.foreign_driver, role=Member.DRIVER)
        self.client.force_login(self.manager)

    def values(self, **extra):
        return {'first_name': 'Motorista central', 'email': 'motorista@empresa.com', 'is_active': 'True',
                'role': 'driver', 'driver': str(self.driver.pk), 'vehicles': [self.vehicle.pk],
                'initial_password': 'Senha-nova-987', 'initial_password_confirmation': 'Senha-nova-987', **extra}

    def test_original_users_page_is_scoped_to_company(self):
        response = self.client.get('/usuarios/', HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'gestor@empresa.com')
        self.assertNotContains(response, 'outro@empresa.com')
        self.assertNotContains(response, 'Perfis e permissões')
        self.assertEqual(self.client.get(f'/usuarios/{self.foreign_user.pk}/editar/', HTTP_HOST='gestao.test').status_code, 404)
        self.assertEqual(self.client.get('/perfis/', HTTP_HOST='gestao.test').status_code, 403)

    def test_single_registration_creates_email_login_driver_grants_and_audit(self):
        response = self.client.post('/usuarios/novo/', self.values(), HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 302, getattr(response.context, 'flatten', lambda: response.context)())
        user = get_user_model().objects.get(email='motorista@empresa.com')
        self.assertEqual(user.username, user.email)
        self.assertTrue(user.check_password('Senha-nova-987'))
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.is_staff)
        member = Member.objects.get(user=user)
        self.assertEqual(member.company, self.company)
        self.assertEqual(member.driver, self.driver)
        self.assertTrue(self.vehicle.drivers.filter(pk=member.pk).exists())
        self.assertNotIn('Senha-nova-987', str(list(AuditLog.objects.values())))
        # Completing first-password change makes this same database account usable by the app.
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        api = Client()
        response = api.post('/api/driver/login/', {'username': user.email, 'password': 'Senha-nova-987'}, content_type='application/json', HTTP_HOST='app.test')
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()['token']
        bootstrap = api.get('/api/driver/bootstrap/', HTTP_AUTHORIZATION='Bearer '+token, HTTP_HOST='app.test')
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()['vehicles'][0]['id'], self.vehicle.pk)
        # Deactivation in the main users screen immediately revokes app access.
        data = self.values(is_active='False', initial_password='', initial_password_confirmation='')
        self.assertEqual(self.client.post(f'/usuarios/{user.pk}/editar/', data, HTTP_HOST='gestao.test').status_code, 302)
        self.assertEqual(api.get('/api/driver/bootstrap/', HTTP_AUTHORIZATION='Bearer '+token, HTTP_HOST='app.test').status_code, 401)

    def test_forged_driver_profile_or_foreign_user_is_rejected(self):
        response = self.client.post('/usuarios/novo/', self.values(driver=str(self.foreign_driver.pk)), HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email='motorista@empresa.com').exists())
        self.assertEqual(self.client.post(f'/usuarios/{self.foreign_user.pk}/editar/', self.values(), HTTP_HOST='gestao.test').status_code, 404)
        self.assertEqual(self.client.post('/usuarios/novo/', self.values(role='owner'), HTTP_HOST='gestao.test').status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email='motorista@empresa.com').exists())

    def test_app_host_has_no_management_area_and_never_forwards_posts(self):
        self.assertRedirects(self.client.get('/', HTTP_HOST='app.test'), '/api/driver/app/', fetch_redirect_response=False)
        response = self.client.get('/usuarios/', HTTP_HOST='app.test')
        self.assertEqual(response.url, 'https://gestao.test/usuarios/')
        self.assertEqual(self.client.get('/api/driver/management/', HTTP_HOST='app.test').url, 'https://gestao.test/usuarios/')
        response = self.client.post('/usuarios/novo/', self.values(), HTTP_HOST='app.test')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(get_user_model().objects.filter(email='motorista@empresa.com').exists())
        self.assertEqual(self.client.get('/api/driver/app/', HTTP_HOST='app.test').url, 'https://gestao.test/')
        self.assertEqual(self.client.get('/api/driver/bootstrap/', HTTP_HOST='app.test').status_code, 403)
        self.assertEqual(self.client.post('/api/driver/login/', {'username': self.manager.email, 'password': 'Senha-segura-987'}, HTTP_HOST='app.test').status_code, 403)

    def test_manager_login_returns_main_and_driver_returns_only_app(self):
        self.client.logout()
        response = self.client.post('/entrar/', {'username': self.manager.email, 'password': 'Senha-segura-987', 'next': '/api/driver/app/'}, HTTP_HOST='app.test')
        self.assertEqual(response.url, 'https://gestao.test/')
        user = get_user_model().objects.create_user(username='driver@empresa.com', email='driver@empresa.com', password='Senha-nova-987')
        Member.objects.create(user=user, company=self.company, driver=self.driver, role=Member.DRIVER)
        self.client.logout()
        response = self.client.post('/entrar/', {'username': user.email, 'password': 'Senha-nova-987', 'next': '/usuarios/'}, HTTP_HOST='gestao.test')
        self.assertEqual(response.url, 'https://app.test/api/driver/app/')

    def test_company_creation_uses_email_as_login_without_username_field(self):
        admin = get_user_model().objects.create_superuser(username='proprietario', password='Senha-segura-987')
        self.client.force_login(admin)
        response = self.client.post('/empresas/', {'action':'company','company_name':'Empresa nova','manager_name':'Gestor Novo', 'email':'novo@empresa.com','password1':'Senha-nova-987','password2':'Senha-nova-987'}, HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(email='novo@empresa.com')
        self.assertEqual(user.username, user.email)
        self.assertTrue(Member.objects.filter(user=user, role=Member.MANAGER).exists())

    def test_legacy_parallel_management_cannot_create_accounts(self):
        self.assertEqual(self.client.get('/api/driver/management/', HTTP_HOST='gestao.test').url, '/usuarios/')
        self.assertEqual(self.client.post('/api/driver/management/', {'action':'member'}, HTTP_HOST='gestao.test').status_code, 403)

    def test_own_manager_access_cannot_be_disabled(self):
        response = self.client.post(f'/usuarios/{self.manager.pk}/editar/', self.values(role='manager', driver='', vehicles=[], email=self.manager.email, is_active='False'), HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 200)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_active)

    def test_legacy_inspection_group_does_not_override_company_manager_role(self):
        from django.contrib.auth.models import Group
        group, _ = Group.objects.get_or_create(name='Operacional')
        self.manager.groups.add(group)
        self.assertEqual(self.client.get('/usuarios/', HTTP_HOST='gestao.test').status_code, 200)
        self.assertEqual(self.client.get('/', HTTP_HOST='gestao.test').status_code, 200)

    def test_legacy_adoption_is_dry_run_and_preserves_other_companies(self):
        import io
        from django.core.management import call_command
        unowned = Driver.objects.create(name='Cadastro legado')
        from .models import RecordOwner
        call_command('adopt_legacy_company', company=str(self.company.pk), adopt_all_unowned=True, stdout=io.StringIO())
        self.assertFalse(RecordOwner.objects.filter(object_id=unowned.pk).exists())
        call_command('adopt_legacy_company', company=str(self.company.pk), adopt_all_unowned=True, apply=True, stdout=io.StringIO())
        self.assertTrue(RecordOwner.objects.filter(object_id=unowned.pk, company=self.company).exists())
        self.assertTrue(RecordOwner.objects.filter(object_id=self.foreign_driver.pk, company=self.other).exists())

    def test_app_first_password_change_uses_operational_screen(self):
        user = get_user_model().objects.create_user(username='senha@empresa.com', email='senha@empresa.com', password='Inicial-987', must_change_password=True)
        Member.objects.create(user=user, company=self.company, driver=self.driver, role=Member.DRIVER)
        self.client.force_login(user)
        response = self.client.get('/minha-senha/', HTTP_HOST='app.test')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TRANSFROTA · MOTORISTA')
        self.assertNotContains(response, 'Usuários do sistema')
        response = self.client.post('/minha-senha/', {'old_password': 'Inicial-987', 'new_password1': 'Pessoal-987-segura', 'new_password2': 'Pessoal-987-segura'}, HTTP_HOST='app.test')
        self.assertEqual(response.url, 'https://app.test/api/driver/app/')
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertTrue(user.check_password('Pessoal-987-segura'))

    def test_central_login_requires_email_and_resolves_existing_legacy_username(self):
        self.manager.username = 'login-legado'
        self.manager.save(update_fields=['username'])
        self.client.logout()
        response = self.client.post('/entrar/', {'username':'login-legado','password':'Senha-segura-987'}, HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post('/entrar/', {'username':self.manager.email,'password':'Senha-segura-987'}, HTTP_HOST='gestao.test')
        self.assertEqual(response.url, 'https://gestao.test/')


    def test_vps_cnh_photo_is_adopted_with_driver_and_private_to_company(self):
        from apps.fleet.models import Document, DocumentType, DocumentStatus, DriverCNHPhoto
        from apps.driverops.ownership import bind_graph
        from apps.driverops.models import RecordOwner
        from django.contrib.auth.models import Permission
        document = Document.objects.create(title='CNH legada',
            document_type=DocumentType.objects.create(name='CNH'),
            status=DocumentStatus.objects.create(name='Ativo'), created_by=self.manager)
        photo = DriverCNHPhoto.objects.create(driver=self.foreign_driver,
            document=document, image=b'portrait', confirmed_by=self.manager)
        bind_graph(Driver, self.foreign_driver.pk, self.other.pk)
        self.assertTrue(RecordOwner.objects.filter(model_label='fleet.drivercnhphoto',
            object_id=photo.pk, company=self.other).exists())
        self.manager.user_permissions.add(Permission.objects.get(codename='view_driver'))
        response = self.client.get(f'/motoristas/{self.foreign_driver.pk}/foto-cnh/', HTTP_HOST='gestao.test')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b'portrait', response.content)
