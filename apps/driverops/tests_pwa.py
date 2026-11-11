import io
import json
import uuid
from PIL import Image
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.fleet.models import Driver, Vehicle, VehicleStatus
from .models import Company, Member, CompanyVehicle
from .views import CHECKS


class PWATests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pwa", password="Teste-123-seguro")
        company = Company.objects.create(name="Empresa PWA")
        self.member = Member.objects.create(company=company, user=self.user, role="driver",
                                           driver=Driver.objects.create(name="Motorista PWA"))
        self.vehicle = CompanyVehicle.objects.create(company=company,
            vehicle=Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível PWA")),
            label="PWA1A23")
        self.vehicle.drivers.add(self.member)

    def test_manifest_icons_and_service_worker_are_public_and_scoped(self):
        manifest = self.client.get("/api/driver/app/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["scope"], "/api/driver/app/")
        for size in (192, 512):
            icon = self.client.get(f"/api/driver/app/icon-{size}.png")
            self.assertEqual(Image.open(io.BytesIO(icon.content)).size, (size, size))
        self.assertEqual(self.client.get("/api/driver/app/sw.js").status_code, 200)
        self.assertEqual(self.client.get("/api/driver/app/not-found.js").status_code, 404)
        self.assertEqual(self.client.get("/api/driver/app/").status_code, 302)

    def test_browser_session_requires_csrf_for_mutations_and_signout(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get("/api/driver/app/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", client.cookies)
        token = client.cookies["csrftoken"].value
        body = {"vehicle": self.vehicle.pk, "destinations": ["Destino A", "Base"]}
        headers = {"HTTP_IDEMPOTENCY_KEY":str(uuid.uuid4())}
        self.assertEqual(client.post("/api/driver/trips/", json.dumps(body),
                                    content_type="application/json", **headers).status_code, 403)
        headers["HTTP_X_CSRFTOKEN"] = token
        result = client.post("/api/driver/trips/", json.dumps(body), content_type="application/json", **headers)
        self.assertEqual(result.status_code, 200)
        trip = result.json()
        data = {"leg":trip["legs"][0]["id"], "km":100,
                "checklist":{key:{"status":"ok","note":""} for key in CHECKS}}
        headers["HTTP_IDEMPOTENCY_KEY"] = str(uuid.uuid4())
        path = f"/api/driver/trips/{trip['id']}/start/"
        self.assertEqual(client.post(path,json.dumps(data),content_type="application/json").status_code,403)
        self.assertEqual(client.post(path,json.dumps(data),content_type="application/json",**headers).status_code,200)
        self.assertEqual(client.post("/api/driver/app/signout/", HTTP_X_CSRFTOKEN=token).status_code,400)

    def test_shell_has_no_personal_data_or_inline_scripts(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/driver/app/")
        self.assertEqual(response["Cache-Control"],"private, no-store")
        self.assertNotContains(response,"Empresa PWA")
        self.assertNotContains(response,"Motorista PWA")
        self.assertContains(response,'src="app.js"')
        self.assertIn("script-src 'self'",response["Content-Security-Policy"])
