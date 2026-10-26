"""Regressões da consulta de contrato sob isolamento por empresa."""
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.driverops.models import Company, Member, RecordOwner
from apps.fleet.models import Contract, Renter
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope


@contextmanager
def company_scope(company, user):
    token = set_scope(Scope(company_id=company.pk, actor_id=user.pk))
    try:
        yield
    finally:
        reset_scope(token)


class ContractDetailTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa do contrato")
        self.other_company = Company.objects.create(name="Outra empresa")
        self.user = get_user_model().objects.create_user(username="gestor-contrato")
        self.other_user = get_user_model().objects.create_user(username="outro-gestor-contrato")
        Member.objects.create(company=self.company, user=self.user, role=Member.MANAGER)
        Member.objects.create(company=self.other_company, user=self.other_user, role=Member.MANAGER)
        with company_scope(self.company, self.user):
            self.renter = Renter.objects.create(name="Locadora autorizada")
            self.contract = Contract.objects.create(number="CONTRATO-SEM-VEICULOS", renter=self.renter)
        with company_scope(self.other_company, self.other_user):
            other_renter = Renter.objects.create(name="Locadora de outra empresa")
            self.foreign_contract = Contract.objects.create(number="CONTRATO-ESTRANGEIRO", renter=other_renter)
        self.client.force_login(self.user)

    def test_opens_owned_contract_without_linked_vehicles(self):
        response = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.contract.number)

    def test_other_company_contract_remains_hidden(self):
        response = self.client.get(reverse("contract_detail", args=[self.foreign_contract.pk]))
        self.assertEqual(response.status_code, 404)

    def test_missing_renter_ownership_does_not_hide_owned_contract(self):
        RecordOwner.objects.filter(model_label="fleet.renter", object_id=self.renter.pk).delete()
        response = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.contract.number)
        self.assertNotContains(response, self.renter.name)
