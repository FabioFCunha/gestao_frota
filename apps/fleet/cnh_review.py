"""Regras de qualidade e comparação da conferência documental."""
import re
from datetime import date

from django.utils import timezone
from django.utils.dateparse import parse_date

from .cnh_legacy import _cpf_digits

FIELDS = {
    'name': 'Nome', 'cpf': 'CPF', 'cnh_number': 'Registro da CNH',
    'cnh_category': 'Categoria', 'birth_date': 'Nascimento',
    'cnh_expiration': 'Validade', 'cnh_issue_date': 'Emissão',
    'cnh_first_issue_date': 'Primeira habilitação',
    'identity_document': 'Identidade', 'issuing_authority': 'Órgão emissor',
    'issuing_state': 'UF emissora', 'nationality': 'Nacionalidade',
    'father_name': 'Filiação — pai', 'mother_name': 'Filiação — mãe', 'location': 'Local de emissão',
}
REQUIRED = {'name', 'cpf', 'cnh_number', 'cnh_category', 'cnh_expiration'}


def as_date(value):
    return value if isinstance(value, date) else parse_date(str(value or ''))


def quality_issues(values, warnings=True):
    issues = {}
    for field in REQUIRED:
        if not values.get(field):
            issues[field] = 'Não identificado; confira no PDF.'
    if values.get('cpf') and not _cpf_digits(str(values['cpf'])):
        issues['cpf'] = 'CPF com dígitos verificadores inválidos.'
    if values.get('cnh_number') and len(re.sub(r'[^0-9]', '', str(values['cnh_number']))) != 11:
        issues['cnh_number'] = 'O registro deve conter 11 dígitos.'
    if values.get('cnh_category') and str(values['cnh_category']).upper() not in {'ACC','A','B','C','D','E','AB','AC','AD','AE'}:
        issues['cnh_category'] = 'Categoria não reconhecida.'
    dates = {key: as_date(values.get(key)) for key in ('birth_date','cnh_issue_date','cnh_first_issue_date','cnh_expiration')}
    for field, value in dates.items():
        if values.get(field) and value is None:
            issues[field] = 'Data inválida.'
        if value and field != 'cnh_expiration' and value > timezone.localdate():
            issues[field] = 'Esta data não pode estar no futuro.'
    for earlier, later in (
        ('birth_date','cnh_first_issue_date'), ('birth_date','cnh_issue_date'),
        ('birth_date','cnh_expiration'), ('cnh_first_issue_date','cnh_issue_date'),
        ('cnh_issue_date','cnh_expiration'), ('cnh_first_issue_date','cnh_expiration'),
    ):
        if dates[earlier] and dates[later] and dates[earlier] > dates[later]:
            issues[later] = f'{FIELDS[later]} anterior a {FIELDS[earlier].lower()}; confira o documento.'
    if warnings and dates['cnh_expiration'] and dates['cnh_expiration'] < timezone.localdate():
        issues.setdefault('cnh_expiration', 'CNH vencida; confira a validade e a necessidade de renovação.')
    return issues


def validate_review_values(values):
    issues = quality_issues(values, warnings=False)
    # Campos ausentes continuam submetidos às regras de identidade e do formulário.
    errors = [f'{FIELDS[field]}: {message}' for field, message in issues.items() if values.get(field)]
    if errors:
        raise ValueError(' '.join(errors))


def review_rows(preview, driver=None):
    from .services import current_cnh_document_values
    previous = current_cnh_document_values(driver) if driver else {}
    issues = quality_issues(preview)
    rows = []
    def display(value):
        if isinstance(value, date):
            return value.strftime('%d/%m/%Y')
        parsed = parse_date(str(value or ''))
        return parsed.strftime('%d/%m/%Y') if parsed else str(value or '')
    for field, label in FIELDS.items():
        old = getattr(driver, field, previous.get(field, '')) if driver else ''
        new = preview.get(field, '')
        locked_name = bool(driver and field == 'name' and driver.horus_user_id)
        effective = old if locked_name else new or old
        rows.append({'field':field, 'label':label, 'current':display(old), 'read':display(new),
            'proposed':display(effective), 'locked':locked_name,
            'status': 'Confira' if field in issues else 'Preservado' if locked_name else 'Não informado' if not new else 'Alteração' if driver and display(old) != display(new) else 'Lido',
            'issue':issues.get(field, ''), 'preserved':bool(driver and old and (not new or locked_name))})
    return rows, issues
