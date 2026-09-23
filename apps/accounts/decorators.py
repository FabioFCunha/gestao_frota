from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def system_creator_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.is_system_creator:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped


def module_permission(permission):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.path}")
            if request.user.is_system_creator or request.user.has_perm(permission):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return wrapped
    return decorator
