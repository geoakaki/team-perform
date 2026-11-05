#!/usr/bin/env bash
# Install the team-perform skill for Claude Code (macOS and Linux).
#
#   ./install.sh                  install for you (~/.claude/skills)
#   ./install.sh --project DIR    install for one project (DIR/.claude/skills)
#   ./install.sh --uninstall      remove it (add --project DIR if installed there)
#   ./install.sh --copy           copy the files instead of linking to this folder
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/team-perform"
target="$HOME/.claude/skills" mode=link action=install

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)   [[ -d "${2:-}" ]] || { echo "--project needs an existing folder" >&2; exit 2; }
                 target="$(cd "$2" && pwd)/.claude/skills"; shift ;;
    --uninstall) action=uninstall ;;
    --copy)      mode=copy ;;
    -h|--help)   sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
dest="$target/team-perform"

if [[ -t 1 ]]; then g=$'\033[32m' r=$'\033[31m' n=$'\033[0m'; else g="" r="" n=""; fi
ok()   { printf '  %s✓%s %s\n' "$g" "$n" "$1"; }
fail() { printf '  %s✗%s %s\n    %s\n' "$r" "$n" "$1" "$2" >&2; exit 1; }

if [[ $action == uninstall ]]; then
  if [[ -e "$dest" || -L "$dest" ]]; then rm -rf "$dest"; echo "Removed $dest"; else echo "Not installed in $target"; fi
  exit 0
fi

echo "Checking requirements"
case "$(uname -s)" in
  Darwin) os=macOS; hint_py="brew install python@3.12"; hint_git="xcode-select --install" ;;
  Linux)  os=Linux; hint_py="sudo apt install python3.11   (or python3 on Ubuntu 24.04+ / Debian 12+), sudo dnf install python3"
          hint_git="sudo apt install git   or   sudo dnf install git" ;;
  *)      fail "Unsupported system: $(uname -s)" "team-perform supports macOS and Linux (on Windows, use WSL)." ;;
esac
ok "$os"
command -v git >/dev/null || fail "git not found" "Install it: $hint_git"
ok "git $(git --version | awk '{print $3}')"
py=""
for c in python3 python3.14 python3.13 python3.12 python3.11; do
  command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && { py=$c; break; }
done
if [[ -z $py ]]; then
  have=$(python3 -c 'import platform; print(platform.python_version())' 2>/dev/null || echo "none")
  fail "Python 3.11 or newer not found (python3: $have)" "Install it: $hint_py"
fi
ok "python $("$py" -c 'import platform; print(platform.python_version())')"
if command -v claude >/dev/null; then ok "Claude Code"; else
  printf '  - Claude Code not found: the command line still works; install it to use the skill (https://claude.com/claude-code)\n'; fi

if [[ -L "$dest" && "$(readlink "$dest")" == "$SRC" ]]; then
  echo "Already installed: $dest"
elif [[ -e "$dest" || -L "$dest" ]]; then
  fail "$dest already exists" "Remove it first: ./install.sh --uninstall"
else
  mkdir -p "$target"
  if [[ $mode == link ]]; then ln -s "$SRC" "$dest"; else cp -R "$SRC" "$dest"; fi
  find "$dest/" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  echo "Installed: $dest"
fi

cat <<EOF

Next:
  1. Start a new Claude Code session.
  2. Ask: "Analyse the team on ~/code/my-repo"

Or run it yourself:
  $dest/scripts/tp all --local ~/code/my-repo --open
EOF
