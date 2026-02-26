# Remote Codex Adaptation (Preamble)

This prompt was written for a local CLI agent. If you are a remote Codex app agent:

- Read `/Users/michaelbraband/.codex/AGENTS.md` first
- Treat `~` as remote (`/home/michael`)
- Run heavy operations on glider via `ssh glider-tunnel`
- Edit files via the mounted mirror under `/Users/michaelbraband/glider/...`
- Use `mkvenv` for per-repo venvs (see global guide)
- If you need a venv, check activation and create if missing:
  - `if [ -z "$VIRTUAL_ENV" ]; then cd /home/michael/dev/work/<repo> && mkvenv; fi`
- If `mkvenv` is unavailable in a non-interactive shell, source it first:
  - `. /home/michael/dev/work/glider/linux-common/dotfiles/bash/bash_venv`
