---
name: team-perform
description: Team activity and commit-quality analysis of git history: who works on which repo, rule-based 0-10 scores (commit messages, size, tests, hygiene, security patterns) and an optional token-lean LLM review per person, rendered as one self-contained HTML report. Works on LOCAL CLONES (a repo, several repos, or a directory of clones, no token), a GitHub org or a GitLab group (gitlab.com or self-hosted). TRIGGER when the user asks to analyse/check/score/review a team, contributors, developers or commit quality of a repo, a cloned repo, a folder of repos, an org or a group; asks who works on what, who owns which repo, who is most active; wants a team scorecard, contributor report or developer performance review; or asks for hiring/promotion input based on code history.
---

# team-perform

Scripts do all the data work (collect, identity merge, author x repo matrix, rule scores,
security pattern checks, HTML report). Model tokens go only to the optional review of compact
per-person bundles, never to raw history.

`TP=~/.claude/skills/team-perform/scripts/tp` (if absent, use `scripts/tp` next to this
SKILL.md). Python 3.11+, stdlib only. Full CLI: `$TP --help`.

## 0. Pick the source and state it

| user points at | command |
|---|---|
| one local clone (or any dir inside it) | `$TP all --local <path>` |
| several clones | `$TP all --local <a> --local <b>` |
| a folder of clones (`~/projects/<estate>/apps`) | `$TP all --local <dir>` (scans for `.git`, 3 levels, skips `node_modules`/`vendor`) |
| GitHub org / GitLab group | `$TP all -c <config.toml>` from `configs/example-{github,gitlab}.toml` |

Say out loud: source path(s) or org/group, window (default 90 days; `--days N` /
`--since YYYY-MM-DD`), and the output dir the run prints on its first line
(default `~/.cache/team-perform/runs/<name>/`, override `--out`, `--name`, `$TEAMPERF_OUT`).

Local mode reads local branches, remote-tracking branches and tags, so it is only as current as
the last fetch. Offer `git -C <repo> fetch --all --prune` first (ask; don't run it unasked on a
repo with uncommitted work in progress elsewhere). A shallow clone is reported as a warning:
offer `git fetch --unshallow`.

API sources need a token: env var named in `source.token_env` or a 1Password reference in
`source.token_op_ref`. Run the whole `tp all` in **one Bash call** so `op` asks for Touch ID once.
Never print the token.

## 1. Run the pipeline

```bash
$TP all --local <path> [--days N] [--per-person N]
```

Read only what it prints (the `[score]` table). Do not open `commits.jsonl`, `sample/` or
`cache/`. Steps 3-5 are free to re-run: `$TP score ... && $TP bundle ... && $TP report ...`
(same source flags each time).

## 2. Check identities before judging anyone

Local history has no provider logins, only author name + email, so one human can show up twice
(work and personal email, a renamed author). Same-name and GitHub no-reply emails merge
automatically. If two rows look like one person, propose aliases, then write a small config
**next to the runs, not in the repo** (it holds emails):

```toml
# ~/.cache/team-perform/configs/<name>.toml
[people.aliases]
"Jane Doe" = ["jane@example.com", "jd@personal.example"]
```

and re-score without re-collecting:
`$TP score -c <cfg> --local <path> && $TP bundle -c <cfg> --local <path> && $TP report -c <cfg> --local <path>`.
Bots are dropped by `[people] exclude_authors`.

## 3. LLM review (optional; ask first when there are more than 10 people)

For each `<out>/<name>/bundle/<person>.md`, launch one subagent in parallel. Give it the bundle
path, `references/review-rubric.md` (next to this file) as its instructions, and the output path
`<out>/<name>/reviews/<person>.json`. Each reads only its bundle, writes the JSON, replies in one
line. Skip people below `min_commits` (they have no bundle). Bundle diffs arrive with secret
matches already masked as `[REDACTED:<rule>]`.

If the user asked for a recommendation (hiring, promotion, ownership), write
`reviews/_summary.json` per the rubric. Then re-render: `$TP report <same flags>`.

## 4. Reply

- Ranked table: person, review score (if any), rule score, commits, repos, last commit.
- Ownership in one or two lines from `matrix.csv` (who carries which repo, bus-factor-1 repos).
- High-severity findings as **rule + file + sha only**.
- The report path. Offer to publish `report.html` as a private artifact only if the user wants
  it shared; it carries names, commit subjects and repo names.

Never paste diff contents, author emails or secret values into the reply.

## Caveats to state when it matters

- Rule scores measure commit discipline, not design or correctness. Use the LLM review for
  anything consequential, and say so when the user asks for hiring/promotion input.
- Security checks scan only **added lines in sampled commits**. A secret committed before the
  window or sitting untouched in the tree is not found; point to gitleaks/trufflehog for that.
- Infra repos (pipelines, helm, terraform, ansible): `tests` means validation (lint, `plan`,
  dry runs); the rubric says so.
- Run output holds client diffs and emails. It is outside the repo by default; delete
  `<out>/<name>/` when the review is done.

## Reference

- Rule-score dimensions and weights: `references/scoring.md`.
- Every config key, commented: `configs/example-{local,github,gitlab}.toml`.
- Reviewer rubric and JSON shapes: `references/review-rubric.md`.
