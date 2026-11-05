"""Merge git identities (login, email, author name) into people.

Rules, in order:
  * a provider login and the commit email it signed are one person
  * GitHub no-reply emails (123+login@users.noreply.github.com) belong to that login
  * the same normalised author name is one person (merge_same_name, default on);
    case, spaces, dots, dashes and underscores are ignored
  * an author name that is an email address counts as that email
  * [identities] in the config forces aliases together under a canonical name
"""
import collections
import re

NOREPLY = re.compile(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$")


def _norm_name(n):
    # "Jane-Doe", "jane.doe" and "Jane Doe" are the same name
    return re.sub(r"[\s._-]+", " ", (n or "").strip().lower()).strip()


class Identities:
    def __init__(self, cfg):
        self.parent = {}
        self.canon = {}  # root -> canonical display name
        self.merge_same_name = cfg.get("merge_same_name", True)
        ex = cfg.get("exclude_authors") or r"(\[bot\]|dependabot|renovate|github-actions|gitlab-ci|noreply@gitlab)"
        self.exclude = re.compile(ex, re.I)
        self.aliases = cfg.get("aliases") or {}

    def _find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def _union(self, a, b):
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            # keep a canonical alias as the root so its display name survives
            if rb.startswith("canon:"):
                ra, rb = rb, ra
            self.parent[rb] = ra

    def _nodes(self, c):
        nodes = []
        if c.get("login"):
            nodes.append("login:" + c["login"].lower())
        if c.get("author_email"):
            nodes.append("email:" + c["author_email"])
            m = NOREPLY.match(c["author_email"])
            if m:
                nodes.append("login:" + m.group(1).lower())
        name = (c.get("author_name") or "").strip()
        if "@" in name and " " not in name:  # author name set to an email address
            nodes.append("email:" + name.lower())
        elif self.merge_same_name and name:
            nodes.append("name:" + _norm_name(name))
        return nodes or ["name:unknown"]

    def build(self, commits):
        for canon, alist in self.aliases.items():
            root = "canon:" + canon
            self._find(root)
            for a in alist:
                a = a.strip().lower()
                if "@" in a:
                    self._union(root, "email:" + a)
                else:
                    self._union(root, "login:" + a)
                    self._union(root, "name:" + _norm_name(a))
        for c in commits:
            n = self._nodes(c)
            for x in n[1:]:
                self._union(n[0], x)
        # display name + id per component
        names = collections.defaultdict(collections.Counter)
        logins = collections.defaultdict(set)
        emails = collections.defaultdict(set)
        for c in commits:
            r = self._find(self._nodes(c)[0])
            names[r][c.get("author_name") or "?"] += 1
            if c.get("login"):
                logins[r].add(c["login"])
            if c.get("author_email"):
                emails[r].add(c["author_email"])
        self.people = {}
        used = set()
        for r in names:
            display = r[6:] if r.startswith("canon:") else names[r].most_common(1)[0][0]
            pid = re.sub(r"[^a-z0-9]+", "-", (sorted(logins[r])[0] if logins[r] else display).lower()).strip("-") or "unknown"
            base, i = pid, 2
            while pid in used:
                pid, i = f"{base}-{i}", i + 1
            used.add(pid)
            self.people[r] = {"id": pid, "name": display, "logins": sorted(logins[r]),
                              "emails": sorted(emails[r]), "names": [n for n, _ in names[r].most_common()]}
        return self

    def person(self, c):
        """Person dict for a commit, or None when the author is excluded (bots)."""
        if self.exclude.search(f"{c.get('author_name')} {c.get('author_email')} {c.get('login') or ''}"):
            return None
        return self.people[self._find(self._nodes(c)[0])]
