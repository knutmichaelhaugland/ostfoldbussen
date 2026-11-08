"""Offentlig nettside: sentralt SMS-nummer, placeholder og ingen falske påstander."""

import tempfile
import unittest

from tests.helpers import RunningApp


class PublicSiteTests(unittest.TestCase):
    def _app(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, overrides)
        app.__enter__()
        self.addCleanup(app.__exit__)
        self.addCleanup(tmp.cleanup)
        return app

    def test_number_placeholder_when_not_configured(self):
        page = self._app().get("/")
        self.assertIn("SMS-nummeret er ikke aktivert ennå.", page.text)
        self.assertNotIn("sms:", page.text)
        self.assertNotIn("Send SMS</a>", page.text)

    def test_number_set_but_disabled_shows_placeholder_not_link(self):
        page = self._app(public_sms_number="+47 123 45 678",
                         public_sms_enabled=False).get("/")
        self.assertIn("SMS-nummeret er ikke aktivert ennå.", page.text)
        self.assertNotIn("sms:", page.text)
        self.assertNotIn("+47 123 45 678", page.text)

    def test_enabled_number_renders_sms_link_and_number(self):
        page = self._app(public_sms_number="+47 123 45 678",
                         public_sms_enabled=True).get("/")
        self.assertIn("+47 123 45 678", page.text)
        self.assertIn("sms:+4712345678", page.text)
        self.assertIn("Send SMS", page.text)

    def test_contact_without_email_does_not_invent_address(self):
        page = self._app().get("/kontakt")
        self.assertNotIn("hjelp@", page.text)
        self.assertIn("Send en melding", page.text)
        self.assertNotIn("mailto:", page.text)

    def test_contact_with_email_renders_mailto(self):
        page = self._app(public_contact_email="post@example.no").get("/kontakt")
        self.assertIn("mailto:post@example.no", page.text)

    def test_no_coming_soon_or_staging_wording_on_home(self):
        text = self._app().get("/").text.lower()
        self.assertNotIn("kommer snart", text)
        self.assertNotIn("under utvikling", text)
        self.assertNotIn("privat staging", text)


