# LLM review rubric

Used by the `team-perform` skill (step 3 of `SKILL.md`). One reviewer reads one
`<out>/<name>/bundle/<person>.md` and writes `<out>/<name>/reviews/<person>.json`.

## Scores (0-10 each)

| key | weight | what it judges |
|---|---|---|
| `quality`  | 35% | readability, duplication, obvious bugs, error handling, N+1/perf traps, dead or commented-out code, debug leftovers |
| `hygiene`  | 20% | one logical change per commit; no giant mixed dumps, build artefacts, lockfile churn, WIP / revert churn |
| `messages` | 15% | descriptive, says why, references a ticket; "fix", "up", "wip", "." score low |
| `security` | 15% | hardcoded secrets/URLs, injection, disabled auth/validation/TLS, personal data in logs |
| `tests`    | 15% | behaviour changes come with tests |

`overall` = weighted sum, one decimal.

## Rules for the reviewer
- Evidence only: cite `sha` + file for every strength and issue.
- The bundle's patches are truncated; don't penalise what you can't see.
- The bundle's "rule findings" are pattern hits. Confirm or dismiss each one.
- **Never quote a secret value.** Name the rule, file and sha only. Diffs show matches as
  `[REDACTED:<rule>]`; treat those as confirmed hits of that rule.
- Squash/merge duplicates of the same change count once.
- Infrastructure repos (pipelines, helm/k8s, terraform, ansible, monitoring): score `tests` as
  validation: CI lint, `helm lint`/`template`, `terraform validate`/`plan`, dry runs, policy or
  schema checks, smoke tests.

## Output: `reviews/<person>.json`

```json
{
  "person": "<person id from the bundle title>",
  "area": "Mobile apps + backend",
  "scores": {"quality": 6, "hygiene": 5, "messages": 4, "security": 7, "tests": 1},
  "overall": 4.9,
  "verdict": "One sentence.",
  "strengths": ["... (sha, file)", "..."],
  "issues": ["most serious first ... (sha, file)", "..."]
}
```

`area` is a few words on what the person works on, taken from their repos and files. It fills the
"Works on" column. Commit shas in the text are highlighted, `**bold**` and `` `code` `` render.

## Page files (written by the orchestrator, not the per-person reviewers)

Both are optional. Write them in plain language for the reader of the page, usually a manager.

`reviews/_summary.json` is the recommendation box at the top. Every key except `title` is optional:

```json
{
  "eyebrow": "Hiring recommendation",
  "title": "Who to hire",
  "headline": "If you're taking one person, **Jane** writes the best code. For a small team, shortlist **Jane, Ana and Lee**.",
  "points": ["optional bullets under the headline"],
  "picks": [
    {"name": "Jane", "tag": "Best quality · 6.9", "points": ["Best messages and commit size"], "caveat": "Last commit 12 Aug: check she's still on the project."}
  ],
  "table": {"title": "Hire only if the role needs them", "columns": ["Role", "Person", "Why only then"],
            "rows": [["Storefront frontend", "George", "Only one who knows the storefronts, but lowest score."]]},
  "columns": [{"title": "Lowest priority", "points": ["..."]}, {"title": "Before you decide", "points": ["..."]}],
  "ask": "Who comes first depends on the role."
}
```

`reviews/_report.json` sets the page's own text:

```json
{
  "title": "Acme Developer Scorecard",
  "eyebrow": "github.com/acme-org · code review",
  "lede": "Who committed where over the last 90 days, and a 0-10 score per developer.",
  "repo_groups": {"Storefront": "^shop-", "Mobile": "-app$", "Backend": "api|worker"},
  "security": [
    {"severity": "high", "title": "shop-app: release keystore password committed",
     "detail": "In plain text in `android/gradle.properties`. Rotate it and move it to CI secrets."}
  ],
  "method_notes": ["Two logins were merged into one person: jdoe and jdoe-acme."]
}
```

- `security` replaces the raw rule-findings list with curated issues: what it is, where, what to
  do. **Name the file and the kind of secret, never its value.** Only list what a reviewer
  confirmed.
- `repo_groups` maps a label to a regex on repo names; the first match wins and the rest go
  under "other". Without it, repos are grouped by name prefix.
