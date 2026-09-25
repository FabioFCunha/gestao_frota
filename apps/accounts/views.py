from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import system_creator_required
from .forms import FleetPasswordChangeForm, GroupForm, UserForm
from .models import User


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
            user.set_password(form.cleaned_data["initial_password"])
            user.must_change_password = True
            user.save()
            form.save_m2m()
            messages.success(
                request,
                "Usuário criado. Entregue a senha inicial ao usuário; ela deverá ser trocada no primeiro acesso.",
            )
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
            if form.cleaned_data.get("initial_password"):
                user.set_password(form.cleaned_data["initial_password"])
                user.must_change_password = True
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
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "title": "Editar usuário", "editing": True},
    )


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


class FleetPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = FleetPasswordChangeForm
    success_url = "/"

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password", "last_changed_at"])
        messages.success(self.request, "Senha alterada com sucesso.")
        return response
