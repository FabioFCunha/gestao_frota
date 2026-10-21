import uuid
from io import StringIO
from datetime import date
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from apps.fleet.models import (Driver, BDT, Vehicle, VehicleStatus, VehicleDriverAssignment,
                               Document, DocumentType, DocumentStatus, DocumentRelation, AuditLog)
from .models import Company, RecordOwner


class CNHReconciliationTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username='owner', email='owner@example.com', password='test-only')
        self.company = Company.objects.create(name='SEGOV teste')
        self.source = Driver.objects.create(name='Motorista Teste', cpf='123.456.789-01',
            cnh_number='11111111111', cnh_category='D', cnh_expiration=date(2034, 4, 14))
        self.target = Driver.objects.create(name='MOTORISTA TESTE', horus_user_id=uuid.uuid4())
        RecordOwner.objects.create(company=self.company, model_label='fleet.driver', object_id=self.target.pk)
        self.document = Document.objects.create(title='CNH teste',
            document_type=DocumentType.objects.get_or_create(name='CNH')[0],
            status=DocumentStatus.objects.get_or_create(name='Recebido')[0], created_by=self.actor)
        self.link = DocumentRelation.objects.create(document=self.document,
            content_type=ContentType.objects.get_for_model(Driver), object_id=self.source.pk, created_by=self.actor)
        AuditLog.objects.create(module='cnh', action='CNH CADASTRADA A PARTIR DE PDF',
            entity_type='document', entity_id=self.document.pk,
            new_values={'driver_id': str(self.source.pk), 'form_values': {'father_name': 'Pai teste'}})
        self.vehicle = Vehicle.objects.create(status=VehicleStatus.objects.get_or_create(name='Ativo')[0])
        self.assignment = VehicleDriverAssignment.objects.create(vehicle=self.vehicle, driver=self.target)
        self.bdt = BDT.objects.create(external_id=uuid.uuid4(), driver=self.target)

    def command(self, **kwargs):
        return call_command('reconcile_driver_cnh', source=self.source.pk, target=self.target.pk,
            company=self.company.pk, document=self.document.pk, actor=self.actor.email, stdout=StringIO(), **kwargs)

    def test_dry_run_rolls_back_identity_links_and_ownership(self):
        self.command()
        self.source.refresh_from_db()
        self.target.refresh_from_db()
        self.link.refresh_from_db()
        self.assertTrue(self.source.active)
        self.assertEqual(self.source.cnh_number, '11111111111')
        self.assertEqual(self.target.cnh_number, '')
        self.assertEqual(self.link.object_id, self.source.pk)
        self.assertFalse(RecordOwner.objects.filter(model_label='fleet.document', object_id=self.document.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='RECONCILIAÇÃO CNH').exists())

    def test_apply_preserves_horus_operation_document_and_audit(self):
        self.command(apply=True)
        self.source.refresh_from_db()
        self.target.refresh_from_db()
        self.link.refresh_from_db()
        self.assertFalse(self.source.active)
        self.assertEqual(self.source.cpf, '')
        self.assertEqual(self.target.cpf, '123.456.789-01')
        self.assertEqual(self.target.cnh_expiration, date(2034, 4, 14))
        self.assertEqual(self.link.object_id, self.target.pk)
        self.assertEqual(BDT.objects.get(pk=self.bdt.pk).driver_id, self.target.pk)
        self.assertEqual(VehicleDriverAssignment.objects.get(pk=self.assignment.pk).driver_id, self.target.pk)
        audit = AuditLog.objects.get(action='RECONCILIAÇÃO CNH')
        self.assertEqual(audit.old_values['source']['cpf'], '123.456.789-01')
        from apps.fleet.services import current_cnh_document_values
        self.assertEqual(current_cnh_document_values(self.target)['father_name'], 'Pai teste')
        self.assertTrue(RecordOwner.objects.filter(company=self.company, model_label='fleet.document', object_id=self.document.pk).exists())
        self.command(apply=True)
        self.assertEqual(AuditLog.objects.filter(action='RECONCILIAÇÃO CNH').count(), 1)

    def test_other_company_document_aborts_every_change(self):
        other = Company.objects.create(name='Outra empresa')
        RecordOwner.objects.create(company=other, model_label='fleet.document', object_id=self.document.pk)
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            self.command(apply=True)
        self.source.refresh_from_db()
        self.link.refresh_from_db()
        self.assertTrue(self.source.active)
        self.assertEqual(self.link.object_id, self.source.pk)

    def test_operational_source_and_name_mismatch_are_refused(self):
        self.target.name = 'Outra pessoa'
        self.target.save()
        with self.assertRaises(CommandError):
            self.command(apply=True)
        self.target.name = self.source.name
        self.target.save()
        BDT.objects.create(external_id=uuid.uuid4(), driver=self.source)
        with self.assertRaises(CommandError):
            self.command(apply=True)
