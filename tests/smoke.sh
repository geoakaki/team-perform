#!/usr/bin/env bash
# Offline smoke test for the local provider: builds a throwaway repo with two authors, runs the
# whole pipeline against it and checks the outputs. No network, no token.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TP="$ROOT/skills/team-perform/scripts/tp"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

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
echo "PASS"
