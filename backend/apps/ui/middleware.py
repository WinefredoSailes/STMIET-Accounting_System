"""Screen access enforcement (ADR-047).

One chokepoint for both surfaces: it resolves the incoming path to a screen
key from the registry (``apps.ui.screens``) and 403s anything the signed-in
user's effective screens exclude. That covers page GETs, HTMX fragments,
exports, print views, deep-typed URLs, and the DRF API alike — a hidden
screen is also a *denied* screen, never just a missing link.

Unauthenticated requests pass through untouched (the auth gate handles
those), as do superusers and everything the registry marks public/shared.
"""

from __future__ import annotations

from django.http import HttpResponseForbidden, JsonResponse
from django.urls import Resolver404, resolve

from .screens import effective_screens, screen_for_api_path, screen_for_url_name

_FORBIDDEN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Not on your desk</title>
<style>
 body{{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;background:#fafaf9;color:#1c1917;
      display:flex;align-items:center;justify-content:center;min-height:100vh}}
 .card{{max-width:28rem;text-align:center;padding:2.5rem;border:1px solid #e7e5e4;border-radius:1rem;
       background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.05)}}
 h1{{font-size:1.1rem;margin:0 0 .5rem}} p{{font-size:.85rem;color:#57534e;margin:.35rem 0}}
 a{{color:#0d9488;font-weight:600;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head>
<body><div class="card">
 <h1>403 &mdash; Not on your desk</h1>
 <p>This screen is not part of your assigned access. Ask the administrator
 if you believe you need it.</p>
 <p><a href="/">&larr; Back to your dashboard</a></p>
</div></body></html>"""


class ScreenAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or user.is_superuser:
            return self.get_response(request)

        screen = self._screen(request)
        if screen is not None and screen not in effective_screens(user):
            return self._denied(request)
        return self.get_response(request)

    @staticmethod
    def _screen(request):
        path = request.path_info
        if path.startswith("/api/"):
            return screen_for_api_path(path)
        try:
            match = resolve(path)
        except Resolver404:
            return None
        if match.namespace != "ui":
            return None  # django admin etc. keep their own gates
        return screen_for_url_name(match.url_name)

    @staticmethod
    def _denied(request):
        if request.path_info.startswith("/api/"):
            return JsonResponse(
                {"detail": "This screen is not part of your assigned access."},
                status=403,
            )
        return HttpResponseForbidden(_FORBIDDEN_HTML)
