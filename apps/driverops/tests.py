import io
import uuid
from datetime import timedelta
from PIL import Image
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.cache import cache
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from apps.fleet.models import Driver, Vehicle, VehicleStatus, VehicleMileage, VehicleExitOrder
from .models import Company, Member, CompanyVehicle, Trip, Leg, Location, Event, DeviceSession
from .views import CHECKS


class DriverAppTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.company = Company.objects.create(name="Empresa A")
        self.other = Company.objects.create(name="Empresa B")
        self.user = get_user_model().objects.create_user(username="motorista", password="Teste-seguro-123")
        self.driver = Driver.objects.create(name="Motorista")
        self.member = Member.objects.create(company=self.company, user=self.user, driver=self.driver, role=Member.DRIVER)
        self.vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível"))
        self.assignment = CompanyVehicle.objects.create(company=self.company, vehicle=self.vehicle, label="ABC1D23")
        self.assignment.drivers.add(self.member)
        self.login()

    def login(self):
        response = self.client.post("/api/driver/login/", {"username":"motorista", "password":"Teste-seguro-123"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["token"])

    def post(self, path, data, key=None):
        return self.client.post("/api/driver/" + path, data, format="json",
                                HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    def checks(self):
        return {key: {"status":"ok", "note":""} for key in CHECKS}

    def open(self, destinations=None, **extra):
        response = self.post("trips/", {"vehicle":self.assignment.pk,
                             "destinations":destinations or ["Destino A", "Retorno à base"], **extra})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def start(self, trip, index=0, km=100):
        response = self.post(f"trips/{trip['id']}/start/", {"leg":trip["legs"][index]["id"], "km":km,"checklist":self.checks()})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def finish(self, trip, index=0, km=120, key=None):
        return self.post(f"trips/{trip['id']}/finish/", {"leg":trip["legs"][index]["id"],"km":km,"checklist":self.checks()}, key)

    def test_full_trip_waiting_return_and_os_remains_open(self):
        order = VehicleExitOrder.objects.create(number="OS-TESTE",vehicle=self.vehicle,driver=self.driver,
            departed_at=timezone.now(),destination="Destino A",reason="Serviço",opened_by=self.user)
        trip = self.open(exit_order=str(order.pk))
        trip = self.start(trip)
        response = self.finish(trip)
        self.assertEqual(response.status_code,200,response.data)
        self.assertIsNone(response.data["closed_at"])
        self.assertFalse(Leg.objects.filter(trip_id=trip["id"],started_at__isnull=False,ended_at=None).exists())
        trip = self.start(response.data,1,120)
        response = self.finish(trip,1,150)
        self.assertIsNotNone(response.data["closed_at"])
        self.assertEqual(response.data["legs"][1]["distance_km"],30)
        self.assertEqual(VehicleMileage.objects.filter(vehicle=self.vehicle).count(),2)
        order.refresh_from_db()
        self.assertEqual(order.state,"PENDING")
        self.assertEqual(Event.objects.filter(trip_id=trip["id"],action="trecho_concluido",user=self.user).count(),2)

    def test_duplicate_commands_do_not_repeat_trip_or_mileage(self):
        key=uuid.uuid4()
        payload={"vehicle":self.assignment.pk,"destinations":["Destino"]}
        a=self.post("trips/",payload,key)
        b=self.post("trips/",payload,key)
        self.assertEqual(a.data,b.data)
        self.assertEqual(Trip.objects.count(),1)
        trip=self.start(a.data)
        key=uuid.uuid4()
        a=self.finish(trip,key=key);b=self.finish(trip,key=key)
        self.assertEqual(a.data,b.data)
        self.assertEqual(VehicleMileage.objects.count(),1)
        changed=self.post("trips/",{"vehicle":self.assignment.pk,"destinations":["Outro"]},key)
        self.assertEqual(changed.status_code,400)

    def test_order_km_checks_and_parallel_open_rejected(self):
        trip=self.open()
        result=self.post(f"trips/{trip['id']}/start/",{"leg":trip["legs"][1]["id"],"km":100,"checklist":self.checks()})
        self.assertEqual(result.status_code,400)
        result=self.post("trips/",{"vehicle":self.assignment.pk,"destinations":["Outro"]})
        self.assertEqual(result.status_code,400)
        bad=self.checks();bad["pneus"]={"status":"problem","note":""}
        result=self.post(f"trips/{trip['id']}/start/",{"leg":trip["legs"][0]["id"],"km":100,"checklist":bad})
        self.assertEqual(result.status_code,400)
        trip=self.start(trip)
        self.assertEqual(self.finish(trip,km=99).status_code,400)
        self.assertEqual(self.post(f"trips/{trip['id']}/close/",{"reason":"Encerrar agora"}).status_code,400)

    def test_cross_company_access_and_foreign_vehicle_are_denied(self):
        trip=self.open()
        other_user=get_user_model().objects.create_user(username="outro",password="Teste-seguro-123")
        Member.objects.create(company=self.other,user=other_user,role=Member.MANAGER)
        self.client.force_authenticate(user=other_user)
        for suffix in ("", "tracking/"):
            self.assertEqual(self.client.get(f"/api/driver/trips/{trip['id']}/{suffix}").status_code,403)
        self.assertEqual(self.client.get("/api/driver/trips/").data,[])
        self.client.force_authenticate(user=self.user)
        self.assignment.company=self.other;self.assignment.save()
        self.assertEqual(self.post("trips/",{"vehicle":self.assignment.pk,"destinations":["Outro"]}).status_code,403)

    def test_session_expiry_deactivation_and_logout(self):
        DeviceSession.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/driver/bootstrap/").status_code,401)
        self.login()
        self.member.active=False;self.member.save()
        self.assertEqual(self.client.get("/api/driver/bootstrap/").status_code,401)
        self.member.active=True;self.member.save()
        self.login()
        self.assertEqual(self.post("logout/",{}).status_code,204)
        self.assertEqual(self.client.get("/api/driver/bootstrap/").status_code,401)

    def test_delayed_gps_idempotency_and_interval(self):
        trip=self.start(self.open())
        leg=Leg.objects.get(pk=trip["legs"][0]["id"])
        point={"id":str(uuid.uuid4()),"measured_at":timezone.now().isoformat(),
               "latitude":-22.9,"longitude":-43.2,"accuracy":12}
        path=f"trips/{trip['id']}/legs/{leg.pk}/locations/"
        self.assertEqual(self.finish(trip).status_code,200)
        self.assertEqual(self.post(path,{"points":[point]}).status_code,200)
        self.assertEqual(self.post(path,{"points":[point]}).status_code,200)
        self.assertEqual(Location.objects.count(),1)
        point["id"]=str(uuid.uuid4());point["measured_at"]=(leg.started_at-timedelta(hours=1)).isoformat()
        result=self.post(path,{"points":[point]})
        self.assertEqual(result.status_code,200)
        self.assertEqual(len(result.data["rejected"]),1)
        point["measured_at"]=timezone.now().isoformat();point["latitude"]=float("inf")
        self.assertEqual(self.post(path,{"points":[{**point,"latitude":999}]}).status_code,400)

    def test_early_close_requires_reason_and_no_active_leg(self):
        trip=self.open()
        self.assertEqual(self.post(f"trips/{trip['id']}/close/",{"reason":"x"}).status_code,400)
        response=self.post(f"trips/{trip['id']}/close/",{"reason":"Serviço cancelado"})
        self.assertIsNotNone(response.data["closed_at"])
        self.assertEqual(self.post(f"trips/{trip['id']}/append/",{"destinations":["Destino"]}).status_code,400)

    def test_protected_photo_and_manager_portal(self):
        trip=self.open()
        output=io.BytesIO();Image.new("RGB",(20,20)).save(output,format="JPEG")
        response=self.client.post(f"/api/driver/trips/{trip['id']}/legs/{trip['legs'][0]['id']}/photos/",
            {"moment":"departure","image":SimpleUploadedFile("photo.jpg",output.getvalue(),content_type="image/jpeg")},format="multipart")
        self.assertEqual(response.status_code,201,response.data)
        photo_id=response.data["id"]
        self.assertEqual(self.client.get(f"/api/driver/photos/{photo_id}/").status_code,200)
        self.client.credentials()
        self.assertEqual(self.client.get(f"/api/driver/photos/{photo_id}/").status_code,401)
        manager=get_user_model().objects.create_user(username="gestor",password="Teste-seguro-123")
        Member.objects.create(company=self.company,user=manager,role=Member.MANAGER)
        self.client.force_login(manager)
        self.assertEqual(self.client.get("/api/driver/panel/").status_code,200)
        self.assertEqual(self.client.get("/api/driver/trips/").status_code,200)

    def test_invalid_input_is_a_validation_error(self):
        self.assertEqual(self.post("trips/",{"vehicle":"abc","destinations":["Destino"]}).status_code,400)
        self.assertEqual(self.post("trips/",{"vehicle":self.assignment.pk,"destinations":["Destino"],"exit_order":"bad"}).status_code,400)

    def test_company_member_cannot_enter_unscoped_legacy_pages(self):
        self.client.credentials()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/").status_code,403)
        self.assertEqual(self.client.get("/api/vehicles/").status_code,403)
        self.assertEqual(self.client.get("/api/driver/bootstrap/").status_code,200)

    def test_login_throttle(self):
        self.client.credentials()
        for _ in range(9):
            response=self.client.post("/api/driver/login/",{"username":"motorista","password":"errada"},format="json")
            self.assertEqual(response.status_code,401)
        response=self.client.post("/api/driver/login/",{"username":"motorista","password":"errada"},format="json")
        self.assertEqual(response.status_code,429)

    def test_password_change_revokes_existing_token(self):
        self.user.set_password("Nova-senha-segura-456")
        self.user.save()
        self.assertEqual(self.client.get("/api/driver/bootstrap/").status_code,401)
