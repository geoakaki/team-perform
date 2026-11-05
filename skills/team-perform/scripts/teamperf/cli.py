"""teamperf CLI.

  Source: a config file (-c), local clones (--local PATH, repeatable), or both: then the config
  supplies window / people / weights and --local replaces its [source].

  tp collect  -c cfg   list repos + every commit in the window (all branches)  -> repos.json, commits.jsonl
  tp sample   -c cfg   last N non-merge commits per person, with diffs          -> sample/<person>.json
  tp score    -c cfg   people, matrix, rule-based scores                        -> people.json, matrix.csv, scores.csv
  tp bundle   -c cfg   compact per-person review packs for an LLM reviewer      -> bundle/<person>.md
  tp report   -c cfg   self-contained HTML report (merges reviews/*.json)       -> report.html
  tp all      -c cfg   all of the above in order
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor

from . import heuristics, report
from .identity import Identities
from .providers import make_provider

DEFAULT_WEIGHTS = {"messages": 0.20, "size": 0.20, "tests": 0.15, "hygiene": 0.25, "security": 0.20}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- config / paths ----------

LOCAL_SOURCE_KEYS = ("include", "exclude", "max_depth", "scope")


class Ctx:
    def __init__(self, path, overrides):
        c = {}
        if path:
            with open(path, "rb") as f:
                c = tomllib.load(f)
        if overrides.local:
            old = c.get("source", {})
            keep = {k: old[k] for k in LOCAL_SOURCE_KEYS if k in old} if old.get("provider") == "local" else {}
            c["source"] = {**keep, "provider": "local", "paths": overrides.local}
            c.pop("name", None)  # the config's name belongs to its own source; derive one from the paths
        if "source" not in c:
            sys.exit("no source: pass -c <config.toml> and/or --local <path>")
        self.cfg = c
        self.src = c["source"]
        if self.src["provider"] == "local" and not self.src.get("scope"):
            paths = self.src.get("paths") or [self.src.get("path", "")]
            self.src["scope"] = ", ".join(os.path.basename(os.path.abspath(os.path.expanduser(p))) for p in paths)
        if overrides.scope:
            self.src["scope"] = overrides.scope
        win = c.get("window", {})
        now = dt.datetime.now(dt.timezone.utc)
        days = overrides.days or win.get("days", 90)
        since = overrides.since or win.get("since")
        self.since = (since + "T00:00:00Z") if since and "T" not in since else since or \
            (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        self.until = now.strftime("%Y-%m-%d")
        s = c.get("sample", {})
        self.per_person = overrides.per_person or s.get("per_person", 20)
        self.patch_bytes = s.get("patch_bytes", 4000)
        self.bundle_bytes = s.get("bundle_bytes", 60000)
        self.min_commits = s.get("min_commits", 1)
        self.weights = {**DEFAULT_WEIGHTS, **c.get("weights", {})}
        run = c.get("run", {})
        self.threads = run.get("threads", 8)
        name = overrides.name or c.get("name") or \
            re.sub(r"[^a-z0-9]+", "-", f'{self.src["provider"]}-{self.src["scope"]}'.lower()).strip("-")[:60]
        self.name = name
        # outside the skill and outside any repo: runs hold client diffs, emails and possibly leaked secrets
        out = overrides.out or run.get("out_dir") or os.environ.get("TEAMPERF_OUT") or \
            os.path.join(os.path.expanduser("~"), ".cache", "team-perform", "runs")
        out = os.path.abspath(os.path.expanduser(out))
        self.dir = os.path.join(out, name)
        os.makedirs(self.dir, exist_ok=True)
        self.people_cfg = c.get("people", {})

    def p(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def provider(self):
        return make_provider(self.src, self.threads)

    def load_commits(self):
        path = self.p("commits.jsonl")
        if not os.path.exists(path):
            sys.exit("no commits.jsonl yet - run `tp collect` first")
        with open(path) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        return list({(c["repo"], c["sha"]): c for c in rows}.values())

    def identities(self, commits):
        return Identities(self.people_cfg).build(commits)


# ---------- commands ----------

def cmd_collect(ctx):
    prov = ctx.provider()
    log(f"[collect] {prov.kind}:{ctx.src['scope']} since {ctx.since[:10]}")
    repos = prov.list_repos()
    if not repos:
        sys.exit("no repositories visible - check scope and token access")
    active = [r for r in repos if prov.keep(r, ctx.since)]
    log(f"  {len(repos)} repos visible, {len(active)} with activity in the window")

    def one(r):
        rows, nb = prov.commits(r, ctx.since)
        log(f"  {r['name']}: {len(rows)} commits" + (f" across {nb} branches" if nb is not None else ""))
        return r, rows, nb

    workers = 2 if prov.kind == "github" else max(1, ctx.threads)
    commits = []
    with ThreadPoolExecutor(workers) as pool:
        for r, rows, nb in pool.map(one, active):
            r["branches"] = nb
            r["commits"] = len(rows)
            commits += rows
    for r in repos:
        r["scanned"] = r in active
    json.dump({"provider": prov.kind, "scope": ctx.src["scope"], "since": ctx.since, "until": ctx.until,
               "repos": repos}, open(ctx.p("repos.json"), "w"), indent=1)
    with open(ctx.p("commits.jsonl"), "w") as f:
        for c in commits:
            f.write(json.dumps(c) + "\n")
    log(f"  saved {len(commits)} commits ({prov.api.calls} {'git' if prov.kind == 'local' else 'API'} calls)")


def _people_commits(ctx, commits):
    ids = ctx.identities(commits)
    by = collections.defaultdict(list)
    for c in commits:
        p = ids.person(c)
        if p:
            by[p["id"]].append(c)
    return ids, by


def cmd_sample(ctx):
    commits = ctx.load_commits()
    ids, by = _people_commits(ctx, commits)
    repos = {r["name"]: r["id"] for r in json.load(open(ctx.p("repos.json")))["repos"]}
    prov = ctx.provider()
    todo = []
    for pid, rows in by.items():
        nm = sorted([c for c in rows if c["parents"] <= 1], key=lambda c: c["date"] or "", reverse=True)
        if len(nm) < ctx.min_commits:
            continue
        nm = list({c["sha"]: c for c in nm}.values())  # same sha can surface from two refs/identities
        nm.sort(key=lambda c: c["date"] or "", reverse=True)
        todo += [(pid, c) for c in nm[:ctx.per_person]]
    log(f"[sample] {len(todo)} commits for {len({p for p, _ in todo})} people")

    def fetch(item):
        pid, c = item
        cache = ctx.p("cache", c["sha"] + ".json")
        if os.path.exists(cache):
            d = json.load(open(cache))
        else:
            d = prov.detail(repos[c["repo"]], c["sha"])
            if d is None:
                return pid, None
            for f in d["files"]:
                f["patch"] = f["patch"][:ctx.patch_bytes]
            json.dump(d, open(cache, "w"))
        return pid, {**c, **d}

    out = collections.defaultdict(list)
    with ThreadPoolExecutor(ctx.threads) as pool:
        for pid, row in pool.map(fetch, todo):
            if row:
                out[pid].append(row)
    for pid, rows in out.items():
        rows.sort(key=lambda r: r["date"] or "", reverse=True)
        json.dump(rows, open(ctx.p("sample", pid + ".json"), "w"), indent=1)
    log(f"  saved samples ({prov.api.calls} {'git' if prov.kind == 'local' else 'API'} calls, cached details reused)")


def cmd_score(ctx):
    commits = ctx.load_commits()
    ids, by = _people_commits(ctx, commits)
    people = []
    matrix = collections.defaultdict(collections.Counter)
    for pid, rows in by.items():
        info = next(p for p in ids.people.values() if p["id"] == pid)
        nm = [c for c in rows if c["parents"] <= 1]
        sp = ctx.p("sample", pid + ".json")
        sample = json.load(open(sp)) if os.path.exists(sp) else []
        analysed = [heuristics.analyse_commit(c, c) for c in sample]
        # too little work to judge: keep them in the matrix, leave the scores empty
        h = heuristics.score_person(nm, analysed, ctx.weights) if len(nm) >= ctx.min_commits \
            else heuristics.score_person([], [], ctx.weights)
        per_repo = collections.Counter(c["repo"] for c in rows)
        for r, n in per_repo.items():
            matrix[r][pid] = n
        dates = sorted(c["date"] for c in rows if c["date"])
        people.append({**info, "commits": len(rows), "nonmerge": len(nm), "merges": len(rows) - len(nm),
                       "repos": len(per_repo), "active_days": len({d[:10] for d in dates}),
                       "first": dates[0][:10] if dates else None, "last": dates[-1][:10] if dates else None,
                       "per_repo": dict(per_repo.most_common()), "heur": h,
                       "sample_commits": [{k: a[k] for k in ("sha", "repo", "date", "subject", "lines", "files", "has_tests")}
                                          for a in analysed]})
    people.sort(key=lambda p: (-(p["heur"]["overall"] or 0), -p["commits"]))
    json.dump(people, open(ctx.p("people.json"), "w"), indent=1)

    repo_names = sorted(matrix)
    with open(ctx.p("matrix.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["repo"] + [p["id"] for p in people] + ["total"])
        for r in repo_names:
            w.writerow([r] + [matrix[r].get(p["id"], 0) for p in people] + [sum(matrix[r].values())])
    with open(ctx.p("scores.csv"), "w", newline="") as f:
        w = csv.writer(f)
        dims = list(DEFAULT_WEIGHTS)
        w.writerow(["person", "name", "commits", "nonmerge", "repos", "active_days", "last"] + dims +
                   ["overall", "vague_msg_pct", "revert_pct", "test_ratio_pct", "high_findings"])
        for p in people:
            h = p["heur"]
            w.writerow([p["id"], p["name"], p["commits"], p["nonmerge"], p["repos"], p["active_days"], p["last"]] +
                       [h["scores"][d] for d in dims] + [h["overall"], h["metrics"]["vague_message_pct"],
                        h["metrics"]["revert_pct"], h["metrics"]["test_ratio_pct"],
                        sum(1 for x in h["findings"] if x["severity"] == "high")])
    log(f"[score] {len(people)} people, {len(repo_names)} repos with commits")
    for p in people:
        h = p["heur"]
        log(f"  {h['overall'] if h['overall'] is not None else '-':>4}  {p['name'][:28]:28} "
            f"{p['commits']:5} commits  {p['repos']:2} repos  last {p['last']}")


def cmd_bundle(ctx):
    people = json.load(open(ctx.p("people.json")))
    os.makedirs(ctx.p("reviews", ".keep").rsplit("/", 1)[0], exist_ok=True)
    n = 0
    for p in people:
        sp = ctx.p("sample", p["id"] + ".json")
        if not os.path.exists(sp):
            continue
        sample = json.load(open(sp))
        h = p["heur"]
        out = [f"# Review pack: {p['name']} ({p['id']})",
               f"logins: {', '.join(p['logins']) or '-'} | commits in window: {p['commits']} ({p['merges']} merges) | "
               f"repos: {p['repos']} | active days: {p['active_days']} | last: {p['last']}",
               f"rule-based scores: {json.dumps(h['scores'])} overall {h['overall']}",
               f"metrics: {json.dumps(h['metrics'])}",
               "rule findings (rule / file / sha - values deliberately not shown): " +
               ("; ".join(f"{x['rule']} {x['file']} {x['sha']}" for x in h["findings"]) or "none"), ""]
        budget = ctx.bundle_bytes - sum(len(x) for x in out)
        per_commit = max(600, budget // max(1, len(sample)))
        for c in sample:
            head = (f"## {c['sha'][:10]} {c['repo']} {c['date'][:10] if c['date'] else ''} "
                    f"+{c['additions']}/-{c['deletions']} {len(c['files'])} files\n"
                    f"msg: {heuristics.redact(c['message'].strip()[:400])}\n"
                    f"files: {', '.join(f['path'] + f' (+{f['additions']}/-{f['deletions']})' for f in c['files'][:25])}"
                    + (" ..." if len(c["files"]) > 25 else ""))
            body, left = [], per_commit - len(head)
            for f in c["files"]:
                if heuristics.NOISE_FILES.search(f["path"] or "") or not f["patch"] or left <= 200:
                    continue
                chunk = heuristics.redact(f["patch"][:left])
                body.append(f"--- {f['path']}\n{chunk}")
                left -= len(chunk)
            out.append(head + ("\n```diff\n" + "\n".join(body) + "\n```" if body else "") + "\n")
        open(ctx.p("bundle", p["id"] + ".md"), "w").write("\n".join(out))
        n += 1
    log(f"[bundle] {n} review packs in {ctx.p('bundle')}  (reviews go in {ctx.p('reviews')}/<person>.json)")


def cmd_report(ctx):
    path = report.build(ctx)
    log(f"[report] {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["collect", "sample", "score", "bundle", "report", "all"])
    ap.add_argument("-c", "--config", help="TOML config (optional with --local)")
    ap.add_argument("--local", action="append", metavar="PATH",
                    help="local git clone, or a directory of clones (repeatable); replaces the config's [source]")
    ap.add_argument("--name", help="run name, output goes to <out>/<name>/")
    ap.add_argument("--scope", help="override source.scope (org / group path)")
    ap.add_argument("--days", type=int)
    ap.add_argument("--since", help="YYYY-MM-DD, overrides --days")
    ap.add_argument("--per-person", type=int)
    ap.add_argument("--out", help="output root (default $TEAMPERF_OUT or ~/.cache/team-perform/runs)")
    a = ap.parse_args(argv)
    ctx = Ctx(a.config, a)
    steps = {"collect": [cmd_collect], "sample": [cmd_sample], "score": [cmd_score], "bundle": [cmd_bundle],
             "report": [cmd_report],
             "all": [cmd_collect, cmd_sample, cmd_score, cmd_bundle, cmd_report]}[a.command]
    log(f"[{a.command}] output: {ctx.dir}")
    for s in steps:
        s(ctx)


if __name__ == "__main__":
    main()
