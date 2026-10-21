from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction, IntegrityError
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import ValidationError
from apps.fleet.models import Driver, Vehicle, VehicleStatus, VehiclePlate, VehicleMileage, AuditLog
from .models import Company, Member, CompanyVehicle
from .management_forms import CompanyForm, MemberForm, VehicleForm, AssignmentForm

BASE = "/api/driver/management/"


def managed_company(request):
    if request.user.is_superuser:
        companies = Company.objects.filter(active=True).order_by("name")
        key = request.POST.get("company") if request.method == "POST" else request.GET.get("company")
        if key:
            try:
                return get_object_or_404(companies,pk=key), companies
            except ValidationError:
                return None, companies
        return companies.first(), companies
    member = Member.objects.filter(user=request.user, role="manager",active=True,company__active=True).select_related("company").first()
    if not member:
        return None, Company.objects.none()
    # Ignore foreign company selectors; every form/query uses the authenticated membership.
    return member.company, Company.objects.filter(pk=member.company_id)


def audit(request, company, action, entity_id, values, old=None):
    AuditLog.objects.create(user=request.user,module="driverops",action=action,
        entity_type="company_setup",entity_id=entity_id,
        old_values=old,new_values={"company":str(company.pk),**values})


def back(company):
    return redirect(("/empresas/" if getattr(settings, "CENTRAL_USER_MANAGEMENT", False) else BASE)+"?"+urlencode({"company":str(company.pk)}))


