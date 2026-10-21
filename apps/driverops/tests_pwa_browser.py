import os
import unittest
from django.test import LiveServerTestCase
from django.contrib.auth import get_user_model
from apps.fleet.models import Driver, Vehicle, VehicleStatus
from .models import Company, Member, CompanyVehicle, Trip, Location


@unittest.skipUnless(os.getenv("PWA_BROWSER_TESTS") == "1", "Ative PWA_BROWSER_TESTS com Chromium instalado.")
class PWABrowserTests(LiveServerTestCase):
    def test_open_two_legs_and_close_using_session_cookie(self):
        from playwright.sync_api import sync_playwright, expect
        user = get_user_model().objects.create_user(username="pwa-browser", password="Teste-123-seguro")
        company = Company.objects.create(name="Empresa navegador")
        member = Member.objects.create(company=company,user=user,role="driver",
                                       driver=Driver.objects.create(name="Motorista navegador"))
        vehicle = CompanyVehicle.objects.create(company=company,
            vehicle=Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível navegador")),
            label="TESTE1")
        vehicle.drivers.add(member)
        self.client.force_login(user)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(permissions=["geolocation"],
                                        geolocation={"latitude":-22.9,"longitude":-43.2})
            context.add_cookies([{"name":"sessionid","value":self.client.cookies["sessionid"].value,
                                 "url":self.live_server_url,"httpOnly":True,"sameSite":"Lax"}])
            page=context.new_page()
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(self.live_server_url+"/api/driver/app/")
            expect(page.locator("#identity")).to_contain_text("Empresa navegador")
            page.route("**/api/driver/addresses/**", lambda route: route.fulfill(json={"results":[
                {"label":"Praça XV, Rio de Janeiro", "latitude":-22.9, "longitude":-43.17}]}))
            page.locator("#destinations").fill("Praça XV Rio")
            page.get_by_role("button", name="Praça XV, Rio de Janeiro", exact=True).click()
            expect(page.locator("#destinations")).to_have_value("Praça XV, Rio de Janeiro")
            page.locator("#destinations").fill("Praça XV, Rio de Janeiro\nRetorno à base")
            dropped = [False]
            def lose_first_response(route):
                if route.request.method == "POST" and not dropped[0]:
                    response = route.fetch()
                    self.assertEqual(response.status, 200)
                    dropped[0] = True
                    response.dispose()
                    route.abort()
                else:
                    route.continue_()
            page.route("**/api/driver/trips/", lose_first_response)
            page.get_by_role("button",name="Abrir BDT",exact=True).click()
            expect(page.locator("#pending")).to_be_visible()
            page.get_by_role("button",name="Sincronizar",exact=True).click()
            expect(page.locator("#message")).to_contain_text("Sincronização concluída")
            page.unroute("**/api/driver/trips/", lose_first_response)
            for index,(initial,final) in enumerate(((100,120),(120,150))):
                expect(page.locator("#transition-submit")).to_have_text("Iniciar trecho")
                page.locator("#km").fill(str(initial))
                for select in page.locator("#checklist select").all():
                    select.select_option("ok")
                page.locator("#transition-submit").click()
                expect(page.locator("#transition-submit")).to_have_text("Concluir trecho")
                expect(page.locator("#google")).to_have_attribute("href",__import__("re").compile("https://www.google.com/maps/dir/.*"))
                page.locator("#km").fill(str(final))
                for select in page.locator("#checklist select").all():
                    select.select_option("ok")
                page.locator("#transition-submit").click()
                expect(page.locator("#message")).to_contain_text("BDT encerrado" if index else "Chegada salva")
            expect(page.locator("#create")).to_be_visible()
            self.assertEqual(errors,[])
            browser.close()
        self.assertEqual(Trip.objects.filter(member=member).count(),1)
        self.assertIsNotNone(Trip.objects.get(member=member).closed_at)
        self.assertEqual(Trip.objects.get(member=member).legs.count(),2)
        self.assertEqual(Trip.objects.get(member=member).legs.first().destination_latitude, -22.9)

    def test_platform_creates_company_and_manager_opens_full_fleet_ui(self):
        from playwright.sync_api import sync_playwright, expect
        admin = get_user_model().objects.create_superuser(username="platform-admin", password="Senha-segura-123")
        self.client.force_login(admin)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value,
                                 "url": self.live_server_url, "httpOnly": True, "sameSite": "Lax"}])
            page = context.new_page()
            page.goto(self.live_server_url + "/api/driver/management/")
            form = page.locator('#company-form')
            form.locator('input[name=company_name]').fill('Empresa Piloto')
            form.locator('input[name=manager_name]').fill('Gestor do Piloto')
            form.locator('input[name=email]').fill('gestor@example.com')
            form.locator('input[name=username]').fill('gestor.piloto')
            for field in ('password1', 'password2'):
                form.locator(f'input[name={field}]').fill('Senha-forte-piloto-123')
            form.get_by_role('button', name='Criar empresa e gestor').click()
            expect(page.get_by_role('status')).to_contain_text('Empresa e gestor criados')
            context.clear_cookies()
            page.goto(self.live_server_url + '/entrar/')
            page.locator('input[name=username]').fill('gestor.piloto')
            page.locator('input[name=password]').fill('Senha-forte-piloto-123')
            page.locator('#wwLoginForm button[type=submit]').click()
            expect(page.locator('.sb-brand')).to_contain_text('Empresa Piloto')
            expect(page.locator('.sb-brand')).to_contain_text('TRANSFROTA')
            for text, path in [('Veículos', '/veiculos/'), ('Motoristas', '/motoristas/')]:
                page.locator('.sb-nav').get_by_text(text, exact=True).click()
                expect(page).to_have_url(self.live_server_url + path)
            page.goto(self.live_server_url + '/api/driver/management/')
            expect(page.get_by_role('link', name='Cadastrar motorista pela CNH')).to_be_visible()
            expect(page.get_by_role('link', name='Cadastrar veículo pelo CRLV')).to_be_visible()
            browser.close()
        member = Member.objects.get(user__username='gestor.piloto')
        self.assertEqual(member.company.name, 'Empresa Piloto')
        self.assertFalse(member.user.is_staff)

    def test_main_users_create_driver_that_logs_into_operational_host(self):
        from django.conf import settings
        from django.test import override_settings
        from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
        from playwright.sync_api import sync_playwright, expect
        main_origin = self.live_server_url
        app_origin = main_origin.replace('localhost', '127.0.0.1')
        middleware = list(settings.MIDDLEWARE)
        middleware.insert(middleware.index('apps.driverops.middleware.CompanyBoundaryMiddleware'), 'apps.driverops.surfaces.AppSurfaceMiddleware')
        manager = get_user_model().objects.create_user(username='gestor.central@example.com', email='gestor.central@example.com', password='Senha-gestor-987')
        company = Company.objects.create(name='Empresa central navegador')
        Member.objects.create(user=manager, company=company, role=Member.MANAGER)
        token = set_scope(Scope(company_id=company.pk, actor_id=manager.pk))
        try:
            driver = Driver.objects.create(name='Motorista CNH navegador')
            vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name='Disponível'))
            vehicle_key = CompanyVehicle.objects.get(vehicle=vehicle).pk
            driver_key = str(driver.pk)
        finally:
            reset_scope(token)
        with override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.company_urls',
            MANAGEMENT_ORIGIN=main_origin, DRIVER_APP_ORIGIN=app_origin,
            MIDDLEWARE=middleware, ALLOWED_HOSTS=['localhost','127.0.0.1','testserver'],
            CSRF_TRUSTED_ORIGINS=[main_origin, app_origin]):
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context()
                page = context.new_page()
                page.goto(main_origin+'/entrar/')
                page.locator('input[name=username]').fill(manager.email)
                page.locator('input[name=password]').fill('Senha-gestor-987')
                page.locator('#wwLoginForm button[type=submit]').click()
                expect(page.locator('.sb-brand')).to_contain_text(company.name)
                page.goto(main_origin+'/usuarios/novo/')
                page.locator('input[name=first_name]').fill('Motorista integração')
                page.locator('input[name=email]').fill('motorista.central@example.com')
                page.locator('select[name=role]').select_option('driver')
                page.locator('select[name=driver]').select_option(driver_key)
                expect(page.locator('input[name=vehicles]')).to_have_count(0)
                page.locator('input[name=initial_password]').fill('Inicial-segura-987')
                page.locator('input[name=initial_password_confirmation]').fill('Inicial-segura-987')
                page.get_by_role('button', name='Salvar usuário', exact=True).click()
                expect(page).to_have_url(main_origin+'/usuarios/')
                expect(page.get_by_text('motorista.central@example.com', exact=True)).to_be_visible()
                page.goto(main_origin+'/ordens-saida/nova/')
                page.locator('select[name=vehicle]').select_option(str(vehicle.pk))
                page.locator('select[name=driver]').select_option(driver_key)
                page.locator('input[name=departed_at]').fill('2026-10-21T10:00')
                page.locator('input[name=destination]').fill('Destino da OS navegador')
                page.locator('textarea[name=reason]').fill('Serviço')
                page.get_by_role('button', name='Abrir OS', exact=True).click()
                expect(page.get_by_text('Destino da OS navegador', exact=True).first).to_be_visible()
                app_page = context.new_page()
                app_page.goto(app_origin+'/entrar/')
                app_page.locator('input[name=username]').fill('motorista.central@example.com')
                app_page.locator('input[name=password]').fill('Inicial-segura-987')
                app_page.locator('#wwLoginForm button[type=submit]').click()
                expect(app_page.get_by_role('heading', name='Alterar senha')).to_be_visible()
                app_page.locator('input[name=old_password]').fill('Inicial-segura-987')
                app_page.locator('input[name=new_password1]').fill('Pessoal-segura-987')
                app_page.locator('input[name=new_password2]').fill('Pessoal-segura-987')
                app_page.get_by_role('button', name='Salvar nova senha').click()
                expect(app_page.locator('#identity')).to_contain_text(company.name)
                expect(app_page.locator('#vehicle option')).to_have_count(1)
                expect(app_page.locator('#order')).to_have_attribute('required', '')
                app_page.locator('#order').select_option(index=1)
                expect(app_page.locator('#destinations')).to_have_value('Destino da OS navegador')
                expect(app_page.locator('.sidebar')).to_have_count(0)
                browser.close()
        member = Member.objects.get(user__email='motorista.central@example.com')
        self.assertEqual(member.driver_id, driver.pk)
        self.assertFalse(CompanyVehicle.objects.get(pk=vehicle_key).drivers.filter(pk=member.pk).exists())
