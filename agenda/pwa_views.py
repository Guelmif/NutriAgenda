"""Public installation metadata; no patient data belongs in the offline cache."""

import hashlib
import json
from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET

ICON_FILES = (
    ("icon-192.png", "192x192", "any"),
    ("icon-512.png", "512x512", "any"),
    ("icon-maskable-512.png", "512x512", "maskable"),
)
PUBLIC_FILES = (
    "agenda/pwa/offline.html",
    "agenda/pwa/apple-touch-icon.png",
    *(f"agenda/pwa/{filename}" for filename, _, _ in ICON_FILES),
)


@require_GET
def manifest(request):
    home = reverse("agenda:calendario")
    response = JsonResponse(
        {
            "id": home,
            "name": "ClínicaUnopar",
            "short_name": "ClínicaUnopar",
            "description": "Agenda e atendimentos da ClínicaUnopar.",
            "lang": "pt-BR",
            "start_url": home,
            "scope": home,
            "display": "standalone",
            "background_color": "#f6f8f5",
            "theme_color": "#166b50",
            "prefer_related_applications": False,
            "icons": [
                {
                    "src": static(f"agenda/pwa/{filename}"),
                    "sizes": sizes,
                    "type": "image/png",
                    "purpose": purpose,
                }
                for filename, sizes, purpose in ICON_FILES
            ],
        },
        content_type="application/manifest+json",
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def service_worker(request):
    # Content-based versions refresh the public offline page and icons on deploy.
    digest = hashlib.sha256()
    for filename in (*PUBLIC_FILES, "agenda/pwa/worker.js"):
        digest.update(filename.encode())
        digest.update(Path(finders.find(filename)).read_bytes())
    settings = {
        "cacheName": f"clinicaunopar-public-{digest.hexdigest()[:16]}",
        "offlineUrl": static(PUBLIC_FILES[0]),
        "publicAssets": [static(filename) for filename in PUBLIC_FILES],
    }
    source = (
        f"self.PWA_CONFIG = {json.dumps(settings)};\n"
        f"importScripts({json.dumps(static('agenda/pwa/worker.js'))});\n"
    )
    response = HttpResponse(source, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = reverse("agenda:calendario")
    return response
