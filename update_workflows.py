#!/usr/bin/env python3
import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error, request

ALFRED_WORKFLOWS_DIR = Path.home() / "Library/Application Support/Alfred/Alfred.alfredpreferences/workflows"
UA = "alfred-workflow-auto-updater/1.0"
LAUNCH_AGENT_LABEL = "com.naodeng.alfred.workflow-updater.autocheck"
LAUNCH_AGENT_PATH = Path.home() / f"Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check and update installed Alfred workflows")
    parser.add_argument("--dry-run", action="store_true", help="Check only, do not install updates")
    parser.add_argument("--max", type=int, default=0, help="Only process the first N candidates (0 means all)")
    parser.add_argument("--self-test", action="store_true", help="Run internal tests and exit")
    parser.add_argument("--quiet-notify", action="store_true", help="Do not show notifications")
    parser.add_argument("--enable-auto", action="store_true", help="Enable scheduled daily check")
    parser.add_argument("--disable-auto", action="store_true", help="Disable scheduled daily check")
    parser.add_argument("--auto-status", action="store_true", help="Show scheduled check status")
    parser.add_argument("--hour", type=int, default=9, help="Hour for scheduled check (0-23)")
    parser.add_argument("--minute", type=int, default=0, help="Minute for scheduled check (0-59)")
    return parser.parse_args()


def normalize_repo(value: str) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    # owner/repo
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        return text

    # GitHub URL patterns
    m = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
    if not m:
        return None
    repo = m.group(1).rstrip("/")
    repo = re.sub(r"\.git$", "", repo)
    return repo if "/" in repo else None


def parse_version(version: str) -> Tuple[int, ...]:
    if not version:
        return tuple()
    cleaned = version.strip()
    cleaned = re.sub(r"^[^0-9]+", "", cleaned)
    parts = [p for p in re.split(r"[^0-9]+", cleaned) if p]
    if not parts:
        return tuple()
    return tuple(int(p) for p in parts)


def is_newer(local_version: str, remote_version: str) -> bool:
    lv = parse_version(local_version)
    rv = parse_version(remote_version)
    if not lv or not rv:
        return False

    width = max(len(lv), len(rv))
    lv = lv + (0,) * (width - len(lv))
    rv = rv + (0,) * (width - len(rv))
    return rv > lv


def read_workflow_meta(info_path: Path) -> Optional[Dict[str, str]]:
    try:
        with info_path.open("rb") as f:
            data = plistlib.load(f)
    except Exception:
        return None

    name = data.get("name") or info_path.parent.name
    version = str(data.get("version") or "")
    bundleid = str(data.get("bundleid") or "")
    web = str(data.get("webaddress") or "")

    variables = data.get("variables") or {}
    repo_candidates = [
        str(variables.get("github_repo") or ""),
        str(variables.get("github_slug") or ""),
        str(variables.get("repo") or ""),
        web,
    ]

    repo = None
    for c in repo_candidates:
        repo = normalize_repo(c)
        if repo:
            break

    if not repo:
        return None

    return {
        "name": name,
        "version": version,
        "bundleid": bundleid,
        "repo": repo,
        "workflow_dir": str(info_path.parent),
    }


def github_latest_release(repo: str) -> Optional[Dict[str, object]]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
        },
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except error.HTTPError as e:
        if e.code in (403, 404, 410):
            return None
        raise
    except Exception:
        return None

    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") or []
    wf_asset = None
    for a in assets:
        name = str(a.get("name") or "")
        if name.lower().endswith(".alfredworkflow"):
            wf_asset = a
            break

    return {
        "tag": tag,
        "asset": wf_asset,
        "html_url": data.get("html_url") or "",
    }


