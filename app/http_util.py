"""HTTP-hjelpere for leverandørkall.

Providerkall skal ikke følge redirects: en 302 kan ellers flytte et
Authorization-header til en annen vert. Tvetydige/feil svar håndteres av
adapteren, ikke av urllibs redirect-policy.
"""
from __future__ import annotations

import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_no_redirect(request: urllib.request.Request, *, timeout: float):
    opener = urllib.request.build_opener(_NoRedirect())
    return opener.open(request, timeout=timeout)
