from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from apps.fleet.models import Driver, Vehicle, VehicleStatus, VehicleMileage, VehiclePlate, AuditLog
from .models import Company, Member, CompanyVehicle
from .management_forms import VehicleForm, MemberForm

BASE="/api/driver/management/"


class ManagementTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.admin=User.objects.create_superuser(username="administrador",password="Senha-segura-123")
        self.company=Company.objects.create(name="Minha empresa")
        self.foreign=Company.objects.create(name="Outra empresa")
        self.manager=User.objects.create_user(username="gestor",password="Senha-segura-123")
        self.manager_member=Member.objects.create(user=self.manager,company=self.company,role="manager")
        self.client.force_login(self.admin)

    def member_data(self, **extra):
        return {"action":"member","company":str(self.company.pk),"name":"Motorista de Teste",
                "username":"motorista-novo","role":"driver","password1":"Senha-nova-forte-123",
                "password2":"Senha-nova-forte-123",**extra}

    def vehicle(self,company=None,label="ABC1D23"):
        obj=CompanyVehicle.objects.create(company=company or self.company,label=label,
            vehicle=Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível")))
        return obj

    def test_platform_can_open_without_membership_and_create_company(self):
        self.assertEqual(self.client.get(BASE).status_code,200)
        response=self.client.post(BASE,{"action":"company","company_name":"Empresa nova","manager_name":"Gestor novo","email":"gestor@example.com","username":"gestor-novo","password1":"Senha-segura-321","password2":"Senha-segura-321"})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Company.objects.filter(name="Empresa nova").exists())
        self.assertTrue(AuditLog.objects.filter(action="EMPRESA CRIADA",user=self.admin).exists())
        response=self.client.post(BASE,{"action":"company","company_name":" empresa NOVA "})
        self.assertEqual(response.status_code,200)
        self.assertEqual(Company.objects.filter(name__iexact="Empresa nova").count(),1)

    def test_driver_access_is_created_with_all_links_and_no_elevated_privileges(self):
        vehicle=self.vehicle()
        self.client.force_login(self.manager)
        data=self.member_data(vehicles=[vehicle.pk])
        response=self.client.post(BASE,data)
        self.assertEqual(response.status_code,302)
        user=get_user_model().objects.get(username="motorista-novo")
        self.assertTrue(user.check_password(data["password1"]))
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        member=Member.objects.get(user=user)
        self.assertEqual(member.company,self.company)
        self.assertEqual(member.driver.name,"Motorista de Teste")
        self.assertTrue(vehicle.drivers.filter(pk=member.pk).exists())
        self.assertNotIn(data["password1"],str(list(AuditLog.objects.values())))
        self.client.force_login(user)
        self.assertEqual(self.client.get(BASE).status_code,403)

    def test_vehicle_creation_includes_plate_initial_km_and_company(self):
        self.client.force_login(self.manager)
        response=self.client.post(BASE,{"action":"vehicle","company":str(self.company.pk),
            "plate":"abc-1d23","label":"Carro de atendimento","mileage":"12000"})
        self.assertEqual(response.status_code,302)
        obj=CompanyVehicle.objects.get(label="Carro de atendimento")
        self.assertEqual(obj.company,self.company)
        self.assertEqual(VehiclePlate.objects.get(vehicle=obj.vehicle).plate,"ABC1D23")
        self.assertEqual(VehicleMileage.objects.get(vehicle=obj.vehicle).mileage,12000)
        response=self.client.post(BASE,{"action":"vehicle","plate":"ABC1D23"})
        self.assertEqual(response.status_code,200)
        self.assertIn("Esta placa já está cadastrada",str(response.context["vehicle_form"].errors))
        self.assertEqual(CompanyVehicle.objects.count(),1)

    def test_manager_cannot_read_or_mutate_another_company(self):
        foreign_vehicle=self.vehicle(company=self.foreign,label="SEGREDO OUTRA EMPRESA")
        self.client.force_login(self.manager)
        response=self.client.get(BASE+"?company="+str(self.foreign.pk))
        self.assertNotContains(response,"SEGREDO OUTRA EMPRESA")
        self.assertContains(response,"Minha empresa")
        self.assertEqual(self.client.post(BASE,{"action":"company","name":"Proibida"}).status_code,403)
        self.assertEqual(self.client.post(BASE,{"action":"assign","vehicle":foreign_vehicle.pk}).status_code,404)
        response=self.client.post(BASE,self.member_data(company=str(self.foreign.pk)))
        self.assertEqual(response.status_code,302)
        self.assertEqual(Member.objects.get(user__username="motorista-novo").company,self.company)

    def test_foreign_driver_and_vehicle_choices_are_rejected(self):
        foreign_vehicle=self.vehicle(company=self.foreign)
        other=get_user_model().objects.create_user(username="outro")
        foreign_driver=Member.objects.create(company=self.foreign,user=other,role="driver",
            driver=Driver.objects.create(name="Outro motorista"))
        self.client.force_login(self.manager)
        response=self.client.post(BASE,self.member_data(vehicles=[foreign_vehicle.pk]))
        self.assertEqual(response.status_code,200)
        self.assertFalse(get_user_model().objects.filter(username="motorista-novo").exists())
        response=self.client.post(BASE,{"action":"vehicle","plate":"DEF2G34","drivers":[foreign_driver.pk]})
        self.assertEqual(response.status_code,200)
        self.assertFalse(VehiclePlate.objects.filter(plate="DEF2G34").exists())

    def test_can_link_existing_vehicle_and_driver_without_duplicate_records(self):
        vehicle=Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível"))
        driver=Driver.objects.create(name="Motorista já cadastrado")
        from apps.driverops.ownership import bind_graph
        bind_graph(Driver,driver.pk,self.company.pk)
        self.client.force_login(self.manager)
        response=self.client.post(BASE,self.member_data(existing_driver=str(driver.pk)))
        self.assertEqual(response.status_code,302)
        member=Member.objects.get(user__username="motorista-novo")
        self.assertEqual(member.driver,driver)
        self.client.force_login(self.admin)
        response=self.client.post(BASE,{"action":"vehicle","company":str(self.company.pk),
            "existing_vehicle":str(vehicle.pk),"label":"Veículo existente","drivers":[member.pk]})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Vehicle.objects.count(),1)
        self.assertEqual(Driver.objects.count(),1)
        self.assertTrue(CompanyVehicle.objects.get(vehicle=vehicle).drivers.filter(pk=member.pk).exists())
        self.client.force_login(self.manager)
        self.assertNotIn("existing_vehicle",VehicleForm(company=self.company).fields)
        self.assertIn("existing_driver",MemberForm(company=self.company).fields)

    def test_self_manager_link_does_not_move_existing_membership(self):
        self.assertEqual(self.client.post(BASE,{"action":"use_company","company":str(self.company.pk)}).status_code,302)
        self.assertEqual(Member.objects.get(user=self.admin).company,self.company)
        self.client.post(BASE,{"action":"use_company","company":str(self.foreign.pk)})
        self.assertEqual(Member.objects.get(user=self.admin).company,self.company)

    def test_csrf_login_and_malformed_vehicle(self):
        anonymous=Client()
        self.assertEqual(anonymous.get(BASE).status_code,302)
        strict=Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        self.assertEqual(strict.post(BASE,{"action":"company","name":"Sem CSRF"}).status_code,403)
        self.assertEqual(self.client.post(BASE,{"action":"assign","vehicle":"bad","company":str(self.company.pk)}).status_code,400)
        response=self.client.get("/api/driver/app/")
        self.assertRedirects(response,BASE,fetch_redirect_response=False)