class RedesignStructureTests(unittest.TestCase):
    def _app(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, overrides)
        app.__enter__()
        self.addCleanup(app.__exit__)
        self.addCleanup(tmp.cleanup)
        return app

    def test_header_nav_is_simplified_and_footer_has_data_status(self):
        html = self._app().get("/").text
        header = html.split("</header>", 1)[0]
        footer = html.split("<footer", 1)[1]
        for label in ("Slik fungerer det", "Om", "Kontakt"):
            self.assertIn(label, header)
        for label in ("Data og lisens", "Driftsstatus", "Personvern"):
            self.assertNotIn(label, header)
            self.assertIn(label, footer)

    def test_logo_and_mobile_menu_exist(self):
        html = self._app().get("/").text
        self.assertIn('class="brand-mark"', html)
        self.assertIn('<details class="menu-mobile">', html)
        self.assertIn("<summary>Meny</summary>", html)

    def test_hero_has_no_phone_and_sms_dialog_is_in_own_section(self):
        html = self._app().get("/").text
        hero = html.split('class="hero"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn('class="phone"', hero)
        conversation = html.split('class="conversation-demo"', 1)[1]
        self.assertIn('class="phone"', conversation)
        self.assertIn("Eksempel på SMS-samtale hentet fra Entur", conversation)
        self.assertIn("bubble out", conversation)

    def test_footer_is_consistent_on_subpages(self):
        for path in ("/slik-fungerer-det", "/om", "/personvern", "/data", "/kontakt", "/status"):
            html = self._app().get(path).text
            self.assertIn("Data og lisens", html.split("<footer", 1)[1], path)
            self.assertIn("Driftsstatus", html.split("<footer", 1)[1], path)

    def test_subpage_prose_and_page_hero(self):
        html = self._app().get("/om").text
        self.assertIn('class="page-hero"', html)
        self.assertIn('class="wrap prose"', html)


class IllustrationConsistencyTests(unittest.TestCase):
    def test_illustration_uses_context_instead_of_reasking_origin(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("Fra Skredderåsen til Refsnes", html)
        self.assertIn("08:54 linje 22", html)
        self.assertIn("09:05 linje 20", html)
        self.assertIn("hentet fra Entur", html)
        self.assertNotIn("Hvor reiser du fra?", html)
        self.assertNotIn("framme 09:03", html)


class StepsIntroPlacementTests(unittest.TestCase):
    def test_intro_text_comes_after_the_three_steps(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("Skriv en SMS", html)
        self.assertIn("Vi sjekker", html)
        self.assertIn("Få svar", html)
        self.assertEqual(html.count('class="step"'), 3)
        self.assertNotIn("Fire enkle trinn", html)
        self.assertGreater(html.index("Østfoldbussen spørre deg om en presisering"), html.index("</ol>"))


class ExamplesSubtitleTests(unittest.TestCase):
    def test_examples_subtitle_sits_under_heading(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        heading = html.index("Hva kan du spørre om?")
        subtitle = html.index("Skriv som du ville spurt en venn")
        grid = html.index('class="featured-examples"')
        self.assertGreater(subtitle, heading)
        self.assertLess(subtitle, grid)
        self.assertEqual(html.count("Skriv som du ville spurt en venn"), 1)


class IllustrationWordingTests(unittest.TestCase):
    def test_illustration_does_not_call_the_service_inactive(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertNotIn("Ikke en aktiv tjeneste", html)
        self.assertIn("Eksempel på SMS-samtale hentet fra Entur", html)

    def test_journey_choice_is_explained(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/slik-fungerer-det").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("første som gir en gyldig reise med nødvendig overgang", html)


class StatusPageLanguageTests(unittest.TestCase):
    def test_status_page_uses_plain_language_not_technical_metadata(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/status").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("Sist oppdatert:", html)
        self.assertIn("Reiseinformasjon", html)
        for technical in ("Bygg:", "Oppetid:", "overordnet tilstand", "build_sha", "T07:", "Z"):
            self.assertNotIn(technical, html)


class MatomoTests(unittest.TestCase):
    def _app(self, **overrides):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, overrides)
        app.__enter__()
        self.addCleanup(app.__exit__)
        self.addCleanup(tmp.cleanup)
        return app

    def test_no_tracking_by_default(self):
        html = self._app().get("/").text
        self.assertNotIn("matomo.js", html)
        self.assertNotIn("_paq", html)

    def test_cookieless_tracking_when_enabled(self):
        html = self._app(public_matomo_enabled=True,
                         public_matomo_url="https://ostfoldbussen.no/",
                         public_matomo_site_id="1").get("/").text
        self.assertIn('src="/matomo-init.js"', html)
        self.assertIn("data-matomo-url", html)

    def test_privacy_page_mentions_matomo_without_cookies(self):
        html = self._app().get("/personvern").text
        self.assertIn("Matomo", html)
        self.assertIn("uten informasjonskapsler", html)


class MatomoInitRouteTests(unittest.TestCase):
    def test_matomo_init_script_is_served_and_cookieless(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            response = app.get("/matomo-init.js")
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertEqual(response.status, 200)
        self.assertIn("text/javascript", response.headers["content-type"])
        body = response.text
        self.assertIn("disableCookies", body)
        self.assertIn("matomo.php", body)


class ActiveNumberTests(unittest.TestCase):
    def test_active_number_is_formatted_and_has_sms_link(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, {
            "public_sms_enabled": True,
            "public_sms_number": "+4700000000",
        })
        app.__enter__()
        try:
            html = app.get("/").text
            contact = app.get("/kontakt").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("+47 000 00 000", html)
        self.assertIn("sms:+4700000000", html)
        self.assertNotIn("+47 000 00 000", contact)
        self.assertNotIn("sms:", contact)
        self.assertNotIn("ikke aktivert ennå", html)


class R52StructureTests(unittest.TestCase):
    def _html(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, {
            "public_sms_enabled": True,
            "public_sms_number": "+4700000000",
        })
        app.__enter__()
        self.addCleanup(app.__exit__)
        self.addCleanup(tmp.cleanup)
        return app.get("/").text

    def test_hero_is_two_columns_with_action_right(self):
        html = self._html()
        self.assertIn('class="hero-content"', html)
        self.assertIn('class="hero-action"', html)
        self.assertLess(html.index('class="hero-content"'), html.index('class="hero-action"'))
        self.assertIn("Gratis tjeneste", html)
        self.assertIn("Ingen app", html)
        self.assertIn("Ingen innlogging", html)

    def test_number_panel_uses_calm_active_copy(self):
        html = self._html()
        panel = html.split('class="number-panel"', 1)[1].split("</div>", 1)[0]
        self.assertIn("Send SMS til Østfoldbussen", panel)
        self.assertIn("+47 000 00 000", panel)
        self.assertIn("Send SMS", panel)
        self.assertIn("Lagre nummeret i kontakter", panel)
        self.assertIn("Vanlig SMS-takst kan gjelde", panel)
        self.assertIn("kan «hikke» litt", panel)
        self.assertNotIn("vcard-tip", panel)

    def test_three_featured_examples_not_six_boxes(self):
        html = self._html()
        self.assertEqual(html.count('class="example-featured"'), 3)
        self.assertEqual(html.count('class="example"'), 0)
        self.assertIn("Du kan også spørre om", html)

    def test_cta_contains_contact_tip(self):
        text = " ".join(self._html().split())
        self.assertIn("Lagre Østfoldbussen i kontaktlisten din", text)
        self.assertIn("Da slipper du å huske nummeret", text)


class GithubLinkTests(unittest.TestCase):
    def test_github_link_in_footer_and_data_page(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            home = app.get("/").text
            data = app.get("/data").text
        finally:
            app.__exit__()
            tmp.cleanup()
        url = "https://github.com/knutmichaelhaugland/ostfoldbussen"
        for html in (home, data):
            self.assertIn(url, html)
            self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn(url, home.split("<footer", 1)[1])


class AttributionTests(unittest.TestCase):
    def test_developer_credit_and_license_status(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            home = app.get("/").text
            about = app.get("/om").text
            data = app.get("/data").text
        finally:
            app.__exit__()
            tmp.cleanup()
        for html in (home, about):
            self.assertIn("Tjenesten er utviklet av", html)
            self.assertIn("Knut Michael Haugland", html)
            self.assertIn('href="https://knutmichael.com"', html)
            self.assertIn('target="_blank"', html)
            self.assertIn('rel="noopener noreferrer"', html)
            self.assertIn("Kildekoden er lisensiert under MIT-lisensen", html)
        self.assertIn("MIT-lisensen", data)


class LicenseTests(unittest.TestCase):
    def test_mit_license_file_and_site_copy(self):
        from pathlib import Path
        license_text = Path("LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Knut Michael Haugland", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)

    def test_data_page_states_mit_and_nlod(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            data = app.get("/data").text
            home = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("MIT-lisensen", data)
        self.assertIn("NLOD 2.0", data)
        self.assertIn("MIT-lisensen", home)


class PrivacySubprocessorTests(unittest.TestCase):
    def test_privacy_lists_verified_subprocessors_and_llm_scope(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/personvern").text
        finally:
            app.__exit__()
            tmp.cleanup()
        for expected in ("Underleverandører", "WAYSCloud AS", "inMobile ApS",
                         "Bineric AS", "Entur AS", "Qwen 235B",
                         "I den offisielle konfigurasjonen sendes ikke telefonnummer",
                         "AWS Stockholm"):
            self.assertIn(expected, html)
        self.assertIn("https://bineric.com/legal/dpa", html)
        self.assertIn("https://www.inmobile.com/en/privacy-policy", html)


class StatusNoticeTests(unittest.TestCase):
    def test_manual_status_notice_is_rendered(self):
        import tempfile
        text = "Enkelte mobiloperatører har utfordringer med å levere SMS-svar for øyeblikket. Dersom du ikke får svar, prøv gjerne igjen senere."
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, {"status_notice": text})
        app.__enter__()
        try:
            html = app.get("/status").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn(text, html)
        self.assertIn('role="status"', html)
        self.assertIn("Noen deler har problemer", html)
        self.assertIn("Utfordringer", html)


class PrivacyContactTests(unittest.TestCase):
    def test_privacy_rights_use_email_not_sms(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name, {"public_contact_email": "hjelp@ostfoldbussen.no"})
        app.__enter__()
        try:
            html = app.get("/personvern").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("hjelp@ostfoldbussen.no", html)
        self.assertNotIn("SMS-nummeret på forsiden", html)


class DataLicenseTextTests(unittest.TestCase):
    def test_data_page_uses_deles_and_repo_cleanup_note(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            html = app.get("/data").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertIn("deles og videreutvikles", html)
        self.assertNotIn("delas og videreutvikles", html)
        self.assertIn("opprydning i repoet", html)
        self.assertIn("uke 46", html)


class SeoTests(unittest.TestCase):
    def test_sitemap_and_robots(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            sitemap = app.get("/sitemap.xml")
            robots = app.get("/robots.txt")
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertEqual(sitemap.status, 200)
        self.assertIn("application/xml", sitemap.headers["content-type"])
        self.assertIn("https://ostfoldbussen.no/", sitemap.text)
        self.assertIn("https://ostfoldbussen.no/status", sitemap.text)
        self.assertNotIn("/admin", sitemap.text)
        self.assertEqual(robots.status, 200)
        self.assertIn("text/plain", robots.headers["content-type"])
        self.assertIn("Disallow: /admin", robots.text)
        self.assertIn("Sitemap: https://ostfoldbussen.no/sitemap.xml", robots.text)

    def test_pages_have_unique_seo_metadata(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            paths = ["/", "/slik-fungerer-det", "/om", "/kontakt", "/personvern", "/data", "/status"]
            pages = {path: app.get(path).text for path in paths}
        finally:
            app.__exit__()
            tmp.cleanup()
        descriptions = []
        for path, html in pages.items():
            self.assertIn('<link rel="canonical" href="https://ostfoldbussen.no', html)
            self.assertIn('property="og:title"', html)
            self.assertIn('application/ld+json', html)
            self.assertIn('name="robots" content="index,follow"', html)
            self.assertEqual(html.count("<h1"), 1, path)
            match = __import__("re").search(r'<meta name="description" content="([^"]*)"', html)
            self.assertIsNotNone(match)
            descriptions.append(match.group(1))
        self.assertEqual(len(descriptions), len(set(descriptions)))


class NotFoundSeoTests(unittest.TestCase):
    def test_404_is_noindex(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            response = app.get("/finnes-ikke")
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertEqual(response.status, 404)
        self.assertIn('name="robots" content="noindex"', response.text)
        self.assertNotIn('rel="canonical"', response.text)


class OpenGraphImageTests(unittest.TestCase):
    def test_og_image_route_and_meta(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            image = app.get("/og-image.png")
            home = app.get("/").text
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertEqual(image.status, 200)
        self.assertIn("image/png", image.headers["content-type"])
        self.assertIn('property="og:image"', home)
        self.assertIn("og-image.png", home)
        self.assertIn('name="twitter:card" content="summary_large_image"', home)


class AboutAliasTests(unittest.TestCase):
    def test_about_redirects_to_om(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        app = RunningApp(tmp.name)
        app.__enter__()
        try:
            response = app.get("/about")
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertEqual(response.status, 301)
        self.assertEqual(response.headers["location"], "/om")
