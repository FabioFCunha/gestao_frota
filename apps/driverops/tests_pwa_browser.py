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

    def test_simple_management_creates_company_driver_and_vehicle(self):
        from playwright.sync_api import sync_playwright, expect
        admin = get_user_model().objects.create_superuser(username="platform-admin",password="Senha-segura-123")
        self.client.force_login(admin)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context()
            context.add_cookies([{"name":"sessionid","value":self.client.cookies["sessionid"].value,
                                 "url":self.live_server_url,"httpOnly":True,"sameSite":"Lax"}])
            page=context.new_page()
            page.goto(self.live_server_url+"/api/driver/management/")
            page.locator("#company-form input[name=name]").fill("Empresa Piloto")
            page.get_by_role("button",name="Salvar empresa",exact=True).click()
            expect(page.get_by_role("heading",name="Empresa Piloto",exact=True)).to_be_visible()
            member_form=page.locator("#member-form")
            member_form.locator("input[name=name]").fill("Motorista do Piloto")
            member_form.locator("input[name=username]").fill("motorista.piloto")
            member_form.locator("input[name=password1]").fill("Senha-forte-piloto-123")
            member_form.locator("input[name=password2]").fill("Senha-forte-piloto-123")
            member_form.get_by_role("button",name="Criar acesso",exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Acesso criado")
            vehicle_form=page.locator("#vehicle-form")
            vehicle_form.locator("input[name=plate]").fill("ABC1D23")
            vehicle_form.locator("input[name=label]").fill("Carro do piloto")
            vehicle_form.locator("input[name=mileage]").fill("1000")
            vehicle_form.locator("input[type=checkbox]").check()
            vehicle_form.get_by_role("button",name="Salvar veículo",exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Veículo cadastrado")
            expect(page.get_by_text("Motorista do Piloto",exact=False).first).to_be_visible()
            browser.close()
        member=Member.objects.get(user__username="motorista.piloto")
        self.assertEqual(member.company.name,"Empresa Piloto")
        self.assertTrue(CompanyVehicle.objects.get(label="Carro do piloto").drivers.filter(pk=member.pk).exists())
