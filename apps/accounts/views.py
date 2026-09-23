from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes

from .decorators import system_creator_required
from .forms import GroupForm, UserForm
from .models import User


def _activation_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return request.build_absolute_uri(
        reverse("activate_account", kwargs={"uidb64": uid, "token": token})
    )


def _whatsapp_url(user, message):
    digits = "".join(ch for ch in user.whatsapp if ch.isdigit())
    if not digits:
        return ""
    if not digits.startswith("55"):
        digits = "55" + digits
    return f"https://wa.me/{digits}?text={quote(message)}"


def _invite_message(user, activation_url):
    return (
        f"Olá, {user.get_full_name() or user.first_name}. "
        "Seu acesso ao Gestão de Frotas foi criado. "
        "Para definir sua senha e ativar sua conta, acesse o link: "
        f"{activation_url}"
    )


def _ensure_default_groups():
    defaults = ["Administrador", "Gestor", "Operacional", "Consulta"]
    for name in defaults:
        Group.objects.get_or_create(name=name)


@system_creator_required
def user_list(request):
    _ensure_default_groups()
    users = User.objects.prefetch_related("groups").order_by("first_name", "last_name", "email")
    return render(request, "accounts/user_list.html", {"users": users})


@system_creator_required
def user_create(request):
    _ensure_default_groups()
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.username = form.cleaned_data["email"].lower()
            user.set_unusable_password()
            user.is_active = False
            user.save()
            form.save_m2m()
            messages.success(request, "Usuário criado. Use o botão WhatsApp para enviar o link de ativação.")
            return redirect("user_list")
    else:
        form = UserForm(initial={"is_active": True})
    return render(request, "accounts/user_form.html", {"form": form, "title": "Cadastrar usuário"})


@system_creator_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_system_creator and user.pk != request.user.pk:
        raise PermissionDenied
    if request.method == "POST":
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save(commit=False)
            user.username = form.cleaned_data["email"].lower()
            user.save()
            form.save_m2m()
            messages.success(request, "Usuário atualizado com sucesso.")
            return redirect("user_list")
    else:
        form = UserForm(instance=user)
    if user.is_system_creator:
        form.fields["email"].disabled = True
        form.fields["is_active"].disabled = True
        form.fields["groups"].disabled = True
    return render(request, "accounts/user_form.html", {"form": form, "title": "Editar usuário", "editing": True})


@system_creator_required
def user_whatsapp(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_system_creator:
        messages.error(request, "O criador do sistema não utiliza convite de ativação.")
        return redirect("user_list")

    user.set_unusable_password()
    user.is_active = False
    user.save(update_fields=["password", "is_active", "last_changed_at"])
    activation_url = _activation_url(request, user)
    message = _invite_message(user, activation_url)
    whatsapp_url = _whatsapp_url(user, message)
    if not whatsapp_url:
        messages.error(request, "O usuário não possui um WhatsApp válido.")
        return redirect("user_list")
    return redirect(whatsapp_url)


@system_creator_required
def group_list(request):
    _ensure_default_groups()
    groups = Group.objects.prefetch_related("permissions").order_by("name")
    return render(request, "accounts/group_list.html", {"groups": groups})


@system_creator_required
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil criado com sucesso.")
            return redirect("group_list")
    else:
        form = GroupForm()
    return render(request, "accounts/group_form.html", {"form": form, "title": "Novo perfil"})


@system_creator_required
def group_edit(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, "Permissões atualizadas com sucesso.")
            return redirect("group_list")
    else:
        form = GroupForm(instance=group)
    return render(request, "accounts/group_form.html", {"form": form, "title": f"Permissões: {group.name}"})


def activate_account(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if not user or not default_token_generator.check_token(user, token):
        return render(request, "accounts/activate_account.html", {"valid": False})

    if request.method == "POST":
        password = request.POST.get("password", "")
        confirmation = request.POST.get("confirmation", "")
        if len(password) < 8:
            messages.error(request, "A senha deve ter pelo menos 8 caracteres.")
        elif password != confirmation:
            messages.error(request, "As senhas não conferem.")
        else:
            user.set_password(password)
            user.is_active = True
            user.save(update_fields=["password", "is_active", "last_changed_at"])
            login(request, user)
            return redirect("dashboard")

    return render(request, "accounts/activate_account.html", {"valid": True, "user": user})
