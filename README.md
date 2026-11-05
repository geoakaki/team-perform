# team-perform

See how a development team works, straight from its git history.

Point it at a repository and you get one web page that shows:

- **Who works on what.** Commits per person per repository, and which repos depend on a single
  person.
- **How each person works.** A score from 0 to 10 for commit messages, change size, tests, code
  hygiene and security.
- **What needs attention.** Leaked passwords or keys, disabled security checks, debug code left in.
- **An optional written review per person**, with strengths and issues, done by Claude.

It runs on your own computer. Your code stays there, and a repository you have cloned needs no
login or token.

## Install

Works on **macOS** and **Linux**. You need `git`, Python 3.11 or newer, and
[Claude Code](https://claude.com/claude-code).

```bash
git clone https://github.com/geoakaki/team-perform.git
cd team-perform
./install.sh
```

The installer checks your system and tells you what is missing and how to get it:

| | macOS | Linux |
|---|---|---|
| git | `xcode-select --install` | `sudo apt install git` / `sudo dnf install git` |
| Python 3.11+ | `brew install python@3.12` | Ubuntu 24.04+, Debian 12+, Fedora: already there. Ubuntu 22.04: `sudo apt install python3.11` |

To update, run `git pull` in the `team-perform` folder. To remove it, run `./install.sh --uninstall`.

## Use it

Start a new Claude Code session and ask in plain words:

| ask | you get |
|---|---|
| *Analyse the team on ~/code/shop-api* | the report for the last 90 days |
| *Check commit quality in this repo for the last 30 days* | the same, for the repository you are in |
| *Who owns what across all repos in ~/code?* | every repository in the folder, with the people behind each |
| *Review each developer on ~/code/shop-api and summarise strengths and issues* | scores plus a written review per person |
| *Jane shows up twice, merge her two emails* | the report again, with one row for Jane |
| *Who should we hire from this team? Export it for my manager* | a recommendation box with picks, then a page to share |

Claude replies with a short ranked table, the main findings, and where the report is saved.

**Without Claude**, from a terminal:

```bash
~/.claude/skills/team-perform/scripts/tp all --local ~/code/shop-api --open
```

Add `--days 30` or `--since 2026-06-01` to change the period. Pass `--local` several times, or
give it a folder, to cover more than one repository. GitHub organisations and GitLab groups also
work. See [advanced use](docs/advanced.md).

## Share it

Ask *Export the report as a page I can share*, or *… with names hidden*. Claude builds one web
page (scores, recommendations, security issues, reviews; [sections](docs/advanced.md#export-and-share))
and, after you confirm, publishes it as a private page on claude.ai. You choose who to share it with. Without Claude:

```bash
~/.claude/skills/team-perform/scripts/tp export --local ~/code/shop-api --anonymize --open
```

`--anonymize` shows people as "Developer A", "Developer B"… in rank order.

## Reading the scores

| score | high means |
|---|---|
| Messages | commit descriptions explain what changed and why ("fix" and "wip" score low) |
| Size | small, focused changes that are easy to review |
| Tests | code changes come with tests |
| Hygiene | no debug output, commented-out code or skipped warnings |
| Security | no passwords, keys or disabled security checks in new code |

The overall score is a weighted average.

## Good to know

- **Scores are a starting point, not a verdict.** They measure working habits, not design
  quality or business impact. Use the written review, and talk to the team, before any decision
  about a person.
- **Only recent work is checked.** The period defaults to 90 days. Code checks read each person's
  last 20 commits. A secret committed earlier is not found.
- **Fetch first.** A local clone is only as current as its last `git fetch`.
- **Privacy.** Results are saved in `~/.cache/team-perform/` on your computer, never in the
  repository. Leaked secrets are named, never shown, and emails stay out of the report. Delete
  the results when you are done.
