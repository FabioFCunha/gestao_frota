import re
import unicodedata

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from apps.accounts.decorators import module_permission
from apps.fleet.driver_scope import apply_driver_sector_scope
from apps.fleet.models import AuditLog, Document, Driver
from apps.fleet.cnh_review import review_rows, validate_review_values
from apps.fleet.cnh_legacy import _cpf_digits


def scoped_driver(request, pk):
    return get_object_or_404(apply_driver_sector_scope(
        Driver.objects.all(), request.user, request.GET.get('sector')), pk=pk)


def review_context(request, preview, driver=None):
    if not preview:
        return {}
    if driver is None and preview.get('cpf'):
        digits = re.sub(r'[^0-9]', '', preview['cpf'])
        driver = next((d for d in apply_driver_sector_scope(Driver.objects.all(), request.user,
            request.GET.get('sector')) if re.sub(r'[^0-9]', '', d.cpf) == digits), None)
    rows, issues = review_rows(preview, driver)
    return {'cnh_review_rows':rows, 'cnh_review_issues':issues, 'cnh_review_driver':driver,
            'cnh_can_correct':bool(driver and request.user.has_perm('fleet.correct_driver_identity'))}


def staged_document(request, pk):
    document = get_object_or_404(Document, pk=pk, created_by=request.user, document_type__name='CNH')
    audit = AuditLog.objects.filter(user=request.user, module='cnh', entity_type='document',
        entity_id=document.pk, action__in=['CNH PARA CADASTRO DE MOTORISTA','CNH PARA ATUALIZAR MOTORISTA']).order_by('-created_at').first()
    if not audit:
        raise Http404
    target = (audit.new_values or {}).get('driver_id')
    if target:
        if not request.user.has_perm('fleet.change_driver'):
            raise PermissionDenied
        scoped_driver(request, target)
    elif not (request.user.has_perm('fleet.add_driver') or request.user.has_perm('fleet.correct_driver_identity')):
        raise PermissionDenied
    return document, audit


@login_required
@xframe_options_sameorigin
def cnh_original(request, pk):
    document, _ = staged_document(request, pk)
    version = document.versions.order_by('-created_at').first()
    if not version:
        raise Http404
    try:
        response = FileResponse(version.file.open('rb'), content_type='application/pdf', filename='CNH.pdf')
    except OSError as exc:
        raise Http404 from exc
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class IdentityCorrectionForm(forms.Form):
    document_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_cpf = forms.CharField(widget=forms.HiddenInput, required=False)
    cpf = forms.CharField(label='CPF correto, conforme o PDF', max_length=14)
    cpf_again = forms.CharField(label='Repita o CPF correto', max_length=14)
    reason = forms.CharField(label='Justificativa da correção', min_length=15, max_length=1000, widget=forms.Textarea(attrs={'rows':3}))
    confirmed = forms.BooleanField(label='Conferi o PDF original e confirmo que pertence a este motorista.')

    def clean(self):
        data = super().clean()
        first = _cpf_digits(data.get('cpf', ''))
        second = _cpf_digits(data.get('cpf_again', ''))
        if not first:
            self.add_error('cpf', 'Informe um CPF com dígitos verificadores válidos.')
        if first != second:
            self.add_error('cpf_again', 'Os dois CPFs devem ser iguais.')
        return data


