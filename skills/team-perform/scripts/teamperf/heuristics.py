"""Rule-based commit quality scoring. No LLM, no network.

Five dimensions, 0-10 each:
  messages  - vague / tiny subjects vs. descriptive ones with a ticket, body, conventional prefix
  size      - lines and files per commit (lockfiles/generated excluded), revert churn
  tests     - share of code-changing commits that also touch test files
  hygiene   - debug leftovers, commented-out code, lint suppressions, TODOs in added lines
  security  - secrets, key files and risky settings in added lines (reported by rule + file, never the value)
"""
import re
import statistics

VAGUE = re.compile(
    r"^(up|upd|update[sd]?|updates? code|fix(e[sd])?|fix(ed)? ?(bug|error|issue|code|fix)?s?|bug ?fix(es)?|hot ?fix|wip|"
    r"test(ing|s)?|changes?|change code|minor|minor (fix|change)s?|small (fix|change)s?|asd+f*|ok|done|temp|tmp|"
    r"commit|refactor(ing)?|clean ?up|cleanup|new|init|save|stuff|more|again|final|last|\.+|-+|\d+)$", re.I)
# GitLab / GitHub web-editor defaults: "Edit white.list", "Update README.md", "Add new file", "Deleted x.yml"
WEB_IDE_DEFAULT = re.compile(r"^(edit|update|add|delete|deleted|upload|create|rename|replace)d? ([\w./@-]+|new (file|directory)|files? via upload)$", re.I)
TICKET = re.compile(r"([A-Z][A-Z0-9]+-\d+|#\d+|![0-9]+)")
CONVENTIONAL = re.compile(r"^(feat|fix|chore|docs|refactor|perf|test|build|ci|style|revert)(\([^)]*\))?!?:\s", re.I)
REVERT = re.compile(r"^revert\b|this reverts commit", re.I | re.M)

NOISE_FILES = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Gemfile\.lock|Podfile\.lock|composer\.lock|poetry\.lock|"
    r"Cargo\.lock|go\.sum|.*\.min\.(js|css)|.*\.map|.*\.pbxproj|.*\.snap)$|(^|/)(dist|build|vendor|node_modules)/", re.I)
ARTIFACTS = re.compile(r"(^|/)(node_modules|dist|\.next|coverage)/|(^|/)\.DS_Store$|\.log$|(^|/)\.idea/|(^|/)\.vscode/settings", re.I)
CODE_EXT = re.compile(r"\.(rb|py|js|jsx|ts|tsx|go|java|kt|kts|cs|php|swift|dart|vue|svelte|scala|rs|ex|exs|c|cc|cpp|h|m|mm)$", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|specs?|__tests__|__mocks__|e2e|cypress|androidTest)/|[._-](test|spec)\.[a-z]+$|_test\.go$|"
                       r"Tests?\.(java|kt|cs|swift)$|(^|/)test_[^/]+\.py$|_spec\.rb$", re.I)

DEBUG = re.compile(r"\bconsole\.(log|debug|trace)\(|^\s*debugger;?\s*$|binding\.pry|\bbyebug\b|\bpry\b\s*$|var_dump\(|"
                   r"\bdd\(|System\.out\.println|fmt\.Print(ln|f)?\(|\bpdb\.set_trace\(|breakpoint\(\)|print_r\(")
COMMENT_BODY = re.compile(r"^\s*(//|#|--)\s?(?!\s*(TODO|FIXME|NOTE|eslint|rubocop|noqa|type:|frozen_string|encoding|!|region|endregion|pragma|-\*-))(.+)$")
CODE_LIKE = re.compile(r"[;{}]\s*$|^\s*(return|const|let|var|if|elsif|else|for|while|def|end|class|import|from|await|async|puts|print|require|console\.|self\.|this\.|@\w+\s*=|<\w+[ />])|"
                       r"^\s*[\w$.\[\]'\"]+\(.*\)\s*[;,]?\s*$|^\s*[\w$.\[\]]+\s*(=|\+=|-=|\|\|=)\s*\S")


