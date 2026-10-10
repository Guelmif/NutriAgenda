import json
import re

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class InstallationTests(SimpleTestCase):
    def test_manifest_is_public_and_describes_installable_app(self):
        response = self.client.get(reverse("agenda:manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        manifest = response.json()
        self.assertEqual(manifest["name"], "ClínicaUnopar")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], reverse("agenda:calendario"))
        self.assertEqual(manifest["scope"], reverse("agenda:calendario"))
        self.assertEqual(
            {icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"}
        )
        self.assertTrue(any(i["purpose"] == "maskable" for i in manifest["icons"]))
        for icon in manifest["icons"]:
            self.assertTrue(finders.find(icon["src"].removeprefix("/static/")))

    def test_worker_has_root_scope_and_only_public_offline_assets(self):
        response = self.client.get(reverse("agenda:service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertEqual(response["Cache-Control"], "no-cache")
        source = response.content.decode()
        settings = json.loads(re.search(r"self.PWA_CONFIG = (.*);", source)[1])
        self.assertTrue(settings["cacheName"].startswith("clinicaunopar-public-"))
        self.assertIn(settings["offlineUrl"], settings["publicAssets"])
        for url in settings["publicAssets"]:
            self.assertTrue(url.startswith("/static/agenda/pwa/"))
            self.assertTrue(url.endswith((".png", "offline.html")))
            self.assertTrue(finders.find(url.removeprefix("/static/")))
        self.assertIn("importScripts", source)
        self.assertEqual(
            source, self.client.get(reverse("agenda:service_worker")).content.decode()
        )

    @override_settings(STATIC_URL="/assets/")
    def test_custom_static_url_is_used_in_manifest_and_worker(self):
        manifest = self.client.get(reverse("agenda:manifest")).json()
        self.assertTrue(all(i["src"].startswith("/assets/") for i in manifest["icons"]))
        worker = self.client.get(reverse("agenda:service_worker"))
        self.assertContains(worker, "/assets/agenda/pwa/offline.html")

    def test_installation_metadata_rejects_mutations(self):
        for route in ("agenda:manifest", "agenda:service_worker"):
            self.assertEqual(self.client.post(reverse(route)).status_code, 405)

    def test_login_has_installation_metadata_and_invitation(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, "Instalar ClínicaUnopar")
        self.assertContains(response, 'id="install-dialog"')
