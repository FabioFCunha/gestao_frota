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
            page.locator("#destinations").fill("Destino A\nRetorno à base")
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
            member = Member.objects.get(user__username='gestor.piloto')
            self.client.force_login(member.user)
            context.clear_cookies()
            context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value,
                                 "url": self.live_server_url, "httpOnly": True, "sameSite": "Lax"}])
            page.goto(self.live_server_url + '/')
            expect(page.locator('.sb-brand')).to_contain_text('Empresa Piloto')
            expect(page.locator('.sb-brand')).to_contain_text('TRANSFROTA')
            for text, path in [('Veículos', '/veiculos/'), ('Motoristas', '/motoristas/')]:
                page.locator('.sb-nav').get_by_text(text, exact=True).click()
                expect(page).to_have_url(self.live_server_url + path)
            page.goto(self.live_server_url + '/api/driver/management/')
            expect(page.get_by_role('link', name='Cadastrar motorista pela CNH')).to_be_visible()
            expect(page.get_by_role('link', name='Cadastrar veículo pelo CRLV')).to_be_visible()
            browser.close()
        self.assertEqual(member.company.name, 'Empresa Piloto')
        self.assertFalse(member.user.is_staff)