def is_commented_code(line):
    m = COMMENT_BODY.match(line)
    return bool(m and CODE_LIKE.search(m.group(3)))


SUPPRESS = re.compile(r"eslint-disable|@ts-ignore|@ts-nocheck|# ?noqa|rubocop:disable|@SuppressWarnings|#pragma warning disable|nolint")
TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")

SECRET_RULES = [
    ("aws-access-key", "high", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", "high", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", "high", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}")),
    ("gitlab-token", "high", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("google-api-key", "high", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("stripe-live-key", "high", re.compile(r"\b(sk|rk)_live_[A-Za-z0-9]{20,}")),
    ("jwt", "medium", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("keystore-password", "high", re.compile(r"(?i)\b(storePassword|keyPassword|[A-Z_]*KEYSTORE_PASSWORD|[A-Z_]*KEY_PASSWORD)\s*[=:]\s*['\"]?[^\s'\"$]{4,}")),
    ("hardcoded-credential", "high", re.compile(
        r"(?i)[A-Za-z0-9_]*(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|auth[_-]?token|access[_-]?token|"
        r"client[_-]?secret|private[_-]?key|map[_-]?kit[_-]?key)[A-Za-z0-9_]*"
        r"[\"']?\s*(=>|[:=])\s*[\"'](?![^\"']*(\$\{|\{\{|<|changeme|example|placeholder|xxx|\*\*\*|your[_-]|process\.env|ENV\[))[A-Za-z0-9_\-+/=.]{16,}[\"']")),
    ("db-url-with-password", "high", re.compile(r"\b(postgres|postgresql|mysql|mongodb(\+srv)?|redis|amqp)://[^:\s/]+:[^@\s$]{3,}@")),
]
RISKY_RULES = [
    ("tls-verify-off", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|"
                                  r"VERIFY_NONE|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|--insecure\b|-k\s+https")),
    ("tunnel-url", re.compile(r"ngrok(-free)?\.(io|app)|\.loca\.lt\b|trycloudflare\.com")),
    ("webview-any-origin", re.compile(r"originWhitelist=\{\[\s*['\"]\*['\"]\s*\]\}")),
    ("dangerous-html", re.compile(r"dangerouslySetInnerHTML|\.html_safe\b|\braw\(|v-html=")),
    ("sql-interpolation", re.compile(r"(?i)(where|order by|select|update|delete)[^\n]*(#\{|\$\{|%s|\" ?\+ ?\w)")),
    ("wide-cors", re.compile(r"Access-Control-Allow-Origin['\"]?\s*[:,=]\s*['\"]\*|origins?\s*[:=]\s*['\"]\*['\"]")),
]
SECRET_FILES = re.compile(r"(^|/)(\.env(\.[a-z]+)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx|.*\.jks|.*\.keystore|credentials(\.json)?|"
                          r".*service[-_]account.*\.json|kubeconfig|.*\.kubeconfig)$", re.I)
# identifiers that mention "password"/"token" but hold a name, not a secret (PASSWORD_RESET_TOPIC, tokenField, ...)
NOT_A_SECRET_NAME = re.compile(r"(topic|event|queue|route|path|url|uri|field|label|message|msg|name|type|key_name|header|"
                               r"param|column|policy|length|min|max|regex|pattern|placeholder|hint|error|i18n|route)s?\b", re.I)
CRED_IDENT = re.compile(r"([A-Za-z0-9_]+)[\"']?\s*(=>|[:=])\s*[\"']")
UI_FILE = re.compile(r"\.(tsx|jsx|vue|svelte|html?|css|scss)$", re.I)
DOC_OR_DEV = re.compile(r"(^|/)(README[^/]*|docker-compose[^/]*\.ya?ml|\.env\.(example|sample)|[^/]*\.md)$|(^|/)(docs?|examples?)/", re.I)
SECRET_FILE_OK = re.compile(r"\.(example|sample|template|dist)$|example|sample", re.I)


def redact(text):
    """Mask secret-rule matches so LLM review packs never carry the value. Rule name is kept."""
    for rule, _, rx in SECRET_RULES:
        text = rx.sub(f"[REDACTED:{rule}]", text)
    return text


def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, x))


