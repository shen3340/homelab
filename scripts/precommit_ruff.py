import subprocess
import sys


def run(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def main() -> int:
    files = sys.argv[1:]

    if not files:
        return 0

    check_status = run(["ruff", "check", "--fix", *files])
    format_status = run(["ruff", "format", *files])

    # Ruff may modify files. Stage its fixes so pre-commit sees a clean
    # worktree and allows the commit to continue.
    stage_status = run(["git", "add", "--", *files])

    return check_status or format_status or stage_status


if __name__ == "__main__":
    raise SystemExit(main())
