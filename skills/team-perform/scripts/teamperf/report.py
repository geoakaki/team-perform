"""Build the HTML report from people.json plus the optional reviewer files.

  reviews/<person>.json   per-person review (scores, verdict, strengths, issues, area)
  reviews/_summary.json   recommendation box: headline, picks, a role table, two columns, a closing ask
  reviews/_report.json    page text: title, eyebrow, lede, repo_groups, curated security issues, method notes

`report` writes report.html for you. `export` writes export.html, the same page made ready to
publish or send: emails and author-name variants are never in it, and --anonymize also replaces
every person's name and login with "Developer A", "Developer B", ...
"""
import datetime as dt
import glob
import json
import os
import re
import string

TEMPLATE = os.path.join(os.path.dirname(__file__), "report_template.html")


def _load(path):
    with open(path) as f:
        return json.load(f)


def collect(ctx):
    people = _load(ctx.p("people.json"))
    meta = _load(ctx.p("repos.json"))
    reviews, summary, page = {}, None, {}
    for f in glob.glob(ctx.p("reviews", "*.json")):
        d = _load(f)
        base = os.path.basename(f)
        if base == "_summary.json":
            summary = d
        elif base == "_report.json":
            page = d
        elif not base.startswith("_"):
            reviews[d.get("person") or base[:-5]] = d
    for p in people:
        if p["id"] in reviews:
            p["review"] = reviews[p["id"]]
        # the page never shows emails; keep them out of the embedded data so a shared report can't leak them
        p.pop("emails", None)
        p.pop("names", None)
    scanned = [r for r in meta["repos"] if r.get("scanned")]
    return {
        "meta": {"name": ctx.name, "provider": meta["provider"], "scope": meta["scope"],
                 "since": meta["since"][:10], "until": meta["until"],
                 "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "repos_total": len(meta["repos"]), "repos_scanned": len(scanned),
                 "per_person": ctx.per_person, "weights": ctx.weights},
        "people": people,
        "quiet_repos": sorted(r["name"] for r in meta["repos"] if not any(r["name"] in p["per_repo"] for p in people)),
        "summary": summary,
        "report": page,
    }


def render(data, out):
    title = (data.get("report") or {}).get("title") or f"{data['meta']['scope']} Team Scorecard"
    blob = json.dumps(data).replace("</", "<\\/")
    html = open(TEMPLATE).read().replace("__DATA__", blob).replace("__TITLE__", _html_escape(title))
    with open(out, "w") as f:
        f.write(html)
    return out


def build(ctx):
    return render(collect(ctx), ctx.p("report.html"))


def export(ctx, anonymize=False, title=None):
    data = collect(ctx)
    for p in data["people"]:
        p.pop("emails", None)
        p.pop("names", None)
    left = []
    if anonymize:
        left = _anonymize(data)
    if title:
        data["report"] = {**(data.get("report") or {}), "title": title}
    return render(data, ctx.p("export.html")), left


def _html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pseudonym(i):
    letters = string.ascii_uppercase
    return "Developer " + (letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26])


def _anonymize(data):
    """Replace names, first names and logins everywhere, including reviewer free text.
    Returns the names that still appear after replacement (should be empty)."""
    people = data["people"]
    first = {}
    for p in people:
        f = p["name"].split()[0] if p["name"].split() else ""
        first.setdefault(f.lower(), set()).add(p["id"])
    has_rev = any(p.get("review") for p in people)
    score = lambda p: (p["review"].get("overall") if has_rev and p.get("review") else p["heur"]["overall"]) or -1
    repl = {}
    for i, p in enumerate(sorted(people, key=score, reverse=True)):  # Developer A = rank 1 on the page
        alias = _pseudonym(i)
        tokens = {p["name"], p["id"], *p.get("logins", [])}
        tokens |= {p["name"].replace(" ", "")}
        f = p["name"].split()[0] if p["name"].split() else ""
        if len(f) >= 3 and len(first[f.lower()]) == 1:  # a first name shared by two people is ambiguous
            tokens.add(f)
        for t in tokens:
            if t and len(t) >= 3:
                repl[t.lower()] = alias
        p["_alias"] = alias
    rx = re.compile(r"(?<![\w@])@?(" + "|".join(re.escape(t) for t in sorted(repl, key=len, reverse=True)) + r")(?!\w)",
                    re.I) if repl else None

    def sub(v):
        if isinstance(v, str):
            return rx.sub(lambda m: repl[m.group(1).lower()], v) if rx else v
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v

    originals = [(p["name"], p["id"], list(p.get("logins", []))) for p in people]
    for p in people:
        alias = p.pop("_alias")
        for k in ("review", "sample_commits"):
            if k in p:
                p[k] = sub(p[k])
        if p.get("review"):
            p["review"]["person"] = alias.lower().replace(" ", "-")
        p["name"], p["id"], p["logins"] = alias, alias.lower().replace(" ", "-"), []
    for k in ("summary", "report"):
        if data.get(k):
            data[k] = sub(data[k])
    blob = json.dumps(data).lower()
    return sorted({n for name, pid, logins in originals for n in (name, pid, *logins)
                   if len(n) >= 3 and re.search(r"(?<![\w@])" + re.escape(n.lower()) + r"(?!\w)", blob)})