SQUASH_LINE = re.compile(r"^\s*([*-]|co-authored-by:|signed-off-by:|reviewed-by:|see merge request|merge branch)", re.I)


def message_score(msg):
    """1 = vague ("fix", "up"); 3 = terse (<= 3 words); 5+ = descriptive, with bonuses."""
    msg = (msg or "").strip()
    subj, _, body = msg.partition("\n")
    s = subj.strip().strip(".!").strip()
    s = re.sub(r"^(merge branch|merged? )", "", s, flags=re.I)
    if VAGUE.match(s) or WEB_IDE_DEFAULT.match(s) or len(s) < 8:
        return 1.0, True
    words = len(re.findall(r"[^\s_/-]+", s))
    # a squash body that just lists the squashed commits ("* up", "* fix") is not an explanation
    real_body = "\n".join(l for l in body.splitlines() if l.strip() and not SQUASH_LINE.match(l))
    score = 3.0 if words <= 3 else 5.0
    score += 1 if len(s) >= 30 else 0
    score += 1 if CONVENTIONAL.match(s) else 0
    score += 1 if TICKET.search(msg) else 0
    score += 2 if len(real_body) >= 40 else 0
    score -= 1 if len(s) > 100 else 0
    return clamp(score), False


def added_lines(patch):
    for line in (patch or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            yield line[1:]


def size_score(lines, files):
    s = 10 if lines <= 200 else 8 if lines <= 500 else 6 if lines <= 1000 else 4 if lines <= 3000 else 2
    return clamp(s - (2 if files > 30 else 1 if files > 15 else 0))


def analyse_commit(c, d):
    """Per-commit metrics from a detail record."""
    files = d["files"]
    real = [f for f in files if not NOISE_FILES.search(f["path"] or "")]
    lines = sum(f["additions"] + f["deletions"] for f in real)
    code = [f for f in real if CODE_EXT.search(f["path"] or "") and not TEST_PATH.search(f["path"] or "")]
    tests = [f for f in files if TEST_PATH.search(f["path"] or "")]
    added = 0
    hy = {"debug": 0, "commented_code": 0, "suppress": 0, "todo": 0}
    findings = []
    for f in files:
        path = f["path"] or ""
        if f["status"] != "removed" and SECRET_FILES.search(path) and not SECRET_FILE_OK.search(path):
            findings.append({"rule": "secret-file", "severity": "high", "file": path})
        if f["status"] != "removed" and ARTIFACTS.search(path):
            findings.append({"rule": "build-artifact", "severity": "low", "file": path})
        seen = set()
        is_test = bool(TEST_PATH.search(path)) or "mock" in path.lower() or "fixture" in path.lower()
        for ln in added_lines(f["patch"]):
            added += 1
            if CODE_EXT.search(path):
                if DEBUG.search(ln):
                    hy["debug"] += 1
                if is_commented_code(ln):
                    hy["commented_code"] += 1
            if SUPPRESS.search(ln):
                hy["suppress"] += 1
            if TODO.search(ln):
                hy["todo"] += 1
            for rule, sev, rx in SECRET_RULES:
                if rule not in seen and rx.search(ln):
                    if rule == "hardcoded-credential":
                        m = CRED_IDENT.search(ln)
                        if m and NOT_A_SECRET_NAME.search(m.group(1).replace("_", " ")):
                            continue
                    seen.add(rule)
                    # test fixtures and local-dev docs usually hold throwaway values - still listed, lower severity
                    if is_test:
                        sev = "low"
                    elif DOC_OR_DEV.search(path) and sev == "high":
                        sev = "medium"
                    findings.append({"rule": rule, "severity": sev, "file": path})
            for rule, rx in RISKY_RULES:
                if rule in seen or not rx.search(ln):
                    continue
                if rule in ("sql-interpolation", "dangerous-html") and (UI_FILE.search(path) and rule == "sql-interpolation"
                                                                         or not CODE_EXT.search(path) or is_test):
                    continue
                seen.add(rule)
                findings.append({"rule": rule, "severity": "low" if is_test else "medium", "file": path})
    for x in findings:
        x.update(sha=c["sha"][:10], repo=c["repo"])
    findings = list({(x["sha"], x["rule"], x["file"]): x for x in findings}.values())
    return {"sha": c["sha"][:10], "repo": c["repo"], "date": c["date"], "subject": c["subject"][:120],
            "lines": lines, "files": len(real), "code_change": bool(code), "has_tests": bool(tests),
            "added": added, "hygiene": hy, "findings": findings,
            "truncated": any(not f["patch"] and (f["additions"] + f["deletions"]) > 0 for f in files)}


def score_person(window_commits, analysed, weights):
    """window_commits: all non-merge commits in the window; analysed: analyse_commit() of the sample."""
    msgs = [message_score(c["message"]) for c in window_commits]
    m_score = statistics.mean(s for s, _ in msgs) if msgs else None
    vague = sum(1 for _, v in msgs if v) / len(msgs) if msgs else 0
    reverts = sum(1 for c in window_commits if REVERT.search(c["message"] or ""))
    revert_ratio = reverts / max(1, len(window_commits))

    if analysed:
        size = statistics.mean(size_score(a["lines"], a["files"]) for a in analysed)
        size = clamp(size - min(3, revert_ratio * 30))
        code = [a for a in analysed if a["code_change"]]
        test_ratio = (sum(1 for a in code if a["has_tests"]) / len(code)) if code else None
        tests = clamp(test_ratio * 10 / 0.6) if test_ratio is not None else None
        added = max(1, sum(a["added"] for a in analysed))
        hy = {k: sum(a["hygiene"][k] for a in analysed) for k in ("debug", "commented_code", "suppress", "todo")}
        per_k = 1000 / added
        # ~17 weighted hits per 1000 added lines reaches 0
        hygiene = clamp(10 - 0.6 * per_k * (hy["debug"] * 1.0 + hy["commented_code"] * 0.5 + hy["suppress"] * 0.5 + hy["todo"] * 0.25))
        findings = list({(f["sha"], f["rule"], f["file"]): f for a in analysed for f in a["findings"]}.values())
        high = len({(f["sha"], f["rule"]) for f in findings if f["severity"] == "high"})
        med = len({(f["sha"], f["rule"]) for f in findings if f["severity"] == "medium"})
        low = len({(f["sha"], f["rule"]) for f in findings if f["severity"] == "low"})
        security = clamp(10 - 4 * high - 1 * med - 0.5 * low)
        median_lines = statistics.median(a["lines"] for a in analysed)
    else:
        size = tests = hygiene = security = None
        test_ratio = median_lines = None
        hy, findings = {}, []

    dims = {"messages": m_score, "size": size, "tests": tests, "hygiene": hygiene, "security": security}
    present = {k: v for k, v in dims.items() if v is not None}
    wsum = sum(weights[k] for k in present)
    overall = sum(present[k] * weights[k] for k in present) / wsum if wsum else None
    r1 = lambda v: None if v is None else round(v, 1)
    return {
        "scores": {k: r1(v) for k, v in dims.items()},
        "overall": r1(overall),
        "metrics": {"vague_message_pct": round(vague * 100), "reverts": reverts, "revert_pct": round(revert_ratio * 100, 1),
                    "median_lines": median_lines, "test_ratio_pct": None if test_ratio is None else round(test_ratio * 100),
                    "hygiene_hits": hy, "sampled": len(analysed)},
        "findings": findings,
    }
