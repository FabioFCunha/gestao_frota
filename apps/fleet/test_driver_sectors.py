from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

from django.apps import apps
from django.db import connection
from django.template.loader import get_template
from django.test import TestCase

from apps.fleet.driver_scope import (
    apply_driver_sector_scope, apply_driver_vehicle_scope, sync_driver_sectors_from_bdts,
)
from apps.fleet.models import BDT, Driver, Sector, Vehicle, VehicleStatus
from apps.fleet.sync_bdt import BDTSyncWorker
from apps.ui.forms import DriverForm


class DriverSectorTests(TestCase):
    def setUp(self):
        self.adm, _ = Sector.objects.get_or_create(slug='adm', defaults={'name': 'ADM'})
        self.lei, _ = Sector.objects.get_or_create(slug='lei-seca', defaults={'name': 'Lei Seca'})
        self.adm_driver = Driver.objects.create(name='ADM', horus_user_id=uuid4())
        self.lei_driver = Driver.objects.create(name='Lei Seca')
        self.shared = Driver.objects.create(name='Ambos')
        self.adm_driver.sectors.add(self.adm)
        self.lei_driver.sectors.add(self.lei)
        self.shared.sectors.add(self.adm, self.lei)
        self.status = VehicleStatus.objects.create(name='Ativo teste')
        self.adm_vehicle = Vehicle.objects.create(status=self.status, sector=self.adm, horus_fleet_id=uuid4())

    def user(self, *slugs, superuser=False):
        return SimpleNamespace(is_authenticated=True, is_superuser=superuser,
                               sectors=Sector.objects.filter(slug__in=slugs))

    def test_single_sector_cannot_expand_using_query_parameter(self):
        qs = apply_driver_sector_scope(Driver.objects.all(), self.user('adm'), 'lei-seca')
        self.assertSetEqual(set(qs), {self.adm_driver, self.shared})

    def test_no_sector_has_no_driver_access(self):
        self.assertFalse(apply_driver_sector_scope(Driver.objects.all(), self.user()).exists())

    def test_superuser_filter_and_shared_driver_are_distinct(self):
        user = self.user(superuser=True)
        self.assertEqual(apply_driver_sector_scope(Driver.objects.all(), user).count(), 3)
        self.assertSetEqual(set(apply_driver_sector_scope(Driver.objects.all(), user, 'lei-seca')), {self.lei_driver, self.shared})

    def test_vehicle_scope_uses_selected_sector(self):
        self.assertFalse(apply_driver_vehicle_scope(Vehicle.objects.all(), self.user('adm', 'lei-seca'), 'lei-seca').exists())

    def test_bdt_classification_is_idempotent_and_keeps_both_sectors(self):
        BDT.objects.create(external_id=uuid4(), driver=self.lei_driver, horus_management_id=125)
        sync_driver_sectors_from_bdts(BDT.objects.all())
        sync_driver_sectors_from_bdts(BDT.objects.all())
        self.assertSetEqual(set(self.lei_driver.sectors.values_list('slug', flat=True)), {'adm', 'lei-seca'})

    def test_worker_classifies_open_bdt_before_mileage_projection(self):
        self.adm_driver.sectors.clear()
        result = BDTSyncWorker([{
            'id': str(uuid4()), 'fleet_id': str(self.adm_vehicle.horus_fleet_id),
            'user_id': str(self.adm_driver.horus_user_id), 'management_id': 125,
            'started_km': '10', 'ended_km': None,
        }]).run()
        self.assertEqual(result['falhas'], 0)
        self.assertTrue(self.adm_driver.sectors.filter(slug='adm').exists())

    def form_data(self, sector):
        return {'name': 'Motorista teste', 'sectors': [str(sector.pk)], 'active': 'True'}

    def test_form_rejects_sector_outside_user_scope(self):
        form = DriverForm(self.form_data(self.lei), user=self.user('adm'))
        self.assertFalse(form.is_valid())
        self.assertIn('sectors', form.errors)

    def test_edit_preserves_membership_hidden_from_user(self):
        form = DriverForm(self.form_data(self.adm), instance=self.shared, user=self.user('adm'))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertSetEqual(set(self.shared.sectors.values_list('slug', flat=True)), {'adm', 'lei-seca'})

    def test_new_manual_driver_saves_selected_sector(self):
        form = DriverForm(self.form_data(self.adm), user=self.user('adm'))
        self.assertTrue(form.is_valid(), form.errors)
        driver = form.save()
        self.assertTrue(driver.sectors.filter(slug='adm').exists())

    def test_migration_classifies_historical_bdts_and_legacy_drivers(self):
        legacy = Driver.objects.create(name='Legado sem BDT')
        BDT.objects.create(external_id=uuid4(), driver=self.adm_driver, horus_management_id=125)
        BDT.objects.create(external_id=uuid4(), driver=self.shared, horus_management_id=125)
        BDT.objects.create(external_id=uuid4(), driver=self.shared, horus_management_id=49)
        Driver.sectors.through.objects.all().delete()
        migration = import_module('apps.fleet.migrations.0042_driver_sectors')
        migration.populate_driver_sectors(apps, SimpleNamespace(connection=connection))
        self.assertSetEqual(set(self.adm_driver.sectors.values_list('slug', flat=True)), {'adm'})
        self.assertSetEqual(set(self.shared.sectors.values_list('slug', flat=True)), {'adm', 'lei-seca'})
        self.assertTrue(legacy.sectors.filter(slug='lei-seca').exists())

    def test_form_renders_allowed_sector_choices(self):
        html = str(DriverForm(user=self.user('adm'))["sectors"])
        self.assertIn('ADM', html)
        self.assertNotIn('Lei Seca', html)

    def test_driver_template_compiles(self):
        get_template('ui/driver_list.html')
