import io
import json
from pathlib import Path
from PIL import Image
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import Member, Trip

ROOT = Path(__file__).parent / "pwa"
ASSETS = {"app.js": "text/javascript", "rules.mjs": "text/javascript",
          "sw.js": "text/javascript", "addresses.mjs": "text/javascript", "style.css": "text/css"}


@login_required
@ensure_csrf_cookie
def app(request):
    if request.user.is_superuser:
        if getattr(settings, "CENTRAL_USER_MANAGEMENT", False):
            from .surfaces import management_url
            return redirect(management_url("/empresas/"))
        return redirect("/api/driver/management/")
    member = Member.objects.filter(user=request.user, active=True, company__active=True).first()
    if not member:
        return HttpResponse("Usuário sem empresa ativa.", status=403)
    if member.role != Member.DRIVER:
        if getattr(settings, "CENTRAL_USER_MANAGEMENT", False):
            from .surfaces import management_url
            return redirect(management_url())
        return redirect("/")
    response = render(request, "driverops/app.html")
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


def asset(request, name):
    if name not in ASSETS:
        return HttpResponse(status=404)
    response = HttpResponse((ROOT / name).read_text(), content_type=ASSETS[name])
    response["Cache-Control"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def manifest(request):
    response = JsonResponse({
        "id": "/api/driver/app/", "name": "Transfrota Motorista",
        "short_name": "Transfrota", "lang": "pt-BR",
        "start_url": "/api/driver/app/", "scope": "/api/driver/app/",
        "display": "standalone", "background_color": "#f1f5f9", "theme_color": "#0f766e",
        "icons": [{"src": f"/api/driver/app/icon-{size}.png?v=brand1", "sizes": f"{size}x{size}",
                   "type": "image/png", "purpose": "any maskable"} for size in (192, 512)],
    }, content_type="application/manifest+json")
    response["Cache-Control"] = "no-cache"
    return response


def icon(request, size):
    if size not in (192, 512):
        return HttpResponse(status=404)
    image = Image.new("RGB", (size, size), "white")
    with Image.open(settings.BASE_DIR / "static/images/transfrota-logo.png") as source:
        logo = source.convert("RGBA")
        logo.thumbnail((round(size * .76), round(size * .76)), Image.Resampling.LANCZOS)
        image.paste(logo, ((size-logo.width)//2, (size-logo.height)//2), logo)
    output = io.BytesIO()
    image.save(output, "PNG")
    response = HttpResponse(output.getvalue(), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    return response


@login_required
@require_POST
def signout(request):
    if Trip.objects.filter(member__user=request.user, closed_at=None).exists():
        return JsonResponse({"detail": "Encerre o BDT antes de sair."}, status=400)
    logout(request)
    response = JsonResponse({"ok": True})
    response["Cache-Control"] = "no-store"
    return response