@login_required
def management(request):
    if getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) and not request.user.is_superuser:
        return redirect('user_list') if request.method == 'GET' else HttpResponseForbidden('Use a área Usuários no sistema principal.')
    if getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) and request.POST.get('action') == 'assign':
        return HttpResponseForbidden('Defina o veículo e o motorista na OS.')
    company, companies = managed_company(request)
    if not request.user.is_superuser and company is None:
        return HttpResponseForbidden("Acesso exclusivo ao administrador ou gestor da empresa.")
    if request.method not in ("GET","POST"):
        return HttpResponseBadRequest("Método não permitido.")
    action = request.POST.get("action") if request.method == "POST" else None
    if action and action not in ("company","member","vehicle","assign","use_company","access","password"):
        return HttpResponseBadRequest("Operação inválida.")
    company_form = CompanyForm(request.POST if action=="company" else None,auto_id="company_%s")
    member_form = MemberForm(request.POST if action=="member" else None,company=company,platform=request.user.is_superuser,auto_id="person_%s") if company else None
    vehicle_form = VehicleForm(request.POST if action=="vehicle" else None,company=company,platform=request.user.is_superuser,auto_id="vehicle_%s") if company else None
    assignment_error = None
    if request.method == "POST":
        if action in ("company","use_company") and not request.user.is_superuser:
            return HttpResponseForbidden("Somente o administrador da plataforma pode cadastrar empresas.")
        if action != "company" and company is None:
            return HttpResponseBadRequest("Selecione uma empresa ativa.")
        if action == "company" and company_form.is_valid():
            try:
                with transaction.atomic():
                    created = company_form.save_company()
                    audit(request,created,"EMPRESA CRIADA",created.pk,{"name":created.name})
            except IntegrityError:
                company_form.add_error(None, 'Este login ou cadastro já existe. Confira os dados.')
            else:
                messages.success(request,"Empresa e gestor criados. O gestor já pode entrar na interface completa da frota.")
                return back(created)
        if action == "use_company":
            with transaction.atomic():
                obj, created = Member.objects.get_or_create(user=request.user,
                    defaults={"company":company,"role":"manager","active":True})
                if obj.company_id != company.pk or obj.role != "manager":
                    messages.error(request,"Sua conta já tem vínculo com outra empresa ou perfil. Não alteramos esse vínculo.")
                elif not obj.active:
                    messages.error(request,"Seu vínculo está inativo. Reative-o na administração avançada.")
                else:
                    if created:
                        audit(request,company,"GESTOR VINCULADO",request.user.pk,{"username":request.user.username})
                    messages.success(request,"Seu acesso ao painel do gestor está pronto.")
            return back(company)
        form = member_form if action=="member" else vehicle_form if action=="vehicle" else None
        if form and form.is_valid():
            try:
                with transaction.atomic():
                    Company.objects.select_for_update().get(pk=company.pk,active=True)
                    if action == "member":
                        data = form.cleaned_data
                        user = form.save(commit=False)
                        parts = data["name"].split(maxsplit=1)
                        user.first_name,user.last_name = parts[0],parts[1] if len(parts)>1 else ""
                        user.email=data["email"]
                        if getattr(settings, "CENTRAL_USER_MANAGEMENT", False):
                            user.username = user.email
                        user.is_staff=False; user.is_superuser=False
                        user.save()
                        driver = None
                        if data["role"]=="driver":
                            driver = data.get("existing_driver")
                            if driver:
                                Driver.objects.select_for_update().get(pk=driver.pk)
                                if Member.objects.filter(driver=driver).exists():
                                    raise IntegrityError("Driver already linked")
                            else:
                                driver = Driver.objects.create(name=data["name"],email=data["email"])
                        member = Member.objects.create(company=company,user=user,driver=driver,role=data["role"])
                        for vehicle in data.get("vehicles", []):
                            vehicle.drivers.add(member)
                        audit(request,company,"PESSOA CADASTRADA",user.pk,
                              {"username":user.username,"role":member.role,"vehicles":[v.pk for v in data.get("vehicles", [])]})
                        messages.success(request,"Acesso criado. Informe ao usuário o login escolhido e a senha inicial.")
                    else:
                        data = form.cleaned_data
                        vehicle = data.get("existing_vehicle")
                        if vehicle:
                            Vehicle.objects.select_for_update().get(pk=vehicle.pk)
                            if CompanyVehicle.objects.filter(vehicle=vehicle).exists():
                                raise IntegrityError("Vehicle already linked")
                        else:
                            status = VehicleStatus.objects.filter(active=True,name="Disponível").first()
                            if not status:
                                status = VehicleStatus.objects.create(name="Disponível")
                            vehicle = Vehicle.objects.create(status=status,created_by=request.user)
                            VehiclePlate.objects.create(vehicle=vehicle,plate=data["plate"],kind="CURRENT",changed_by=request.user)
                            if data["mileage"] is not None:
                                VehicleMileage.objects.create(vehicle=vehicle,mileage=data["mileage"],
                                    recorded_by=request.user,notes="Cadastro inicial pelo painel da empresa.")
                        assignment, _ = CompanyVehicle.objects.update_or_create(company=company,vehicle=vehicle,defaults={"label":data["label"] or data["plate"]})
                        assignment.drivers.set(data.get("drivers", []))
                        audit(request,company,"VEÍCULO VINCULADO",vehicle.pk,
                              {"label":assignment.label,"drivers":[m.pk for m in data.get("drivers", [])]})
                        messages.success(request,"Veículo cadastrado e vinculado à empresa.")
                return back(company)
            except IntegrityError:
                form.add_error(None,"Este usuário, motorista, placa ou veículo já foi cadastrado. Confira a lista e tente novamente.")
        if action in ('password', 'access'):
            try:
                member_key = int(request.POST.get('member', ''))
            except (ValueError, TypeError):
                return HttpResponseBadRequest('Usuário inválido.')
        if action == 'password':
            member = get_object_or_404(Member, company=company, pk=member_key)
            if member.user.is_superuser or member.user_id == request.user.pk:
                return HttpResponseForbidden('Use Alterar senha para sua própria conta.')
            password_form = SetPasswordForm(member.user, request.POST)
            if password_form.is_valid():
                with transaction.atomic():
                    password_form.save()
                    from .models import DeviceSession
                    DeviceSession.objects.filter(member=member).delete()
                    audit(request,company,'SENHA REDEFINIDA',member.user_id,{})
                messages.success(request,'Senha redefinida. Informe a nova senha ao usuário.')
            else:
                messages.error(request,' '.join(str(error) for errors in password_form.errors.values() for error in errors))
            return back(company)
        if action == 'access':
            member = get_object_or_404(Member, company=company, pk=member_key)
            if member.user.is_superuser:
                return HttpResponseForbidden('Acesso reservado à plataforma.')
            if member.user_id == request.user.pk:
                return HttpResponseBadRequest('Você não pode desativar seu próprio acesso.')
            active = request.POST.get('active') == 'true'
            with transaction.atomic():
                Company.objects.select_for_update().get(pk=company.pk)
                if member.role == Member.MANAGER and not active and not Member.objects.filter(company=company, role=Member.MANAGER, active=True).exclude(pk=member.pk).exists():
                    return HttpResponseBadRequest('Mantenha pelo menos um gestor ativo.')
                member.active = active
                member.save(update_fields=['active'])
                audit(request,company,'ACESSO ALTERADO',member.user_id,{'active':active})
            messages.success(request,'Acesso atualizado.')
            return back(company)
        if action == "assign":
            try:
                vehicle_key = int(request.POST.get("vehicle", ""))
            except (ValueError, TypeError):
                return HttpResponseBadRequest("Veículo inválido.")
            assignment = get_object_or_404(CompanyVehicle,company=company,pk=vehicle_key)
            form = AssignmentForm(request.POST,company=company,vehicle=assignment,auto_id=f"allowed_{assignment.pk}_%s")
            if form.is_valid():
                with transaction.atomic():
                    CompanyVehicle.objects.select_for_update().get(pk=assignment.pk)
                    before = list(assignment.drivers.values_list("pk",flat=True))
                    assignment.drivers.set(form.cleaned_data["drivers"])
                    audit(request,company,"MOTORISTAS AUTORIZADOS",assignment.vehicle_id,
                          {"drivers":list(assignment.drivers.values_list("pk",flat=True))},old={"drivers":before})
                messages.success(request,"Motoristas autorizados atualizados.")
                return back(company)
            assignment_error=(assignment.pk,form)
    vehicles = list(CompanyVehicle.objects.filter(company=company).select_related("vehicle").order_by("label")) if company else []
    for vehicle in vehicles:
        vehicle.assignment_form = assignment_error[1] if assignment_error and assignment_error[0]==vehicle.pk else AssignmentForm(company=company,vehicle=vehicle,auto_id=f"allowed_{vehicle.pk}_%s")
    members = Member.objects.filter(company=company).select_related("user","driver").order_by("user__first_name","user__username") if company else []
    return render(request,"driverops/management.html",{
        "company":company,"companies":companies,"company_form":company_form,
        "member_form":member_form,"vehicle_form":vehicle_form,"vehicles":vehicles,
        "members":members,"platform":request.user.is_superuser,
    })
