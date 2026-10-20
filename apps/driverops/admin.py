from django.contrib import admin
from django.core.exceptions import ValidationError
from django import forms
from .models import Company, Member, CompanyVehicle


class PlatformAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission
    has_delete_permission = has_view_permission


class VehicleForm(forms.ModelForm):
    class Meta:
        model = CompanyVehicle
        fields = "__all__"

    def clean(self):
        data = super().clean()
        company = data.get("company")
        drivers = data.get("drivers")
        if company and drivers is not None and drivers.exclude(company=company, role=Member.DRIVER).exists():
            raise ValidationError("Selecione somente motoristas desta empresa.")
        if company and self.instance.pk and self.instance.trip_set.exists():
            if CompanyVehicle.objects.get(pk=self.instance.pk).company_id != company.pk:
                raise ValidationError("Não é permitido transferir veículo com histórico de BDT.")
        return data


@admin.register(Company)
class CompanyAdmin(PlatformAdmin):
    list_display = ["name", "active"]


@admin.register(Member)
class MemberAdmin(PlatformAdmin):
    list_display = ["user", "company", "role", "active"]

    def get_readonly_fields(self, request, obj=None):
        return ["company", "user", "driver"] if obj and obj.trip_set.exists() else []


@admin.register(CompanyVehicle)
class CompanyVehicleAdmin(PlatformAdmin):
    form = VehicleForm
    list_display = ["label", "company", "active"]
    filter_horizontal = ["drivers"]
