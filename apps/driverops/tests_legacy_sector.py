import io
import uuid

from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from apps.fleet.models import BDT, Driver, Sector, Vehicle, VehicleStatus
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
from .models import Company, CompanyVehicle, RecordOwner


@override_settings(CENTRAL_USER_MANAGEMENT=True)
class LegacySectorAdoptionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Empresa de frota')
        self.adm = Sector.objects.get(slug='adm')
        self.other = Sector.objects.get(slug='lei-seca')
        status = VehicleStatus.objects.create(name='Disponível para migração')
        self.vehicle = Vehicle.objects.create(status=status, sector=self.adm)
        self.inactive = Vehicle.objects.create(status=status, sector=self.adm, active=False)
        self.foreign = Vehicle.objects.create(status=status, sector=self.other)
        self.unassigned = Vehicle.objects.create(status=status)
        self.driver = Driver.objects.create(name='Motorista compartilhado')
        self.driver.sectors.add(self.adm, self.other)
        self.bdt = BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.vehicle,
            driver=self.driver, horus_management_id=125)
        self.foreign_bdt = BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.foreign,
            driver=self.driver, horus_management_id=49)

    def adopt(self, **options):
        call_command('adopt_legacy_sector', sector='adm', company=str(self.company.pk),
            stdout=io.StringIO(), **options)

    def test_simulation_rolls_back_all_links_and_temporary_company(self):
        self.adopt()
        self.assertFalse(RecordOwner.objects.exists())
        self.assertFalse(CompanyVehicle.objects.exists())
        call_command('adopt_legacy_sector', sector='adm', stdout=io.StringIO())
        self.assertEqual(Company.objects.count(), 1)
        self.assertFalse(RecordOwner.objects.exists())

    def test_sector_apply_keeps_inactive_history_and_shared_driver_trips_separate(self):
        self.adopt(apply=True)
        self.adopt(apply=True)  # Safe to repeat: no duplicate links or loss of activity flags.
        self.assertEqual(CompanyVehicle.objects.filter(company=self.company, active=True).count(), 1)
        self.assertEqual(CompanyVehicle.objects.filter(company=self.company, active=False).count(), 1)
        token = set_scope(Scope(company_id=self.company.pk))
        try:
            self.assertSetEqual(set(Vehicle.objects.values_list('pk', flat=True)), {self.vehicle.pk, self.inactive.pk})
            self.assertSetEqual(set(BDT.objects.values_list('pk', flat=True)), {self.bdt.pk})
            self.assertEqual(Driver.objects.get().pk, self.driver.pk)
        finally:
            reset_scope(token)
        self.assertEqual(BDT.objects.count(), 2)
        self.assertEqual(Driver.objects.count(), 1)

    def test_conflicting_source_rolls_back_entire_adoption(self):
        BDT.objects.filter(pk=self.bdt.pk).update(horus_management_id=49)
        with self.assertRaises(CommandError):
            self.adopt(apply=True)
        self.assertFalse(RecordOwner.objects.exists())
        self.assertFalse(CompanyVehicle.objects.exists())

    def test_later_foreign_sync_does_not_infer_company_from_shared_driver(self):
        self.adopt(apply=True)
        later = BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.foreign,
            driver=self.driver, horus_management_id=49)
        self.assertFalse(RecordOwner.objects.filter(object_id__in=[later.pk, self.foreign.pk]).exists())
        with self.assertRaises(PermissionDenied):
            BDT.objects.create(external_id=uuid.uuid4(), vehicle=self.vehicle,
                driver=self.driver, horus_management_id=49)

    def test_apply_requires_explicit_company(self):
        with self.assertRaises(CommandError):
            call_command('adopt_legacy_sector', sector='adm', apply=True, stdout=io.StringIO())

    def test_document_shared_with_foreign_vehicle_aborts_without_partial_claims(self):
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.fleet.models import Document, DocumentType, DocumentStatus, DocumentRelation
        user = get_user_model().objects.create_user(username='proprietario')
        document = Document.objects.create(title='Documento com vínculos mistos',
            document_type=DocumentType.objects.create(name='Contrato'),
            status=DocumentStatus.objects.create(name='Ativo'), created_by=user)
        for vehicle in (self.vehicle, self.foreign):
            DocumentRelation.objects.create(document=document, content_type=ContentType.objects.get_for_model(Vehicle),
                object_id=vehicle.pk, created_by=user)
        with self.assertRaises(CommandError):
            self.adopt(apply=True)
        self.assertFalse(RecordOwner.objects.exists())
        self.assertFalse(CompanyVehicle.objects.exists())
