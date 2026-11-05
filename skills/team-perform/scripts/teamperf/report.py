"""Build a single self-contained HTML report from people.json (+ optional reviews/*.json)."""
import datetime as dt
import glob
import json
import os

TEMPLATE = os.path.join(os.path.dirname(__file__), "report_template.html")


def build(ctx):
    people = json.load(open(ctx.p("people.json")))
    meta = json.load(open(ctx.p("repos.json")))
    reviews, summary = {}, None
    for f in glob.glob(ctx.p("reviews", "*.json")):
        d = json.load(open(f))
        if os.path.basename(f) == "_summary.json":
            summary = d
        else:
            reviews[d.get("person") or os.path.basename(f)[:-5]] = d
    for p in people:
        if p["id"] in reviews:
            p["review"] = reviews[p["id"]]
        # the page never shows emails; keep them out of the embedded data so a shared report can't leak them
        p.pop("emails", None)
        p.pop("names", None)
    scanned = [r for r in meta["repos"] if r.get("scanned")]
    data = {
        "meta": {"name": ctx.name, "provider": meta["provider"], "scope": meta["scope"],
                 "since": meta["since"][:10], "until": meta["until"],
                 "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "repos_total": len(meta["repos"]), "repos_scanned": len(scanned),
                 "per_person": ctx.per_person, "weights": ctx.weights},
        "people": people,
        "quiet_repos": sorted(r["name"] for r in meta["repos"] if not any(r["name"] in p["per_repo"] for p in people)),
        "summary": summary,
    }
    blob = json.dumps(data).replace("</", "<\\/")
    html = open(TEMPLATE).read().replace("__DATA__", blob).replace("__TITLE__", f"{meta['scope']} Team Scorecard")
    out = ctx.p("report.html")
    open(out, "w").write(html)
    return out
