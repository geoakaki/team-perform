# team-perform: advanced use

The [README](../README.md) covers install and everyday use. This page is the full reference.

`TP=~/.claude/skills/team-perform/scripts/tp` below. Run `$TP --help` for every flag.

## Command line

```bash
$TP all --local ~/code/api                         # one clone, last 90 days
$TP all --local .                                  # the clone you are in (any subfolder works)
$TP all --local ~/code/api --local ~/code/web      # several clones, one report
$TP all --local ~/code                             # every clone under a folder (3 levels deep)
$TP all --local ~/code/api --days 30               # shorter window
$TP all --local ~/code/api --since 2026-06-01      # from a date
$TP all --local ~/code/api --name q3-review        # name the run (its output folder)
$TP all --local ~/code/api --per-person 40         # read more commits per person (default 20)
$TP all --local ~/code/api --open                  # open the report when done
```

Local mode reads local branches, remote-tracking branches and tags, so it is only as current as
the last `git fetch --all --prune`. A shallow clone prints a warning; `git fetch --unshallow`
gives full history.

## Steps

`all` runs five steps. The last three cost nothing to re-run after you change aliases or weights.

| step | does | output in `<out>/<name>/` |
|---|---|---|
| `collect` | every commit in the window, all branches | `repos.json`, `commits.jsonl` |
| `sample`  | diffs of each person's last N commits (cached) | `sample/`, `cache/` |
| `score`   | merges identities, scores people, builds the person x repo matrix | `people.json`, `matrix.csv`, `scores.csv` |
| `bundle`  | one compact review pack per person for the LLM review, secrets masked | `bundle/<person>.md` |
| `report`  | one self-contained HTML page, with reviews merged in if present | `report.html` |

Output goes to `~/.cache/team-perform/runs/<name>/`. Change it with `--out`, `run.out_dir` or
`$TEAMPERF_OUT`.

## Config file

A config is optional for local repos. Use one for aliases, weights, a longer window or filters.
Keep it outside the repo, since it can hold emails. With `-c cfg --local PATH`, the config supplies
everything except the source.

```toml
# ~/.cache/team-perform/configs/acme.toml
[window]
days = 120                                   # or: since = "2026-06-01"

[people]
exclude_authors = "(\\[bot\\]|renovate|jenkins)"

[people.aliases]                             # one person, several identities
"Jane Doe" = ["jane@example.com", "jd@personal.example"]

[weights]                                    # normalised over the dimensions a person has
tests = 0.30
```

```bash
$TP all   -c ~/.cache/team-perform/configs/acme.toml --local ~/code/api
$TP score -c ~/.cache/team-perform/configs/acme.toml --local ~/code/api \
  && $TP report -c ~/.cache/team-perform/configs/acme.toml --local ~/code/api   # re-score only
```

Every key, commented: [`example-local.toml`](../skills/team-perform/configs/example-local.toml),
[`example-github.toml`](../skills/team-perform/configs/example-github.toml),
[`example-gitlab.toml`](../skills/team-perform/configs/example-gitlab.toml). For a folder scan,
`include` / `exclude` (regex on the repo's path under the folder) and `max_depth` go in a
`provider = "local"` source block.

## GitHub organisation or GitLab group

```bash
cp skills/team-perform/configs/example-gitlab.toml ~/.cache/team-perform/configs/acme-gitlab.toml
# edit base_url, scope (group path) and the token source
GITLAB_TOKEN=... $TP all -c ~/.cache/team-perform/configs/acme-gitlab.toml
```

- Token scopes: GitLab `read_api`. GitHub: a fine-grained token with *Contents: read* and
  *Metadata: read*, or a classic token with `repo`.
- Token sources: the env var named in `source.token_env`, or a password-manager reference in
  `source.token_op_ref` (read with `op read`). The token stays in memory and is never logged or
  written to disk.
- Self-hosted GitLab: set `base_url`, plus `ca_file` for a private CA. Rate limits are honoured
  automatically.
- GitHub has no "all branches" listing, so `collect` walks every branch and costs more API calls.

## Scores

Rule-based, 0-10, no LLM. Full definitions are in
[`references/scoring.md`](../skills/team-perform/references/scoring.md), and the LLM reviewer's
rubric is in [`references/review-rubric.md`](../skills/team-perform/references/review-rubric.md).

## Data handling

- Run output holds commit metadata, author emails and diff excerpts. Delete it when done.
- Finding values are never printed: not in the terminal, the CSVs, the report, nor the review
  packs, where matches show as `[REDACTED:<rule>]`. Author emails are stripped from the report.
- Credentials in a clone's remote URL are removed before the URL is stored.

## Platforms

macOS and Linux, with Python 3.11+ and git. Windows works through WSL. No packages to install:
everything uses the Python standard library.

| system | Python 3.11+ |
|---|---|
| macOS | `brew install python@3.12` (the Xcode tools' Python may be older) |
| Ubuntu 24.04+, Debian 12+, Fedora 38+ | the system `python3` |
| Ubuntu 22.04 | `sudo apt install python3.11` (found automatically next to the older `python3`) |

## Development

```bash
bash tests/smoke.sh      # offline end-to-end test against a throwaway two-author repo
```

```text
skills/team-perform/
  SKILL.md                 what triggers the skill and the steps Claude follows
  scripts/tp               launcher (python3 -m teamperf)
  scripts/teamperf/        the pipeline; providers: local, github, gitlab
  references/              scoring.md, review-rubric.md
  configs/                 example configs
tests/smoke.sh
install.sh
docs/advanced.md
```
