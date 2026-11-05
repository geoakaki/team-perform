"""Minimal JSON-over-HTTP client: auth header, retries, rate limits, Link pagination.

The token is held only in memory and sent as a header. It is never logged.
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class Api:
    def __init__(self, base, headers, verify_tls=True, ca_file=None, timeout=40):
        self.base = base.rstrip("/")
        self.headers = {"User-Agent": "teamperf", **headers}
        self.timeout = timeout
        self.ctx = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        if not verify_tls:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        self.calls = 0

    def url(self, path, params=None):
        u = path if path.startswith("http") else self.base + path
        if params:
            u += ("&" if "?" in u else "?") + urllib.parse.urlencode(params)
        return u

    def get(self, path, params=None):
        """Return (data, headers). data is None on 404/409 (missing / empty repo)."""
        url = self.url(path, params)
        for attempt in range(6):
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                    self.calls += 1
                    body = r.read()
                    return (json.loads(body) if body else None), r.headers
            except urllib.error.HTTPError as e:
                if e.code in (404, 409, 410):
                    return None, e.headers
                if e.code == 401:
                    sys.exit(f"401 Unauthorized for {self._safe(url)} - check the token and its scopes")
                if e.code in (403, 429):
                    wait = self._rate_wait(e.headers)
                    if wait is None:  # plain permission error, not rate limiting
                        print(f"  403 forbidden: {self._safe(url)}", file=sys.stderr)
                        return None, e.headers
                    print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
                    time.sleep(wait)
                    continue
                if 500 <= e.code < 600:
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"  HTTP {e.code}: {self._safe(url)}", file=sys.stderr)
                return None, e.headers
            except Exception:  # network drop, timeout, reset
                time.sleep(2 * (attempt + 1))
        print(f"  giving up: {self._safe(url)}", file=sys.stderr)
        return None, {}

    def paged(self, path, params=None, limit=None):
        """Follow Link rel=next. Return list, or None if the first page is missing."""
        out, url, first = [], self.url(path, params), True
        while url:
            data, headers = self.get(url)
            if data is None:
                return None if first else out
            first = False
            out += data if isinstance(data, list) else [data]
            if limit and len(out) >= limit:
                return out[:limit]
            url = self._next(headers)
        return out

    @staticmethod
    def _next(headers):
        link = (headers or {}).get("Link", "") or ""
        for part in link.split(","):
            if 'rel="next"' in part:
                return part[part.find("<") + 1:part.find(">")]
        return None

    @staticmethod
    def _rate_wait(h):
        h = h or {}
        if h.get("Retry-After"):
            return int(float(h["Retry-After"])) + 1
        remaining = h.get("X-RateLimit-Remaining") or h.get("RateLimit-Remaining")
        reset = h.get("X-RateLimit-Reset") or h.get("RateLimit-Reset")
        if remaining == "0" and reset:
            return max(5, int(reset) - int(time.time()) + 2)
        if h.get("X-RateLimit-Remaining") is not None or h.get("RateLimit-Remaining") is not None:
            return 30
        return None

    @staticmethod
    def _safe(url):
        return url.split("?")[0]