def notify(title: str, message: str, quiet: bool = False) -> None:
    if quiet:
        return
    safe_title = title.replace("\\", "\\\\").replace("\"", "\\\"")
    safe_message = message.replace("\\", "\\\\").replace("\"", "\\\"")
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install_asset(download_url: str) -> bool:
    try:
        with tempfile.NamedTemporaryFile(suffix=".alfredworkflow", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        req = request.Request(download_url, headers={"User-Agent": UA})
        with request.urlopen(req, timeout=40) as resp, tmp_path.open("wb") as out:
            out.write(resp.read())

        # Opening the workflow file triggers Alfred import/update.
        subprocess.run(["open", str(tmp_path)], check=True)
        time.sleep(0.3)
        return True
    except Exception:
        return False


def find_candidates(limit: int = 0) -> List[Dict[str, str]]:
    if not ALFRED_WORKFLOWS_DIR.exists():
        return []

    out: List[Dict[str, str]] = []
    for info_path in sorted(ALFRED_WORKFLOWS_DIR.glob("*/info.plist")):
        item = read_workflow_meta(info_path)
        if not item:
            continue
        if item.get("bundleid") == "com.naodeng.alfred.workflow-updater":
            continue
        out.append(item)
        if limit and len(out) >= limit:
            break
    return out


def run_self_test() -> int:
    assert normalize_repo("owner/repo") == "owner/repo"
    assert normalize_repo("https://github.com/owner/repo") == "owner/repo"
    assert normalize_repo("git@github.com:owner/repo.git") == "owner/repo"
    assert normalize_repo("https://example.com") is None

    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("v2.10.0") == (2, 10, 0)
    assert is_newer("1.2.3", "1.2.4") is True
    assert is_newer("1.2.3", "1.2.3") is False
    assert is_newer("1.2", "1.2.0") is False
    assert is_newer("2024.10", "2025.1") is True

    print("self-test passed")
    return 0


def write_launch_agent(hour: int, minute: int) -> None:
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    script_path = str(Path(__file__).resolve())
    py = sys.executable or "/usr/bin/python3"
    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [py, script_path, "--quiet-notify"],
        "RunAtLoad": False,
        "StartCalendarInterval": {"Hour": int(hour), "Minute": int(minute)},
        "StandardOutPath": str(Path.home() / "Library/Logs/alfred-workflow-updater.log"),
        "StandardErrorPath": str(Path.home() / "Library/Logs/alfred-workflow-updater.err.log"),
    }
    with LAUNCH_AGENT_PATH.open("wb") as f:
        plistlib.dump(plist, f)


def launchctl_bootout() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(LAUNCH_AGENT_PATH)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def launchctl_bootstrap() -> bool:
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(LAUNCH_AGENT_PATH)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def enable_auto(hour: int, minute: int, quiet: bool = False) -> int:
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        msg = "定时失败：时间格式无效"
        print(msg)
        notify("Workflow Updater", msg, quiet=quiet)
        return 1

    write_launch_agent(hour, minute)
    launchctl_bootout()
    ok = launchctl_bootstrap()
    if not ok:
        msg = "已写入定时任务，但系统加载失败，可手动重试"
        print(msg)
        notify("Workflow Updater", msg, quiet=quiet)
        return 1

    msg = f"已开启自动检查：每天 {hour:02d}:{minute:02d}"
    print(msg)
    notify("Workflow Updater", msg, quiet=quiet)
    return 0


def disable_auto(quiet: bool = False) -> int:
    launchctl_bootout()
    if LAUNCH_AGENT_PATH.exists():
        LAUNCH_AGENT_PATH.unlink(missing_ok=True)
    msg = "已关闭自动检查"
    print(msg)
    notify("Workflow Updater", msg, quiet=quiet)
    return 0


def auto_status(quiet: bool = False) -> int:
    if not LAUNCH_AGENT_PATH.exists():
        msg = "当前未开启自动检查"
        print(msg)
        notify("Workflow Updater", msg, quiet=quiet)
        return 0
    try:
        with LAUNCH_AGENT_PATH.open("rb") as f:
            data = plistlib.load(f)
        time_cfg = data.get("StartCalendarInterval", {})
        hour = int(time_cfg.get("Hour", 9))
        minute = int(time_cfg.get("Minute", 0))
        msg = f"自动检查已开启：每天 {hour:02d}:{minute:02d}"
    except Exception:
        msg = "自动检查已开启"
    print(msg)
    notify("Workflow Updater", msg, quiet=quiet)
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if args.enable_auto:
        return enable_auto(args.hour, args.minute, quiet=args.quiet_notify)
    if args.disable_auto:
        return disable_auto(quiet=args.quiet_notify)
    if args.auto_status:
        return auto_status(quiet=args.quiet_notify)

    candidates = find_candidates(args.max)
    if not candidates:
        msg = "没找到可自动更新的 workflows（需要能识别到 GitHub 仓库地址）"
        print(msg)
        notify("Workflow Updater", msg, quiet=args.quiet_notify)
        return 0

    checked = 0
    updatable = 0
    updated = 0
    skipped_no_asset = 0

    for wf in candidates:
        checked += 1
        release = github_latest_release(wf["repo"])
        if not release:
            continue

        tag = str(release.get("tag") or "")
        asset = release.get("asset")
        if not is_newer(wf["version"], tag):
            continue

        updatable += 1
        if not asset:
            skipped_no_asset += 1
            continue

        if args.dry_run:
            updated += 1
            continue

        url = str(asset.get("browser_download_url") or "")
        if url and install_asset(url):
            updated += 1

    if args.dry_run:
        msg = f"检查完成：共检查 {checked} 个，发现可更新 {updatable} 个（演练模式未执行安装）"
    else:
        msg = (
            f"检查完成：共检查 {checked} 个，发现可更新 {updatable} 个，成功触发更新 {updated} 个"
        )
        if skipped_no_asset:
            msg += f"，另有 {skipped_no_asset} 个没有可安装文件"

    print(msg)
    notify("Workflow Updater", msg, quiet=args.quiet_notify)
    return 0


if __name__ == "__main__":
    sys.exit(main())
