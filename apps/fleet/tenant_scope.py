"""Request-local company scope for the existing fleet ORM, including lazy queries.

No scope means offline/platform operation (legacy compatibility). A blocked scope
means an unauthenticated/unassigned HTTP request: no fleet data is visible.
The SQL compiler boundary also covers QuerySets declared at module import time.
"""
from copy import copy
from contextvars import ContextVar
from dataclasses import dataclass
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models import Q, Subquery
from django.db.models.expressions import Col
from django.db.models.lookups import In
from django.db.models.sql.where import WhereNode
from django.db.models.sql import Query
from django.db.models.sql.compiler import SQLCompiler


@dataclass(frozen=True)
class Scope:
    company_id: object = None
    actor_id: object = None
    blocked: bool = False


_current = ContextVar('fleet_company_scope', default=None)
GLOBAL = {'fleet.sector', 'fleet.brand', 'fleet.vehiclemodel'}
CATALOG = {'fleet.vehiclestatus', 'fleet.maintenancestatus', 'fleet.maintenancetype',
           'fleet.vehicleinspectiontype', 'fleet.vehicleinspectionstatus', 'fleet.vehiclefinestatus',
           'fleet.documenttype', 'fleet.documentstatus', 'fleet.seiprocessstatus', 'fleet.licensingcalendar'}


def current_scope():
    return _current.get()


def company_id():
    scope = current_scope()
    return scope.company_id if scope else None


def set_scope(scope):
    return _current.set(scope)


def reset_scope(token):
    _current.reset(token)


def owners():
    return apps.get_model('driverops', 'RecordOwner')


def predicate(model, write=False):
    scope = current_scope()
    if scope is None:
        return Q()
    if scope.blocked or not scope.company_id:
        return Q(pk__in=[])
    label = model._meta.label_lower
    mine = owners().objects.filter(model_label=label, company_id=scope.company_id).values('object_id')
    if not write and label in GLOBAL:
        return Q()
    if not write and label in CATALOG:
        all_ids = owners().objects.filter(model_label=label).values('object_id')
        return Q(pk__in=mine) | ~Q(pk__in=all_ids)
    return Q(pk__in=mine)


class CompanyQuery(Query):
    def get_compiler(self, using=None, connection=None, elide_empty=True):
        # Do not mutate shared class-level QuerySets or cached form choices.
        query = self.clone()
        query.add_q(predicate(self.model))
        compiler = super(CompanyQuery, query).get_compiler(using, connection, elide_empty)
        return CompanySQLCompiler(query, compiler.connection, compiler.using, elide_empty)


class CompanySQLCompiler(SQLCompiler):
    def get_from_clause(self):
        # select_related() creates joins during pre_sql_setup(), so guard them
        # here, once all selected relations and annotations have been resolved.
        query = self.query
        scope = current_scope()
        if scope and scope.company_id:
            # Scope reverse joins too: a shared brand/status must never expose
            # another company's vehicles through values(), annotations or filters.
            tables = {m._meta.db_table: m for m in apps.get_app_config('fleet').get_models()
                      if issubclass(m, TenantModel)}
            for alias, join in list(query.alias_map.items()):
                target = tables.get(join.table_name)
                if not getattr(join, 'join_type', None) or target is None or target._meta.label_lower in GLOBAL:
                    continue
                label = target._meta.label_lower
                col = Col(alias, target._meta.pk)
                own = owners().objects.filter(model_label=label, company_id=scope.company_id).values('object_id')
                condition = In(col, Subquery(own))
                if label in CATALOG:
                    all_ids = owners().objects.filter(model_label=label).values('object_id')
                    condition = WhereNode([condition, WhereNode([In(col, Subquery(all_ids))], negated=True)], connector='OR')
                guarded = copy(join)
                guarded.filtered_relation = WhereNode(
                    ([join.filtered_relation] if join.filtered_relation is not None else []) + [condition])
                query.alias_map[alias] = guarded
        return super().get_from_clause()


