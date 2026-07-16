# VPS Deployment via GitHub

Notes on installing and maintaining this skill on a remote VPS via GitHub.

## Initial Installation

```bash
# Clone the repo directly into the Hermes skills directory
git clone https://github.com/Stefan-codestar/multi-ai-skill.git ~/.hermes/skills/multi-ai-skill
```

SKILL.md must be in the repo root (not under `skill/`) for Hermes to discover it.

## Updating from GitHub

```bash
cd ~/.hermes/skills/multi-ai-skill
git pull origin main
```

## Pushing Local Changes to GitHub

If the VPS has no GitHub credentials configured, `git push` will fail with
`fatal: could not read Username for 'https://github.com'`. Options:

1. **Make repo public** — clone and pull work without auth; push still needs auth
2. **SSH deploy key** (recommended for VPS):
   - `ssh-keygen -t ed25519 -C "deploy@vps" -f ~/.ssh/id_deploy_multi_ai -N ""`
   - Add the `.pub` key at Repo -> Settings -> Deploy keys (check "Allow write access")
   - Add to `~/.ssh/config`:
     ```
     Host github.com-multi-ai
       HostName github.com
       User git
       IdentityFile ~/.ssh/id_deploy_multi_ai
       IdentitiesOnly yes
     ```
   - `git remote set-url origin git@github.com-multi-ai:Stefan-codestar/multi-ai-skill.git`
3. **Git credential helper** with PAT:
   - `git config --global credential.helper store`
   - Do a manual `git ls-remote` to trigger the prompt (username + token as password)

## Hermes Security Scanner and Tokens

The Hermes terminal security scanner **blocks commands containing plaintext GitHub
tokens** (patterns like `ghp_...`). Do NOT paste a token into a `terminal()` command.
Instead:
- Use SSH deploy keys (no token in any command)
- Or have the user set up credentials themselves via the credential helper prompt
- Or store the token in `~/.env` and read it from a script file, not inline

## Git Identity on Fresh VPS

Fresh VPS images lack git identity. Set before first commit:

```bash
git config --global user.email "user@example.com"
git config --global user.name "User Name"
```

Symptom: `fatal: unable to auto-detect email address`

## Directory Structure Convention

Hermes expects this layout for a skill with code:

```
multi-ai-skill/
├── SKILL.md                 ← MUST be in root, not in a subdirectory
├── .gitignore
├── multiai/                 ← Python package
│   ├── __init__.py
│   ├── __main__.py
│   └── *.py
├── references/              ← Supplementary docs
│   ├── build-notes.md
│   ├── moa-model-selection.md
│   └── streaming.md
├── templates/               ← Config templates
│   └── config_pro_3worker.py
└── tests/                   ← Test suite
    ├── conftest.py
    └── test_*.py
```

Key rules:
- SKILL.md in root (Hermes convention; `skill/SKILL.md` will NOT be discovered)
- `__pycache__/` and `.pytest_cache/` in `.gitignore`
- Windows paths in SKILL.md must be converted to Linux paths for VPS