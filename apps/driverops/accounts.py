"""Company access management inside the original /usuarios/ screens."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from apps.accounts.models import User
from apps.fleet.models import AuditLog
from .account_forms import CompanyUserForm
from .models import Company, Member, CompanyVehicle, DeviceSession


def user_list(request):
    users = User.objects.filter(member__company=request.company).select_related('member').order_by('first_name', 'email')
    return render(request, 'accounts/user_list.html', {'users': users, 'central_users': True})


def user_form(request, pk=None):
    member = get_object_or_404(Member.objects.select_related('user'), company=request.company, user_id=pk) if pk else None
    if member and member.user.is_superuser:
        raise PermissionDenied('Conta da plataforma protegida.')
    form = CompanyUserForm(request.POST or None, instance=member.user if member else None,
                           member=member, company=request.company)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                Company.objects.select_for_update().get(pk=request.company.pk, active=True)
                data = form.cleaned_data
                if member and member.user_id == request.user.pk and (not data['is_active'] or data['role'] != Member.MANAGER):
                    raise ValueError('Você não pode desativar ou remover o perfil de gestor do próprio acesso.')
                if member and member.role == Member.MANAGER and (not data['is_active'] or data['role'] != Member.MANAGER):
                    if not Member.objects.filter(company=request.company, role=Member.MANAGER, active=True, user__is_active=True).exclude(pk=member.pk).exists():
                        raise ValueError('Mantenha pelo menos um gestor ativo.')
                user = form.save(commit=False)
                user.email = user.email.strip().lower()
                user.username = user.email
                user.is_staff = False
                user.is_superuser = False
                password = data.get('initial_password')
                if password:
                    user.set_password(password)
                    user.must_change_password = True
                user.save()
                if not member:
                    member = Member(company=request.company, user=user)
                member.role, member.driver, member.active = data['role'], data.get('driver'), data['is_active']
                member.save()
                DeviceSession.objects.filter(member=member).delete()
                AuditLog.objects.create(user=request.user, module='usuários', action='ACESSO DA EMPRESA ATUALIZADO',
                    entity_type='user', entity_id=user.pk, new_values={'company': str(request.company.pk), 'email': user.email,
                    'role': member.role, 'active': member.active, 'driver': str(member.driver_id) if member.driver_id else None,
                    'vehicle_authorization': 'exit_order'})
        except (IntegrityError, ValueError) as error:
            form.add_error(None, 'E-mail ou motorista já vinculado. Confira o cadastro.' if isinstance(error, IntegrityError) else str(error))
        else:
            messages.success(request, 'Acesso atualizado. O login é o e-mail; o motorista usa a mesma conta no aplicativo.')
            return redirect('user_list')
    return render(request, 'accounts/user_form.html', {'form': form, 'title': 'Editar usuário' if member else 'Cadastrar usuário', 'editing': bool(member)})