class CompanyQuerySet(models.QuerySet):
    def _fetch_all(self):
        key = current_scope()
        if getattr(self, '_company_cache_key', None) != key:
            self._result_cache = None
            self._prefetch_done = False
        self._company_cache_key = key
        return super()._fetch_all()

    def _scoped(self, write=False):
        return self.filter(predicate(self.model, write=write))

    def count(self):
        return super(CompanyQuerySet, self._scoped()).count()

    def exists(self):
        return super(CompanyQuerySet, self._scoped()).exists()

    def aggregate(self, *args, **kwargs):
        return super(CompanyQuerySet, self._scoped()).aggregate(*args, **kwargs)

    def update(self, **kwargs):
        if current_scope() is not None and hasattr(self.model, 'content_type') and {'content_type', 'content_type_id', 'object_id'} & kwargs.keys():
            raise PermissionDenied('Altere vínculos de documento individualmente para validar o destino.')
        validate_links(self.model, kwargs)
        return super(CompanyQuerySet, self._scoped(write=True)).update(**kwargs)

    def _update(self, values):
        return super(CompanyQuerySet, self._scoped(write=True))._update(values)

    def delete(self):
        return super(CompanyQuerySet, self._scoped(write=True)).delete()

    def bulk_create(self, objs, *args, **kwargs):
        if current_scope() is None:
            return super().bulk_create(objs, *args, **kwargs)
        if args or kwargs.get('ignore_conflicts') or kwargs.get('update_conflicts'):
            raise PermissionDenied('Importação em lote com conflitos não disponível por empresa.')
        with transaction.atomic():
            for obj in objs:
                obj.save(force_insert=True, using=self.db)
        return objs

    def bulk_update(self, objs, fields, **kwargs):
        if current_scope() is None:
            return super().bulk_update(objs, fields, **kwargs)
        with transaction.atomic():
            for obj in objs:
                obj.save(update_fields=fields, using=self.db)
        return len(objs)

    def raw(self, *args, **kwargs):
        if current_scope() is not None:
            raise PermissionDenied('Consulta SQL direta não permitida no painel da empresa.')
        return super().raw(*args, **kwargs)


class CompanyManager(models.Manager.from_queryset(CompanyQuerySet)):
    def get_queryset(self):
        return self._queryset_class(self.model, query=CompanyQuery(self.model), using=self._db, hints=self._hints)


def validate_links(model, data):
    scope = current_scope()
    if scope is None:
        return
    if scope.blocked:
        raise PermissionDenied('Empresa não identificada.')
    for field in model._meta.concrete_fields:
        if not field.is_relation or field.many_to_many:
            continue
        value = data.get(field.name, data.get(field.attname))
        if value is None:
            continue
        target = field.remote_field.model
        pk = value.pk if hasattr(value, 'pk') else value
        if target._meta.app_label == 'fleet' and issubclass(target, TenantModel):
            if not target.objects.filter(pk=pk).exists():
                raise PermissionDenied('Cadastro relacionado não pertence à sua empresa.')
        if target._meta.label_lower == 'accounts.user' and pk != scope.actor_id:
            Member = apps.get_model('driverops', 'Member')
            User = apps.get_model('accounts', 'User')
            if not User.objects.filter(pk=pk, is_superuser=True).exists() and not Member.objects.filter(user_id=pk, company_id=scope.company_id).exists():
                raise PermissionDenied('Usuário relacionado não pertence à sua empresa.')


class TenantModel(models.Model):
    objects = CompanyManager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        if current_scope() is not None and not type(self).objects.filter(predicate(type(self), write=True), pk=self.pk).exists():
            raise PermissionDenied('Registro de outra empresa ou catálogo compartilhado protegido.')
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        scope = current_scope()
        if scope is None:
            with transaction.atomic(using=kwargs.get("using") or self._state.db or "default"):
                return super().save(*args, **kwargs)
        if scope.blocked:
            raise PermissionDenied('Empresa não identificada.')
        label = self._meta.label_lower
        with transaction.atomic(using=kwargs.get('using') or self._state.db or 'default'):
            if self._state.adding and models.QuerySet(type(self)).filter(pk=self.pk).exists():
                if not type(self).objects.filter(predicate(type(self), write=True), pk=self.pk).exists():
                    raise PermissionDenied('Não é permitido substituir registro existente de outra empresa ou catálogo compartilhado.')
            if not self._state.adding:
                if not type(self).objects.filter(predicate(type(self), write=True), pk=self.pk).exists():
                    raise PermissionDenied('Registro de outra empresa ou catálogo compartilhado protegido.')
            validate_links(type(self), {f.attname:getattr(self,f.attname) for f in self._meta.concrete_fields})
            if hasattr(self, 'content_type_id') and hasattr(self, 'object_id'):
                target = self.content_type.model_class()
                if target is None or target._meta.app_label != 'fleet' or not target.objects.filter(pk=self.object_id).exists():
                    raise PermissionDenied('Destino do documento fora da empresa.')
            owner, created = owners().objects.get_or_create(model_label=label, object_id=self.pk,
                                                         defaults={'company_id':scope.company_id})
            if owner.company_id != scope.company_id:
                raise PermissionDenied('Registro já pertence a outra empresa.')
            return super().save(*args, **kwargs)
