#!/usr/bin/env bash
# Install the team-perform skill for Claude Code.
#   ./install.sh                  symlink into ~/.claude/skills (personal, follows git pull)
#   ./install.sh --copy           copy instead of symlink
#   ./install.sh --project DIR    install into DIR/.claude/skills (shared with that repo's users)
#   ./install.sh --uninstall [--project DIR]
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/team-perform"
dest_root="$HOME/.claude/skills" mode=link uninstall=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy) mode=copy ;;
    --project) [[ -d "${2:-}" ]] || { echo "--project needs an existing directory" >&2; exit 2; }
               dest_root="$(cd "$2" && pwd)/.claude/skills"; shift ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
dest="$dest_root/team-perform"

if [[ $uninstall == 1 ]]; then
  if [[ -L "$dest" || -d "$dest" ]]; then rm -rf "$dest"; echo "removed $dest"; else echo "not installed: $dest"; fi
  exit 0
fi
command -v python3 >/dev/null || { echo "python3 (3.11+) is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "python3 3.11+ is required" >&2; exit 1; }
mkdir -p "$dest_root"
if [[ -e "$dest" || -L "$dest" ]]; then
  if [[ -L "$dest" && "$(readlink "$dest")" == "$SRC" ]]; then echo "already linked: $dest -> $SRC"; exit 0; fi
  echo "$dest exists - run with --uninstall first" >&2; exit 1
fi
if [[ $mode == link ]]; then ln -s "$SRC" "$dest"; else cp -R "$SRC" "$dest"; find "$dest" -name __pycache__ -prune -exec rm -rf {} +; fi
echo "installed ($mode): $dest"
echo "try: $dest/scripts/tp all --local <path-to-a-clone>   or ask Claude: \"analyse the team on <path>\""
