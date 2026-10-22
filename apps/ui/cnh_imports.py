from urllib.parse import urlencode
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from apps.accounts.decorators import module_permission
from apps.fleet.models import CNHImportJob
from apps.fleet.cnh_jobs import enqueue, retry
from .cnh_safety import staged_document


def enqueue_response(request, file_obj, driver=None):
    job = enqueue(file_obj=file_obj, user=request.user, driver=driver, sector=request.GET.get('sector', ''))
    return redirect('cnh_import_status', pk=job.pk)


def review_url(job):
    if job.state == 'confirmed':
        return reverse('driver_cnh', args=[job.driver_id]) if job.driver_id else reverse('driver_list')
    route = reverse('driver_cnh', args=[job.driver_id]) if job.driver_id else reverse('driver_create')
    return route + '?' + urlencode({'import':str(job.pk), **({'sector':job.sector} if job.sector else {})})


def imported_document(request, driver=None):
    import uuid
    from django.http import Http404
    try:
        identifier = uuid.UUID(request.GET['import'])
    except (ValueError, TypeError) as exc:
        raise Http404 from exc
    job = get_object_or_404(CNHImportJob, pk=identifier, created_by=request.user,
        driver=driver, state='ready')
    document, audit = staged_document(request, job.document_id)
    return document, dict(audit.new_values or {})


@login_required
def import_status(request, pk):
    job = get_object_or_404(CNHImportJob, pk=pk, created_by=request.user)
    permission = 'fleet.change_driver' if job.driver_id else 'fleet.add_driver'
    if not request.user.has_perm(permission):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    error = ''
    if request.method == 'POST':
        try:
            retry(job)
        except ValueError as exc:
            error = str(exc)
        job.refresh_from_db()
    if request.GET.get('format') == 'json':
        response = JsonResponse({'state':job.state, 'label':job.get_state_display(), 'error':job.error,
            'review_url':review_url(job) if job.state in ('ready','confirmed') else None})
        add_never_cache_headers(response)
        return response
    if job.state in ('ready','confirmed'):
        return redirect(review_url(job))
    response = render(request, 'ui/cnh_import_status.html', {'job':job, 'retry_error':error})
    add_never_cache_headers(response)
    return response


@login_required
@module_permission('fleet.correct_driver_identity')
def import_monitor(request):
    jobs = CNHImportJob.objects.all()
    counts = list(jobs.values('state').annotate(total=Count('pk')))
    for item in counts:
        item['label'] = CNHImportJob.State(item['state']).label
    return render(request, 'ui/cnh_import_monitor.html', {'jobs':jobs.select_related('created_by').order_by('-created_at')[:100], 'counts':counts})
