"""One-command commit + push for the project's GitHub repository.

First run (repo path / remote are saved to push.config.json, which is gitignored):

    ./.Search/Scripts/python.exe scripts/git_push.py \
        --repo "D:\\AI_projects\\YuanBao_Search" \
        --remote "https://github.com/Mc-ler/Yuanbao_Search.git"

Every later push only asks for the commit title/body:

    ./.Search/Scripts/python.exe scripts/git_push.py

The script never stores tokens. Authentication is delegated to Git Credential
Manager or SSH. It refuses to commit local secrets (.env, cache, archive, ...).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATHS = (ROOT / "push.config.json", ROOT / ".push.json")
DEFAULT_CONFIG = CONFIG_PATHS[0]
EXAMPLE_CONFIG = ROOT / "push.config.example.json"

FORBIDDEN_STAGED = re.compile(
    r"(^|/)(\.env(\.(?!example$).*)?$|\.push\.json$|push\.config\.json$|\.Search/|cache/|archive/|state/|probe/|\.archify/)"
)


def config_path() -> Path:
    for path in CONFIG_PATHS:
        if path.exists():
            return path
    return DEFAULT_CONFIG


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed"
        raise GitError(message)
    return result


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> None:
    path = config_path()
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_remote(remote: str) -> str:
    try:
        parts = urlsplit(remote)
        if parts.scheme and parts.hostname:
            netloc = parts.hostname
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        pass
    return remote


def resolve_repo(args: argparse.Namespace, config: dict) -> Path:
    raw = args.repo or config.get("repo") or os.environ.get("GIT_REPO_PATH") or ""
    if not raw:
        raw = ask("Repository path")
    if not raw:
        raise GitError("repository path is required (use --repo)")
    repo = Path(raw).expanduser().resolve()
    if not repo.exists():
        raise GitError(f"repository path not found: {repo}")
    if not repo.is_dir():
        raise GitError(f"repository path is not a directory: {repo}")
    config["repo"] = str(repo)
    return repo


def ensure_repo(repo: Path, args: argparse.Namespace) -> None:
    if (repo / ".git").exists():
        return
    allow = args.init or ask(f"{repo} is not a git repo; initialize? [y/N]", "n").lower() in {"y", "yes"}
    if not allow:
        raise GitError("not a git repository; pass --init or initialize it first")
    result = git(repo, "init", "-b", "main", check=False)
    if result.returncode != 0:
        git(repo, "init")
        git(repo, "checkout", "-b", "main", check=False)


def ensure_identity(repo: Path, args: argparse.Namespace, config: dict) -> None:
    name = git(repo, "config", "user.name", check=False).stdout.strip()
    email = git(repo, "config", "user.email", check=False).stdout.strip()
    target_name = args.name or config.get("author_name") or name
    target_email = args.email or config.get("author_email") or email
    if not target_name:
        target_name = ask("Git author name")
    if not target_email:
        target_email = ask("Git author email")
    if not target_name or not target_email:
        raise GitError("git user.name and user.email are required")
    if target_name != name:
        git(repo, "config", "user.name", target_name)
    if target_email != email:
        git(repo, "config", "user.email", target_email)
    config["author_name"] = target_name
    config["author_email"] = target_email


def ensure_remote(repo: Path, args: argparse.Namespace, config: dict) -> str:
    existing = git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    remote = args.remote or config.get("remote") or existing or os.environ.get("GIT_REMOTE") or ""
    if not remote:
        remote = ask("GitHub remote URL (git@github.com:org/repo.git)")
    if not remote:
        raise GitError("remote URL is required (use --remote)")
    if existing and existing != remote:
        git(repo, "remote", "set-url", "origin", remote)
    elif not existing:
        git(repo, "remote", "add", "origin", remote)
    config["remote"] = remote
    return remote


def current_branch(repo: Path) -> str:
    result = git(repo, "symbolic-ref", "--short", "HEAD", check=False)
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch else "main"


def has_commits(repo: Path) -> bool:
    return git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


def align_branch(repo: Path, target: str) -> None:
    current = current_branch(repo)
    if current == target:
        return
    if not has_commits(repo):
        git(repo, "branch", "-M", target)
        print(f"branch: {current} -> {target} (empty repo)")
        return
    exists = git(repo, "rev-parse", "--verify", target, check=False).returncode == 0
    if not exists:
        raise GitError(f"branch {target} does not exist; pass --branch {current} or create it first")
    git(repo, "checkout", target)
    print(f"branch: {current} -> {target}")


def ensure_env_ignored(repo: Path) -> None:
    env_file = repo / ".env"
    if not env_file.exists():
        return
    result = git(repo, "check-ignore", "-q", ".env", check=False)
    if result.returncode != 0:
        raise GitError(".env exists but is not gitignored; add .env to .gitignore before pushing")


def staged_files(repo: Path) -> list[str]:
    result = git(repo, "diff", "--cached", "--name-only", "-z")
    return [item for item in result.stdout.split("\0") if item]


def stage(repo: Path) -> tuple[bool, list[str]]:
    git(repo, "add", "-A")
    files = staged_files(repo)
    forbidden = [path for path in files if FORBIDDEN_STAGED.search(path)]
    if forbidden:
        raise GitError(
            "refusing to commit local-only files:\n  " + "\n  ".join(forbidden[:10])
        )
    changed = git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
    return changed, files


def push(repo: Path, remote: str, branch: str, assume_yes: bool) -> bool:
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    display = safe_remote(remote)
    if not assume_yes:
        answer = ask(f"Push {branch} to {display}? [Y/n]", "y").lower()
        if answer not in {"y", "yes"}:
            print("push cancelled")
            return False
    if upstream.returncode == 0:
        git(repo, "push")
    else:
        git(repo, "push", "-u", "origin", branch)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push the project repository")
    parser.add_argument("--repo", help="local repository path (saved in push.config.json)")
    parser.add_argument("--remote", help="GitHub remote URL (saved in push.config.json)")
    parser.add_argument("--branch", help="branch to push (default: config branch or current)")
    parser.add_argument("--message", "-m", help="commit title; prompted if omitted")
    parser.add_argument("--body", help="optional commit body")
    parser.add_argument("--name", help="git author name")
    parser.add_argument("--email", help="git author email")
    parser.add_argument("--init", action="store_true", help="initialize the repo if needed")
    parser.add_argument("--yes", "-y", action="store_true", help="skip push confirmation")
    parser.add_argument("--dry-run", action="store_true", help="show status only; do not commit/push")
    args = parser.parse_args()

    try:
        config = load_config()
        repo = resolve_repo(args, config)
        ensure_repo(repo, args)
        ensure_identity(repo, args, config)
        remote = ensure_remote(repo, args, config)
        ensure_env_ignored(repo)

        branch = args.branch or config.get("branch") or current_branch(repo)
        print(f"repo:   {repo}")
        print(f"remote: {safe_remote(remote)}")
        print(f"branch: {branch}")

        if args.dry_run:
            print("\n-- dry run: staged files would be --")
            print(git(repo, "status", "--short", check=False).stdout.rstrip() or "(clean)")
            save_config(config)
            return 0

        align_branch(repo, branch)
        config["branch"] = branch
        changed, files = stage(repo)
        if files:
            print(f"\nstaged {len(files)} file(s):")
            for path in files[:20]:
                print(f"  {path}")
            if len(files) > 20:
                print(f"  ... {len(files) - 20} more")
        else:
            print("\nno local changes")

        if changed:
            title = (args.message or "").strip()
            if not title:
                title = ask("Commit title")
            if not title:
                raise GitError("commit title is required")
            body = (args.body or "").strip()
            if body:
                git(repo, "commit", "-m", title, "-m", body)
            else:
                git(repo, "commit", "-m", title)
            print("committed:", git(repo, "log", "-1", "--oneline").stdout.strip())
        else:
            ahead = git(repo, "rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
            if ahead in {"", "0"}:
                print("nothing to commit or push")
                save_config(config)
                return 0

        if not push(repo, remote, branch, args.yes):
            save_config(config)
            return 0
        save_config(config)
        print("done:", git(repo, "log", "-1", "--oneline").stdout.strip())
        return 0
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
