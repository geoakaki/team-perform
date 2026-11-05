"""Provider drivers. Each one normalises repos, commits and commit details to one shape.

  github  GitHub org/user over the REST API (token)
  gitlab  GitLab group/user over the REST API (token, gitlab.com or self-hosted)
  local   git clones on disk: one repo, or every repo under a directory (no token, no network)

repo:   {id, name, archived, last_activity, default_branch, web_url}
commit: {sha, repo, date, author_name, author_email, login, parents, subject, message}
detail: {additions, deletions, files: [{path, status, additions, deletions, patch}]}
"""
import collections
import os
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .http import Api


def resolve_token(src):
    """Token from env var, else from a 1Password reference via `op read` (kept in memory only)."""
    env = src.get("token_env")
    if env and os.environ.get(env):
        return os.environ[env]
    ref = src.get("token_op_ref")
    if ref:
        try:
            return subprocess.run(["op", "read", ref], check=True, capture_output=True, text=True).stdout.strip()
        except Exception as e:
            sys.exit(f"could not read token from 1Password reference ({type(e).__name__})")
    if src.get("allow_anonymous"):
        return ""
    sys.exit(f"no token: set ${env or 'TOKEN'} or source.token_op_ref, or allow_anonymous = true")


def make_provider(src, threads=8):
    kind = src["provider"].lower()
    if kind == "local":
        return Local(src, threads)
    token = resolve_token(src)
    tls = dict(verify_tls=src.get("verify_tls", True), ca_file=src.get("ca_file"))
    if kind == "github":
        base = src.get("base_url") or "https://api.github.com"
        if "api.github.com" not in base and not base.rstrip("/").endswith("/api/v3"):
            base = base.rstrip("/") + "/api/v3"  # GitHub Enterprise Server
        hdr = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            hdr["Authorization"] = f"Bearer {token}"
        return GitHub(src, Api(base, hdr, **tls), threads)
    if kind == "gitlab":
        base = (src.get("base_url") or "https://gitlab.com").rstrip("/")
        if not base.endswith("/api/v4"):
            base += "/api/v4"
        hdr = {"PRIVATE-TOKEN": token} if token else {}
        return GitLab(src, Api(base, hdr, **tls), threads)
    sys.exit(f"unknown provider {kind!r} (github | gitlab | local)")


class _Base:
    def __init__(self, src, api, threads):
        self.src, self.api, self.threads = src, api, threads
        self.scope = src["scope"].strip("/")
        self.include = re.compile(src.get("include") or ".*")
        self.exclude = re.compile(src["exclude"]) if src.get("exclude") else None

    def keep(self, repo, since):
        n = repo["name"]
        if not self.include.search(n) or (self.exclude and self.exclude.search(n)):
            return False
        if repo["archived"] and not self.src.get("include_archived"):
            return False
        return not (repo["last_activity"] and repo["last_activity"] < since)


class GitHub(_Base):
    kind = "github"

    def list_repos(self):
        rows = self.api.paged(f"/orgs/{self.scope}/repos", {"type": "all", "per_page": 100})
        if rows is None:
            rows = self.api.paged(f"/users/{self.scope}/repos", {"type": "owner", "per_page": 100}) or []
        return [{"id": r["full_name"], "name": r["name"], "archived": r["archived"],
                 "last_activity": r["pushed_at"], "default_branch": r["default_branch"],
                 "web_url": r["html_url"]} for r in rows]

    def commits(self, repo, since):
        # GitHub has no all-refs listing, so walk every branch and de-duplicate by sha.
        rid = repo["id"]
        branches = [b["name"] for b in self.api.paged(f"/repos/{rid}/branches", {"per_page": 100}) or []]
        seen = {}
        with ThreadPoolExecutor(self.threads) as pool:
            pages = pool.map(lambda b: self.api.paged(f"/repos/{rid}/commits",
                                                      {"sha": b, "since": since, "per_page": 100}) or [], branches)
            for page in pages:
                for c in page:
                    seen.setdefault(c["sha"], c)
        out = []
        for c in seen.values():
            a = c["commit"]["author"] or {}
            msg = c["commit"]["message"] or ""
            out.append({"sha": c["sha"], "repo": repo["name"], "date": a.get("date"),
                        "author_name": a.get("name") or "", "author_email": (a.get("email") or "").lower(),
                        "login": (c.get("author") or {}).get("login"), "parents": len(c.get("parents") or []),
                        "subject": msg.split("\n", 1)[0], "message": msg})
        return out, len(branches)

    def detail(self, repo_id, sha):
        d, _ = self.api.get(f"/repos/{repo_id}/commits/{sha}")
        if not d:
            return None
        files = [{"path": f["filename"], "status": f["status"], "additions": f["additions"],
                  "deletions": f["deletions"], "patch": f.get("patch") or ""} for f in d.get("files") or []]
        st = d.get("stats") or {}
        return {"additions": st.get("additions", 0), "deletions": st.get("deletions", 0), "files": files}


