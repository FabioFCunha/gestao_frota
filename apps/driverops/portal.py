from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Member


@login_required
def dashboard(request):
    if not Member.objects.filter(user=request.user, role__in=Member.DESKTOP_ROLES, active=True, company__active=True).exists():
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Acesso exclusivo aos perfis do desktop.")
    from apps.fleet.models import BDT
    if request.GET.get('source') == 'horus' or (request.GET.get('source') != 'app' and BDT.objects.exists()):
        from .horus_panel import horus_dashboard
        return horus_dashboard(request)
    return render(request, "driverops/dashboard.html")
