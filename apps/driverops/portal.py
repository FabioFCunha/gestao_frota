from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Member


@login_required
def dashboard(request):
    if not Member.objects.filter(user=request.user, role=Member.MANAGER, active=True, company__active=True).exists():
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Acesso exclusivo ao gestor da empresa.")
    return render(request, "driverops/dashboard.html")