@transaction.atomic
def correct_identity(*, driver, document_id, expected_cpf, cpf, reason, user):
    from apps.fleet.services import cnh_confirmation_source, link_document
    if not user.has_perm('fleet.correct_driver_identity'):
        raise PermissionDenied
    document, source = cnh_confirmation_source(document_id=document_id, user=user)
    driver = Driver.objects.select_for_update().get(pk=driver.pk)
    digits = lambda value: re.sub(r'[^0-9]', '', str(value or ''))
    if digits(driver.cpf) != digits(expected_cpf):
        raise ValueError('O cadastro mudou durante a conferência. Reabra a tela.')
    key = lambda value: ''.join(c for c in unicodedata.normalize('NFKD', value or '').upper() if c.isalnum())
    if not key(source.get('name')) or key(source['name']) != key(driver.name):
        raise ValueError('O nome do PDF diverge do cadastro. A correção precisa de conferência pela administração da plataforma.')
    valid = _cpf_digits(cpf)
    if not valid or valid != _cpf_digits(source.get('cpf', '')):
        raise ValueError('O CPF informado não corresponde ao CPF válido lido no PDF.')
    validate_review_values(source)
    if driver.cnh_number and digits(driver.cnh_number) != digits(source.get('cnh_number')):
        raise ValueError('O registro da CNH diverge. Confira a identidade antes de corrigir o CPF.')
    if driver.birth_date and str(driver.birth_date) != str(source.get('birth_date')):
        raise ValueError('O nascimento do PDF diverge do cadastro.')
    if len(reason.strip()) < 15:
        raise ValueError('Informe uma justificativa com pelo menos 15 caracteres.')
    if digits(driver.cpf) == valid:
        raise ValueError('O cadastro já contém este CPF; não é necessário corrigir.')
    formatted = f'{valid[:3]}.{valid[3:6]}.{valid[6:9]}-{valid[9:]}'
    # Exceção controlada à imutabilidade, com bloqueio e valores anterior/novo auditados.
    old = driver.cpf
    Driver.objects.filter(pk=driver.pk).update(cpf=formatted, updated_at=timezone.now())
    link_document(document=document, obj=driver, user=user)
    audit = AuditLog.objects.create(user=user, module='cnh', action='CORREÇÃO CPF COM DOCUMENTO',
        entity_type='driver', entity_id=driver.pk, old_values={'cpf':old},
        new_values={'cpf':formatted, 'driver_id':str(driver.pk), 'document_id':str(document.pk)}, reason=reason.strip())
    # A administração da plataforma pode atuar sem escopo de empresa.
    from django.apps import apps
    from apps.fleet.tenant_scope import current_scope
    if current_scope() is None and apps.is_installed('apps.driverops'):
        from apps.driverops.models import RecordOwner
        from apps.driverops.ownership import bind_graph
        owner = RecordOwner.objects.filter(model_label='fleet.driver', object_id=driver.pk).first()
        if owner:
            bind_graph(Document, document.pk, owner.company_id)
            bind_graph(AuditLog, audit.pk, owner.company_id)
    return driver


@login_required
@module_permission('fleet.correct_driver_identity')
def identity_correction(request, pk):
    from .forms import CNHUploadForm
    from apps.fleet.services import stage_cnh_document_for_creation
    driver = scoped_driver(request, pk)
    upload = CNHUploadForm()
    form = document = preview = None
    if request.method == 'POST' and request.POST.get('step') == 'upload':
        upload = CNHUploadForm(request.POST, request.FILES)
        if upload.is_valid():
            try:
                document, preview = stage_cnh_document_for_creation(file_obj=upload.cleaned_data['file'], user=request.user)
                form = IdentityCorrectionForm(initial={'document_id':document.pk, 'expected_cpf':driver.cpf})
            except ValueError as exc:
                upload.add_error('file', str(exc))
    elif request.method == 'POST':
        form = IdentityCorrectionForm(request.POST)
        if form.is_valid():
            try:
                correct_identity(driver=driver, user=request.user, **{k:v for k,v in form.cleaned_data.items() if k not in ('confirmed','cpf_again')})
            except (ValueError, ValidationError, IntegrityError, Document.DoesNotExist) as exc:
                form.add_error(None, 'CPF já cadastrado ou documento indisponível.' if isinstance(exc, (IntegrityError, Document.DoesNotExist)) else str(exc))
            else:
                return redirect(reverse('driver_cnh', args=[driver.pk]))
        document_id = form.cleaned_data.get('document_id')
        if document_id:
            document, audit = staged_document(request, document_id)
            preview = audit.new_values or {}
    return render(request, 'ui/cnh_identity_correction.html', {'driver':driver, 'upload_form':upload,
        'form':form, 'document':document, 'preview':preview})


def audit_context(driver):
    from django.db.models import Q
    return {'cnh_recent_audits': AuditLog.objects.filter(module='cnh').filter(
        Q(entity_type='driver', entity_id=driver.pk) | Q(new_values__driver_id=str(driver.pk))
    ).select_related('user').order_by('-created_at')[:12]}
