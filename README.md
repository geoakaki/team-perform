# team-perform

A Claude Code **skill** for team activity and commit-quality analysis of git history: who works
on which repo, rule-based scores per person, security pattern checks, an optional LLM review, and
one self-contained HTML report.

It reads **local clones** (no token, no network), a **GitHub organisation**, or a **GitLab group**
(gitlab.com or self-hosted). Scripts do all the data work. The model only reads compact
per-person review packs, and only if you ask for the qualitative review.

Based on [geoakaki/team-performance](https://github.com/geoakaki/team-performance), repackaged
as a skill, with a local-clone provider and secret masking in the review packs added.

Python 3.11+, standard library only. Nothing to `pip install`.

## Install

```bash
git clone https://github.com/geoakaki/team-perform.git
cd team-perform
./install.sh                       # symlink into ~/.claude/skills/team-perform (follows git pull)
./install.sh --copy                # or a plain copy
./install.sh --project ~/src/app   # or into one repo's .claude/skills, shared with its users
./install.sh --uninstall
```

Restart Claude Code (or start a new session) and the skill is picked up. It triggers on requests
like "analyse the team on this repo" or "who owns what in ~/src/acme". You can also run the
scripts directly: `~/.claude/skills/team-perform/scripts/tp --help`.

## Analyse a local cloned repo

### Ask Claude

Open Claude Code anywhere and ask in plain words. The skill picks the command, runs it, and
replies with a ranked table, ownership notes, high-severity findings and the report path.

| you type | what happens |
|---|---|
| `Analyse the team on ~/src/acme/api` | `tp all --local ~/src/acme/api`: last 90 days, all branches, rule scores, report |
| `Check commit quality in this repo for the last 30 days` | same, run from inside the clone, with `--days 30` |
| `Score everyone who committed to ~/src/acme/api and ~/src/acme/web since June` | two `--local` paths, `--since 2026-06-01` |
| `Who owns what across all repos in ~/projects/acme/apps?` | scans the folder for clones, then reads ownership from the author x repo matrix |
| `Review the team on ~/src/acme/api with an LLM review per developer` | rule run, then one sub-agent per person reads their review pack and scores quality, hygiene, messages, security and tests |
| `Fetch first, then analyse ~/src/acme/api for the last 6 months` | `git fetch --all --prune`, then `--days 180` |
| `Jane's work and personal emails show as two people, merge them and re-score` | writes `[people.aliases]` to a config next to the runs, then re-runs `score`/`bundle`/`report` with no re-collection |
| `Who should own the payments service? Give me a recommendation` | LLM review plus a summary box at the top of the report |

A fuller prompt, when you want to control every step:

```text
Use the team-perform skill on ~/src/acme/api and ~/src/acme/web.
Window: since 2026-06-01. Fetch all remotes first.
Show me the rule-score table, then point out anyone who looks split across two identities
and propose aliases before going further.
Ask me before the LLM review if there are more than 10 people.
Reply with the ranked table, who carries which repo (bus factor 1 repos), and high-severity
findings as rule + file + sha only. No diff contents, emails or secret values in the reply.
```

### Run it yourself

```bash
TP=~/.claude/skills/team-perform/scripts/tp

$TP all --local ~/src/acme/api                         # one clone, last 90 days
$TP all --local .                                      # the clone you are in (any subdir works)
$TP all --local ~/src/acme/api --days 30               # shorter window
$TP all --local ~/src/acme/api --since 2026-06-01      # from a date
$TP all --local ~/src/acme/api --local ~/src/acme/web  # several clones, one report
$TP all --local ~/projects/acme/apps                   # every clone under a folder (3 levels deep)
$TP all --local ~/src/acme/api --name acme-q3          # pick the run name (output folder)
$TP all --local ~/src/acme/api --per-person 40         # read more diffs per person

open ~/.cache/team-perform/runs/local-api/report.html
```

The first line of every run prints the output folder.

Local mode reads local branches, remote-tracking branches and tags. It is only as current as your
last fetch, so run `git fetch --all --prune` first. A shallow clone prints a warning; run
`git fetch --unshallow` for full history.

**Aliases, weights or a filter on a local run:** keep a small config outside the repo and
combine it with `--local`. The config supplies window, people and weights, and `--local`
replaces its source:

```toml
# ~/.cache/team-perform/configs/acme.toml
[window]
days = 120

[people]
exclude_authors = "(\\[bot\\]|renovate|jenkins)"

[people.aliases]
"Jane Doe" = ["jane@acme.com", "jd@personal.example"]

[weights]
tests = 0.30
```

```bash
$TP all   -c ~/.cache/team-perform/configs/acme.toml --local ~/src/acme/api
$TP score -c ~/.cache/team-perform/configs/acme.toml --local ~/src/acme/api \
  && $TP report -c ~/.cache/team-perform/configs/acme.toml --local ~/src/acme/api   # re-score, no re-collect
```

For a folder scan, `include` / `exclude` (regex on the repo's relative path) and `max_depth` go in
a `provider = "local"` source block. See `skills/team-perform/configs/example-local.toml`.

## GitHub org or GitLab group

```bash
cp skills/team-perform/configs/example-gitlab.toml ~/.cache/team-perform/configs/acme-gitlab.toml
$EDITOR ~/.cache/team-perform/configs/acme-gitlab.toml       # base_url, scope, token source
GITLAB_TOKEN=... $TP all -c ~/.cache/team-perform/configs/acme-gitlab.toml
```

Or ask Claude: `Analyse the GitHub org acme-org for the last 90 days, token from op://<vault>/<item>/token`.

Token scopes: GitLab `read_api`. GitHub: a fine-grained PAT with *Contents: read* + *Metadata:
read*, or classic `repo`. The token stays in memory, goes out only as a header, and is never
logged or written to disk. Rate limits (`429`, `Retry-After`) are honoured. On self-hosted GitLab
with a private CA, set `ca_file`.

## Pipeline

| step | command | cost | output in `<out>/<name>/` |
|---|---|---|---|
| 1 | `tp collect` | `git log` (local) or API calls (repos + commits on all branches) | `repos.json`, `commits.jsonl` |
| 2 | `tp sample`  | `git show` / 1-2 API calls per sampled commit, cached | `sample/<person>.json`, `cache/` |
| 3 | `tp score`   | none | `people.json`, `matrix.csv`, `scores.csv` |
| 4 | `tp bundle`  | none | `bundle/<person>.md` (LLM review packs, secrets masked) |
| 5 | `tp report`  | none | `report.html` (merges `reviews/*.json` if present) |
|   | `tp all`     | 1 to 5 | |

Steps 3-5 are free to re-run after you change aliases or weights.

## What the scores mean

Five rule-based dimensions, 0-10 each, no LLM. Messages are scored on every commit, the rest on
the last 20 commits per person:

- **messages**: descriptive subjects, a real body, ticket refs. "fix", "up", "wip" and
  web-editor defaults score 1.
- **size**: small, focused commits.
- **tests**: code changes that also touch tests.
- **hygiene**: no debug prints, commented-out code, lint suppressions or TODOs.
- **security**: no secrets, key files, TLS-off or SQL interpolation.

Details: [`references/scoring.md`](skills/team-perform/references/scoring.md). The optional LLM
review follows [`references/review-rubric.md`](skills/team-perform/references/review-rubric.md).

Rule scores are for triage. They measure commit discipline, not design or correctness. Use the
LLM review for anything that matters (hiring, promotion), and read it as one input, not a
verdict.

Security checks see only **added lines in sampled commits**. Run a full-tree scanner (gitleaks,
trufflehog) to find a secret committed earlier or sitting untouched in the tree.

## Data handling

- Output defaults to `~/.cache/team-perform/runs/<name>/`, outside the skill and any repo
  (override with `--out`, `run.out_dir` or `$TEAMPERF_OUT`). It holds commit metadata, author
  emails and diff excerpts. Delete it when the review is done.
- Finding values are never printed: not in the terminal, the CSVs, the report, nor the review
  packs, where matches are masked as `[REDACTED:<rule>]`. Author emails are stripped from the
  report's embedded data.
- Credentials embedded in a clone's remote URL are stripped before the URL is stored.

## Layout

```text
skills/team-perform/
  SKILL.md                      the skill: when it triggers and the workflow Claude follows
  scripts/tp                    launcher (python3 -m teamperf)
  scripts/teamperf/             collect / sample / score / bundle / report, providers: local, github, gitlab
  references/                   scoring.md, review-rubric.md (sub-agent instructions)
  configs/example-*.toml        every config key, commented
tests/smoke.sh                  offline end-to-end test against a throwaway repo
install.sh
```

Test: `bash tests/smoke.sh`. It builds a two-author repo, runs the whole pipeline, and checks
identity merging, scores, findings, paths with spaces, and that no secret value or email reaches
any report artifact.
