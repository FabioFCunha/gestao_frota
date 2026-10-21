"""Explicit, audited reconciliation of an orphan PDF driver into a Hórus driver."""
import re
import unicodedata
from uuid import UUID
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.fleet.models import Driver, Document, DocumentRelation, AuditLog, DriverCNHPhoto
from apps.fleet.services import current_cnh_document_values, update_driver_document_data
from apps.fleet.tenant_scope import current_scope
from apps.driverops.models import Company, RecordOwner
from apps.driverops.ownership import bind_graph


def digits(value):
    return re.sub(r'\D', '', value or '')


def name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value).upper() if c.isalnum())


class Command(BaseCommand):
    help = 'Reconcilia CNH de cadastro sem operação; simula por padrão e exige --apply para gravar.'

    def add_arguments(self, parser):
        for name in ('source', 'target', 'company', 'document'):
            parser.add_argument('--' + name, required=True, type=UUID)
        parser.add_argument('--actor', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        if current_scope() is not None:
            raise CommandError('Execute offline, sem escopo de usuário.')
        if options['source'] == options['target']:
            raise CommandError('Origem e destino devem ser diferentes.')
        company = Company.objects.get(pk=options['company'], active=True)
        actor = get_user_model().objects.get(email__iexact=options['actor'], is_active=True, is_superuser=True)
        locked = {d.pk: d for d in Driver.objects.select_for_update().filter(
            pk__in=[options['source'], options['target']]).order_by('pk')}
        if len(locked) != 2:
            raise CommandError('Motoristas não localizados.')
        source, target = locked[options['source']], locked[options['target']]
        if AuditLog.objects.filter(action='RECONCILIAÇÃO CNH', entity_id=target.pk,
                                   new_values__source_id=str(source.pk)).exists():
            self.stdout.write('Reconciliação já aplicada; nenhum dado alterado.')
            return
        owner = RecordOwner.objects.filter(model_label='fleet.driver', object_id=target.pk).first()
        if not owner or owner.company_id != company.pk:
            raise CommandError('Destino não pertence à empresa informada.')
        if RecordOwner.objects.filter(model_label='fleet.driver', object_id=source.pk).exclude(company=company).exists():
            raise CommandError('Origem pertence a outra empresa.')
        if source.horus_user_id or not target.horus_user_id or name_key(source.name) != name_key(target.name):
            raise CommandError('É necessário cadastro órfão e destino Hórus com o mesmo nome.')
        if not source.active or source.sectors.exists():
            raise CommandError('Origem deve estar ativa e sem setor institucional.')
        if len(digits(source.cpf)) != 11 or len(digits(source.cnh_number)) != 11:
            raise CommandError('Origem sem CPF/CNH completos.')
        for field in ('cpf', 'cnh_number'):
            if digits(getattr(target, field)) not in ('', digits(getattr(source, field))):
                raise CommandError('Destino já possui identidade divergente.')
        if source.birth_date and target.birth_date and source.birth_date != target.birth_date:
            raise CommandError('Datas de nascimento divergentes.')
        # Any operational/account reference means this command cannot retire the source.
        for rel in Driver._meta.related_objects:
            if rel.related_model._meta.label_lower in ('fleet.drivercnhhistory', 'fleet.drivercnhphoto'):
                continue
            if rel.related_model.objects.filter(**{rel.field.name: source.pk}).exists():
                raise CommandError('Origem tem vínculos operacionais; reconciliação manual necessária.')
        ct = ContentType.objects.get_for_model(Driver)
        links = list(DocumentRelation.objects.select_for_update().filter(content_type=ct, object_id=source.pk))
        if {r.document_id for r in links} != {options['document']}:
            raise CommandError('Os documentos da origem mudaram; confira novamente.')
        document = Document.objects.select_for_update().get(pk=options['document'])
        if document.document_type.name.upper() != 'CNH':
            raise CommandError('Documento informado não é uma CNH.')
        if DocumentRelation.objects.filter(document=document).exclude(content_type=ct, object_id=source.pk).exists():
            raise CommandError('Documento também vinculado a outro cadastro.')
        if DriverCNHPhoto.objects.filter(driver=source).exists() and DriverCNHPhoto.objects.filter(driver=target).exists():
            raise CommandError('Ambos possuem foto; confira qual foto preservar.')

        fields = ('cpf', 'birth_date', 'cnh_number', 'cnh_category', 'cnh_expiration')
        def snapshot(driver):
            result = {f: getattr(driver, f) for f in fields}
            return {f: v.isoformat() if hasattr(v, 'isoformat') else v for f, v in result.items()}
        old = {'source': snapshot(source), 'target': snapshot(target), 'source_active': source.active}
        supplementary = current_cnh_document_values(source)
        old['source_document_values'] = supplementary
        allowed = ('cnh_issue_date', 'cnh_first_issue_date', 'identity_document', 'issuing_authority',
                   'issuing_state', 'nationality', 'father_name', 'mother_name', 'location')
        values = {f: supplementary[f] for f in allowed if supplementary.get(f) not in (None, '')}
        values.update({f: getattr(source, f) for f in fields if getattr(source, f) not in (None, '')})
        # Deliberate repair exception to immutable CPF: release the orphan's identity
        # inside this transaction, retaining its original values in the audit below.
        Driver.objects.filter(pk=source.pk).update(cpf='', cnh_number='', active=False, updated_at=timezone.now())
        target = update_driver_document_data(driver=target, values=values, user=actor)
        for link in links:
            link.object_id = target.pk
            link.save(update_fields=['object_id', 'updated_at'])
        for model_name in ('drivercnhhistory', 'drivercnhphoto'):
            from django.apps import apps
            apps.get_model('fleet', model_name).objects.filter(driver=source).update(driver=target)
        # Claim only the reviewed document graph after redirecting its driver link.
        bind_graph(Document, document.pk, company.pk)
        bind_graph(Driver, target.pk, company.pk)
        for audit in AuditLog.objects.filter(entity_type='document', entity_id=document.pk):
            bind_graph(AuditLog, audit.pk, company.pk)
        for audit in AuditLog.objects.filter(entity_type='driver', entity_id=target.pk, action='CNH EDITADA MANUALMENTE'):
            bind_graph(AuditLog, audit.pk, company.pk)
        audit = AuditLog.objects.create(user=actor, module='cnh', action='RECONCILIAÇÃO CNH',
            entity_type='driver', entity_id=target.pk, old_values=old,
            new_values={'source_id': str(source.pk), 'driver_id': str(target.pk),
                        'document_id': str(document.pk), 'form_values': current_cnh_document_values(target)},
            reason='Cadastro órfão criado por PDF reconciliado com o motorista Hórus; origem inativada, sem exclusão.')
        bind_graph(AuditLog, audit.pk, company.pk)
        self.stdout.write(f'Destino: {target.name} | Empresa: {company.name}')
        self.stdout.write(f'BDTs preservados: {target.bdts.count()} | Vínculos de viatura: {target.vehicle_assignments.count()}')
        if options['apply']:
            self.stdout.write('Reconciliação aplicada com auditoria. Origem inativa; documento preservado.')
        else:
            transaction.set_rollback(True)
            self.stdout.write('Simulação concluída; nenhum dado alterado. Use --apply para gravar.')
