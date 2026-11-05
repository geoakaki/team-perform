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
  "scores": {"quality": 6, "hygiene": 5, "messages": 4, "security": 7, "tests": 1},
  "overall": 4.9,
  "verdict": "One sentence.",
  "strengths": ["... (sha, file)", "..."],
  "issues": ["most serious first ... (sha, file)", "..."]
}
```

Optional `reviews/_summary.json` renders as a box at the top of the report:

```json
{"eyebrow": "Hiring recommendation", "title": "Who to hire", "headline": "One paragraph.", "points": ["...", "..."]}
```
