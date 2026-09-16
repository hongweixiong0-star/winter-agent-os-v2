"""Scan the tracked tree for anything that must not reach a PUBLIC repository.

Why this exists (2026-09-16).  The repo became public
(https://github.com/hongweixiong0-star/winter-agent-os-v2), and pushing is now part of
the normal development loop, so "did I just publish a token" has to be answerable in
one command instead of by re-deriving an ad-hoc grep each time -- the ad-hoc version
already produced a false-positive report (sha256/dhash values matched as secrets).

What it checks
--------------
1. **Tracked file names** that should never be tracked at all:
   `.env*`, `secrets*`, `credentials*`, `token*`, `cookie*`, `session*`, `*.pem`,
   `*.key`, `id_rsa*`.
2. **Tracked file contents** for high-signal credential shapes: GitHub tokens, Slack
   tokens, Google API keys, AWS keys, private-key headers, JWTs, and
   `password/token/secret/api_key = "<long literal>"` assignments.
3. **Personal data**: mainland phone numbers and e-mail addresses, minus an allowlist
   of shapes the project legitimately contains (the commit identity
   `agent@winter-agent-os.local`, example/test domains, and hashes).
4. **`.gitignore` coverage** for the file patterns above, so an accidental
   `git add -A` cannot publish them in the first place.

Anything binary, or larger than ``--max-bytes``, is skipped rather than guessed at.

Read-only: it never stages, commits or rewrites anything.

Exit code is 1 when something must be looked at, 0 otherwise, so it can gate a push.

Usage
-----
    python tools/scan_public_repo.py
    python tools/scan_public_repo.py --json out_secret_scan.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 1. file names that must not be tracked
FORBIDDEN_NAMES = [
    ".env", ".env.*", "*.env", "secrets*", "credentials*", "token*", "cookie*",
    "session*", "*.pem", "*.key", "*.p12", "id_rsa*", "id_ed25519*",
]
FORBIDDEN_NAME_EXCEPTIONS = [
    # the project legitimately has modules and fixtures with these words in them
    "winter_agent_v2/*", "tools/*", "tests/*", "docs/*", "knowledge/*",
    "*.md", "*.json",
]

# 2. content shapes
SECRET_PATTERNS: list[tuple[str, str]] = [
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    ("github_pat", r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    ("assignment", r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|"
                   r"cookie|access[_-]?key|client[_-]?secret|refresh[_-]?token)\b"
                   r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"),
    ("bearer_header", r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._\-]{20,}"),
]

# 3. personal data
PII_PATTERNS: list[tuple[str, str]] = [
    ("cn_mobile", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("email", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
]
PII_ALLOWLIST = [
    r"@winter-agent-os\.local$",   # the commit identity
    r"@example\.(com|org|net)$",
    r"@localhost$",
    r"@users\.noreply\.github\.com$",
    r"@test\.local$",
    r"^[0-9a-f]{32,}@",            # md5/sha-prefixed fixture ids
]
# the repo is public and the operator's own GitHub handle is already public in the URL
PII_CONTEXT_ALLOWLIST = [
    "hongweixiong0-star",
]
# A phone-number regex matches inside hex digests.  Measured 2026-09-16: all ten hits in
# this tree were substrings of sha256/dhash values in `dataset/candidate/dataset_audit.json`
# (`"sha256": "9e0b3dc...2d14946334577"` matched `14946334577`), which is the same
# false-positive class the ad-hoc pre-push grep produced.  Suppress any match that sits
# inside a run of hex characters long enough to be a digest, and only there: a real
# number in text is a standalone run of digits.
HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ico", ".pdf", ".zip", ".gz",
    ".mp4", ".pyc", ".so", ".dll", ".exe", ".bin", ".woff", ".woff2", ".ttf", ".onnx",
}
# files whose *purpose* is to discuss these patterns
SCAN_TARGET_EXCEPTIONS = {
    "tools/scan_public_repo.py",
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def read_text(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def name_is_exempt(rel: str) -> bool:
    return any(fnmatch(rel, pattern) for pattern in FORBIDDEN_NAME_EXCEPTIONS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    files = tracked_files()
    findings: dict[str, list[dict]] = {
        "forbidden_name": [], "secret": [], "pii": [], "gitignore_gap": [],
    }

    secret_res = [(name, re.compile(pattern)) for name, pattern in SECRET_PATTERNS]
    pii_res = [(name, re.compile(pattern)) for name, pattern in PII_PATTERNS]
    pii_allow = [re.compile(pattern) for pattern in PII_ALLOWLIST]

    for rel in files:
        rel_posix = rel.replace("\\", "/")
        base = Path(rel_posix).name

        # 1. file names
        if any(fnmatch(base, pattern) or fnmatch(rel_posix, pattern)
               for pattern in FORBIDDEN_NAMES) and not name_is_exempt(rel_posix):
            findings["forbidden_name"].append({"file": rel_posix})

        if rel_posix in SCAN_TARGET_EXCEPTIONS:
            continue
        if Path(rel_posix).suffix.lower() in SKIP_SUFFIXES:
            continue

        text = read_text(ROOT / rel_posix, args.max_bytes)
        if text is None:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            if len(line) > 4000:
                continue
            for name, regex in secret_res:
                for match in regex.finditer(line):
                    findings["secret"].append({
                        "file": rel_posix, "line": line_no, "pattern": name,
                        "match": match.group(0)[:24] + ("..." if len(match.group(0)) > 24 else ""),
                    })
            for name, regex in pii_res:
                for match in regex.finditer(line):
                    value = match.group(0)
                    if any(allow.search(value) for allow in pii_allow):
                        continue
                    if any(token in value for token in PII_CONTEXT_ALLOWLIST):
                        continue
                    span = HEX_RUN.search(line)
                    in_hex = False
                    while span is not None:
                        if span.start() <= match.start() and match.end() <= span.end():
                            in_hex = True
                            break
                        span = HEX_RUN.search(line, span.end())
                    if in_hex:
                        continue
                    findings["pii"].append({
                        "file": rel_posix, "line": line_no, "pattern": name,
                        "match": value[:40],
                    })

    # 4. .gitignore coverage
    ignore_text = ""
    ignore_path = ROOT / ".gitignore"
    if ignore_path.is_file():
        ignore_text = ignore_path.read_text(encoding="utf-8", errors="replace")
    for pattern in (".env", "*.env", "secrets*", "credentials*", "token*", "cookie*",
                    "session*", "*.pem", "*.key", "id_rsa*"):
        if pattern not in ignore_text:
            findings["gitignore_gap"].append({"pattern": pattern})

    counts = {key: len(value) for key, value in findings.items()}
    print(f"tracked files: {len(files)}")
    print(f"counts: {json.dumps(counts)}")

    for key, label in (("forbidden_name", "MUST NOT BE TRACKED"),
                       ("secret", "CREDENTIAL SHAPES"),
                       ("pii", "PERSONAL DATA"),
                       ("gitignore_gap", ".GITIGNORE GAPS")):
        rows = findings[key]
        print(f"\n-- {label} ({len(rows)}) --")
        for row in rows[:40]:
            print("   " + json.dumps(row, ensure_ascii=False))
        if len(rows) > 40:
            print(f"   ... and {len(rows) - 40} more")

    blocking = counts["forbidden_name"] + counts["secret"]
    print("\nVERDICT: " + ("REVIEW REQUIRED before push" if blocking else
                           "no credentials found in tracked files"))
    if counts["pii"]:
        print(f"         {counts['pii']} personal-data hit(s) need a human look "
              f"(the repo is public)")
    if counts["gitignore_gap"]:
        print(f"         {counts['gitignore_gap']} .gitignore pattern(s) missing")

    if args.json:
        target = Path(args.json)
        if not target.is_absolute():
            target = ROOT / target
        target.write_text(json.dumps({
            "tracked_files": len(files), "counts": counts, "findings": findings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")

    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