class GitLab(_Base):
    kind = "gitlab"

    def list_repos(self):
        gid = urllib.parse.quote(self.scope, safe="")
        rows = self.api.paged(f"/groups/{gid}/projects",
                              {"include_subgroups": "true", "per_page": 100, "with_shared": "false"})
        if rows is None:  # scope is a user namespace
            rows = self.api.paged(f"/users/{gid}/projects", {"per_page": 100}) or []
        pre = self.scope + "/"
        return [{"id": str(r["id"]),
                 "name": r["path_with_namespace"][len(pre):] if r["path_with_namespace"].startswith(pre) else r["path_with_namespace"],
                 "archived": r.get("archived", False), "last_activity": r.get("last_activity_at"),
                 "default_branch": r.get("default_branch"), "web_url": r.get("web_url")} for r in rows]

    def commits(self, repo, since):
        rows = self.api.paged(f"/projects/{repo['id']}/repository/commits",
                              {"all": "true", "since": since, "per_page": 100}) or []
        out = [{"sha": c["id"], "repo": repo["name"], "date": c.get("authored_date") or c.get("created_at"),
                "author_name": c.get("author_name") or "", "author_email": (c.get("author_email") or "").lower(),
                "login": None, "parents": len(c.get("parent_ids") or []),
                "subject": c.get("title") or "", "message": c.get("message") or ""} for c in rows]
        return list({c["sha"]: c for c in out}.values()), None

    def detail(self, repo_id, sha):
        d, _ = self.api.get(f"/projects/{repo_id}/repository/commits/{sha}")
        if not d:
            return None
        diffs = self.api.paged(f"/projects/{repo_id}/repository/commits/{sha}/diff", {"per_page": 100}) or []
        files = []
        for f in diffs:
            patch = f.get("diff") or ""
            adds = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
            status = "added" if f.get("new_file") else "removed" if f.get("deleted_file") else \
                "renamed" if f.get("renamed_file") else "modified"
            files.append({"path": f.get("new_path") or f.get("old_path"), "status": status,
                          "additions": adds, "deletions": dels, "patch": patch})
        st = d.get("stats") or {}
        return {"additions": st.get("additions", 0), "deletions": st.get("deletions", 0), "files": files}


# ---------- local clones ----------

class _GitCalls:
    """Stands in for http.Api so the CLI's call counter also works for local runs."""
    def __init__(self):
        self.calls = 0


URL_USERINFO = re.compile(r"(?<=://)[^/@\s]+@")
SKIP_DIRS = {"node_modules", "vendor", ".terraform", "dist", "build", "__pycache__", ".venv", "venv"}
UTC_DATE = "--date=format-local:%Y-%m-%dT%H:%M:%SZ"


