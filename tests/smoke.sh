#!/usr/bin/env bash
# Offline smoke test for the local provider: builds a throwaway repo with two authors, runs the
# whole pipeline against it and checks the outputs. No network, no token.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TP="$ROOT/skills/team-perform/scripts/tp"
WORK="$(mktemp -d)"
trap '[[ -n "${KEEP:-}" ]] && echo "kept: $WORK" || rm -rf "$WORK"' EXIT

FAKE_KEY="AKIA""ABCDEFGHIJKLMNOP"   # matches the aws-access-key rule; split so this file itself doesn't
repo="$WORK/clones/demo-api"
mkdir -p "$repo" && cd "$repo"
git init -q -b main
c() { GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" \
      git -c commit.gpgsign=false commit -q -m "$3"; }

for i in 1 2 3 4; do
  printf 'export function add%s(a, b) {\n  return a + b + %s;\n}\n' "$i" "$i" > "src_$i.js"
  printf 'test("add%s", () => expect(1).toBe(1));\n' "$i" > "src_$i.test.js"
  git add . && c "Jane Doe" "jane@example.com" "feat(math): add add$i helper with unit test PROJ-$i"
done
for i in 1 2 3; do
  printf 'console.log("debug %s");\nconst x%s = 1;\n' "$i" "$i" > "util_$i.js"
  git add . && c "John Roe" "john@example.com" "fix"
done
printf 'const awsKey = "%s";\n' "$FAKE_KEY" > config.js
git add . && c "John Roe" "john@example.com" "add config"
git checkout -q -b feature/x
printf 'x\n' > "file with space.txt"
git add . && c "Jane Doe" "Jane.Doe@Example.com" "docs: add a file whose name holds spaces"
git checkout -q main

out="$WORK/runs"
"$TP" all --local "$WORK/clones" --out "$out" --name smoke 2>&1 | sed 's/^/  | /'
d="$out/smoke"

fail() { echo "FAIL: $*"; exit 1; }
for f in repos.json commits.jsonl people.json matrix.csv scores.csv report.html; do
  [[ -s "$d/$f" ]] || fail "missing $f"
done
python3 -I - "$d" <<'EOF' || exit 1
import json, sys
d = sys.argv[1]
commits = [json.loads(l) for l in open(f"{d}/commits.jsonl")]
assert len(commits) == 9, f"expected 9 commits across both branches, got {len(commits)}"
people = {p["name"]: p for p in json.load(open(f"{d}/people.json"))}
assert set(people) == {"Jane Doe", "John Roe"}, people.keys()
jane, john = people["Jane Doe"], people["John Roe"]
assert jane["commits"] == 5, "Jane's two emails should merge into one person"
assert jane["heur"]["overall"] > john["heur"]["overall"], "focused, tested commits should outscore 'fix' + console.log"
rules = {f["rule"] for f in john["heur"]["findings"]}
assert "aws-access-key" in rules, rules
assert john["heur"]["metrics"]["hygiene_hits"]["debug"] == 3
paths = {f["path"] for c in json.load(open(f"{d}/sample/jane-doe.json")) for f in c["files"]}
assert "file with space.txt" in paths, paths
print("  ok: commits, identity merge, scores, findings, paths with spaces")
EOF
grep -rqF "$FAKE_KEY" "$d"/{people.json,scores.csv,matrix.csv,report.html,bundle} \
  && fail "secret value leaked into a report artefact"
grep -qF "jane@example.com" "$d/report.html" && fail "author email embedded in report.html"

# export: reviewer files that name people in free text, then a plain and an anonymized export
mkdir -p "$d/reviews"
cat > "$d/reviews/jane-doe.json" <<'EOF'
{"person": "jane-doe", "area": "Math helpers", "scores": {"quality": 8, "hygiene": 8, "messages": 9, "security": 9, "tests": 8},
 "overall": 8.3, "verdict": "Jane writes small, tested changes.", "strengths": ["Tests with every helper (abc1234, src_1.js)"], "issues": ["None serious"]}
EOF
cat > "$d/reviews/john-roe.json" <<'EOF'
{"person": "john-roe", "area": "Utilities", "scores": {"quality": 4, "hygiene": 2, "messages": 1, "security": 2, "tests": 0},
 "overall": 2.4, "verdict": "John Roe leaves debug output and a key in config.js.", "strengths": ["Fast"], "issues": ["Unlike Jane, no tests"]}
EOF
cat > "$d/reviews/_summary.json" <<'EOF'
{"eyebrow": "Hiring recommendation", "title": "Who to hire", "headline": "Take **Jane Doe**; coach John.",
 "picks": [{"name": "Jane Doe", "tag": "Best quality · 8.3", "points": ["Tested helpers"], "caveat": "Check availability"}],
 "table": {"title": "Only if the role needs them", "columns": ["Role", "Person", "Why"], "rows": [["Utilities", "John", "Only one in util"]]},
 "columns": [{"title": "Before you decide", "points": ["Paid trial task"]}], "ask": "Depends on the role."}
EOF
cat > "$d/reviews/_report.json" <<'EOF'
{"title": "Demo Developer Scorecard", "eyebrow": "local · demo-api", "repo_groups": {"API": "^demo"},
 "security": [{"severity": "high", "title": "AWS key committed in config.js", "detail": "Rotate it; committed by @john-roe in `config.js`."}],
 "method_notes": ["Two people, one repo."]}
EOF
"$TP" export --local "$WORK/clones" --out "$out" --name smoke 2>&1 | sed 's/^/  | /'
"$TP" export --local "$WORK/clones" --out "$out" --name smoke --anonymize 2>&1 | tee "$WORK/anon.log" | sed 's/^/  | /'
e="$d/export.html"
[[ -s "$e" ]] || fail "missing export.html"
head -c 15 "$e" | grep -qi "<!DOCTYPE html" || fail "export.html must start with <!DOCTYPE html>"
grep -q "<title>Demo Developer Scorecard</title>" "$e" || fail "export title"
grep -qF "Developer A" "$e" || fail "no pseudonyms in anonymized export"
grep -qiE "jane|john|\bdoe\b|\broe\b" "$e" && fail "a real name survived --anonymize"
grep -q "warning" "$WORK/anon.log" && fail "anonymize reported leftovers"
grep -qF "$FAKE_KEY" "$e" && fail "secret value in export"
python3 -I - "$e" <<'EOF' || exit 1
import json, re, sys
html = open(sys.argv[1]).read()
data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
top = max(data["people"], key=lambda p: p["review"]["overall"])
assert top["name"] == "Developer A", "Developer A should be the top-ranked person"
assert data["summary"]["picks"][0]["name"] == "Developer A", data["summary"]["picks"][0]
assert "Developer B" in data["summary"]["table"]["rows"][0][1]
print("  ok: export, anonymized names in reviews, summary, security and table")
EOF
echo "PASS"
