# Rule-based scores (0-10, no LLM)

| dimension | computed from | high score means |
|---|---|---|
| `messages` | every non-merge commit in the window | descriptive subjects, a real body, ticket refs; "fix", "up", "wip" and web-editor defaults ("Update README.md") score 1 |
| `size`     | sampled diffs, lockfiles/generated excluded | small, focused commits; penalised above 500 lines, above 15 files, and for revert churn |
| `tests`    | sampled diffs | code-changing commits that also touch test files (60 % = 10) |
| `hygiene`  | added lines in sampled diffs | no debug prints, commented-out code, lint suppressions, TODOs |
| `security` | added lines + file names in sampled diffs | no secrets, key files, TLS-off, tunnel URLs, `dangerouslySetInnerHTML`, SQL interpolation |

Default weights: hygiene 25 %, messages / size / security 20 % each, tests 15 %. Set them in
`[weights]`; they are normalised over the dimensions a person has. People below `min_commits`
stay in the matrix but get no score.

Security findings are rule + file + sha. The matched value is never printed: not in the
terminal, the CSVs, the report, nor the bundles (masked as `[REDACTED:<rule>]`). Findings in
test fixtures drop to low severity, findings in docs / docker-compose / `.env.example` to medium.

Sampling: the last `per_person` (default 20) non-merge commits per person get their diffs read;
each file patch is capped at `patch_bytes`. Message scores use every non-merge commit.

## Outputs (`<out>/<name>/`)

| file | what |
|---|---|
| `repos.json`, `commits.jsonl` | repos and every commit in the window (all branches, de-duplicated by sha) |
| `sample/<person>.json`, `cache/<sha>.json` | sampled commit details (diffs) |
| `people.json`, `matrix.csv`, `scores.csv` | identities, author x repo commit counts, scores |
| `bundle/<person>.md` | LLM review pack, capped at `bundle_bytes` (~15k tokens) |
| `reviews/<person>.json`, `reviews/_summary.json` | LLM reviews (optional) |
| `report.html` | self-contained report; author emails are stripped from its embedded data |