class Local(_Base):
    """Commits from git clones on disk. A path is either a repo (any dir inside one works) or a
    directory that is scanned for repos up to `max_depth` levels down. Reads every local branch,
    remote-tracking branch and tag, so run `git fetch --all --prune` first for a current picture."""
    kind = "local"

    def __init__(self, src, threads):
        paths = src.get("paths") or ([src["path"]] if src.get("path") else [])
        if not paths:
            sys.exit("local provider: set source.paths in the config, or pass --local PATH")
        self.paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
        src.setdefault("scope", ", ".join(os.path.basename(p) for p in self.paths))
        super().__init__(src, _GitCalls(), threads)
        self.max_depth = int(src.get("max_depth", 3))

    def git(self, repo, *args):
        self.api.calls += 1
        r = subprocess.run(["git", "-C", repo, "-c", "core.quotePath=false", "-c", "diff.noprefix=false",
                            "-c", "diff.mnemonicPrefix=false", "-c", "log.showSignature=false", *args],
                           capture_output=True, env={**os.environ, "TZ": "UTC", "GIT_PAGER": "cat"})
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None

    def _toplevel(self, path):
        out = self.git(path, "rev-parse", "--show-toplevel")
        return os.path.realpath(out.strip()) if out else None

    def _scan(self, root, depth):
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
            if os.path.exists(os.path.join(e.path, ".git")):
                yield e.path
            elif depth > 1:
                yield from self._scan(e.path, depth - 1)

    def list_repos(self):
        found, seen = [], set()
        for root in self.paths:
            if not os.path.isdir(root):
                sys.exit(f"local provider: {root} is not a directory")
            top = self._toplevel(root)
            pairs = [(top, os.path.basename(top))] if top else \
                [(os.path.realpath(p), os.path.relpath(p, root)) for p in self._scan(root, self.max_depth)]
            for top, name in pairs:
                if top not in seen:
                    seen.add(top)
                    found.append((top, name, os.path.basename(root)))
        names = collections.Counter(n for _, n, _ in found)
        repos, used = [], set()
        for top, name, rootname in found:
            if names[name] > 1:  # two roots each holding an "api" repo
                name = f"{rootname}/{name}"
            base, i = name, 2
            while name in used:
                name, i = f"{base}-{i}", i + 1
            used.add(name)
            if (self.git(top, "rev-parse", "--is-shallow-repository") or "").strip() == "true":
                print(f"  warning: {name} is a shallow clone - history before the shallow point is missing; "
                      f"run `git fetch --unshallow` for a full picture", file=sys.stderr)
            last = self.git(top, "log", "--branches", "--remotes", "--tags", "-1", "--format=%cd", UTC_DATE)
            url = (self.git(top, "config", "--get", "remote.origin.url") or "").strip()
            repos.append({"id": top, "name": name, "archived": False,
                          "last_activity": (last or "").strip() or None,
                          "default_branch": (self.git(top, "symbolic-ref", "--short", "-q", "HEAD") or "").strip() or None,
                          "web_url": URL_USERINFO.sub("", url) or None})  # never keep a token baked into a remote URL
        return repos

    def commits(self, repo, since):
        fmt = "%H%x1f%ad%x1f%an%x1f%ae%x1f%P%x1f%B%x1e"
        out = self.git(repo["id"], "log", "--branches", "--remotes", "--tags", f"--since={since}",
                       UTC_DATE, f"--format={fmt}") or ""
        rows = {}
        for rec in out.split("\x1e"):
            rec = rec.lstrip("\n")
            if not rec:
                continue
            sha, date, name, email, parents, msg = (rec.split("\x1f", 5) + [""] * 6)[:6]
            rows.setdefault(sha, {"sha": sha, "repo": repo["name"], "date": date or None,
                                  "author_name": name, "author_email": email.lower(), "login": None,
                                  "parents": len(parents.split()), "subject": msg.split("\n", 1)[0],
                                  "message": msg.rstrip()})
        refs = (self.git(repo["id"], "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes") or "").split()
        return list(rows.values()), len([r for r in refs if not r.endswith("/HEAD")])

    def detail(self, repo_id, sha):
        out = self.git(repo_id, "show", "--format=", "--patch", "-M", "--no-color", "--no-ext-diff",
                       "--no-textconv", sha)
        if out is None:
            return None
        files = []
        for chunk in re.split(r"(?m)^(?=diff --git )", out):
            if not chunk.startswith("diff --git "):
                continue
            header, sep, rest = chunk.partition("\n@@")
            patch = "@@" + rest if sep else ""
            first, path, old, status = header.split("\n", 1)[0], None, None, "modified"
            for line in header.splitlines()[1:]:
                if line.startswith("new file mode"):
                    status = "added"
                elif line.startswith("deleted file mode"):
                    status = "removed"
                elif line.startswith("rename to "):
                    path, status = line[10:], "renamed"
                elif line.startswith("+++ ") and line[4:] != "/dev/null":
                    path = path or _strip_prefix(line[4:], "b/")
                elif line.startswith("--- ") and line[4:] != "/dev/null":
                    old = _strip_prefix(line[4:], "a/")
            if not path:  # binary or mode-only change: no ---/+++ lines; header is "diff --git a/X b/X"
                s = first[len("diff --git "):]
                path = old or s[(len(s) + 1) // 2:][2:]
            lines = patch.splitlines()
            files.append({"path": path, "status": status,
                          "additions": sum(1 for l in lines if l.startswith("+")),
                          "deletions": sum(1 for l in lines if l.startswith("-")),
                          "patch": patch})
        return {"additions": sum(f["additions"] for f in files),
                "deletions": sum(f["deletions"] for f in files), "files": files}


def _strip_prefix(p, prefix):
    p = p.rstrip("\t")  # git appends a tab when the path holds a space
    if len(p) > 1 and p[0] == p[-1] == '"':
        p = p[1:-1]
    return p[len(prefix):] if p.startswith(prefix) else p
