#!/usr/bin/env python3
"""
EvoMemory sync manager.

Commands:
  - upgrade: git pull (if git repo) + pip install -e .
  - uninstall: ask for EvoScientist.py path, remove injected code, then pip uninstall -y evomemory_sync

No third-party dependencies; uses Python standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Tuple


def _color_red(s: str) -> str:
    # ANSI escape codes work in most terminals (including modern PowerShell). If not, raw text still readable.
    return f"\033[91m{s}\033[0m"


def _repo_root() -> Path:
    # scripts/manage.py -> scripts/ -> repo root
    return Path(__file__).resolve().parent.parent


def _is_git_repo(path: Path) -> bool:
    try:
        p = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return p.returncode == 0 and p.stdout.strip().lower() == "true"
    except FileNotFoundError:
        return False


def _read_text_with_fallback_encodings(file_path: Path) -> Tuple[str, str]:
    encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252"]
    for enc in encodings:
        try:
            return file_path.read_text(encoding=enc, errors="strict"), enc
        except UnicodeDecodeError:
            continue
    # Last resort: replace undecodable chars.
    return file_path.read_text(encoding="utf-8", errors="replace"), "utf-8"


def _write_text(file_path: Path, text: str, encoding: str) -> None:
    file_path.write_text(text, encoding=encoding, errors="strict")


def cmd_upgrade(_: argparse.Namespace) -> None:
    root = _repo_root()

    if _is_git_repo(root):
        print("Detected git repo. Running `git pull` ...")
        subprocess.run(["git", "-C", str(root), "pull"], check=False)
    else:
        print("Not a git repo. Skipping `git pull` ...")

    print("Running `pip install -e .` ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=str(root), check=True)
    print("[OK] Upgrade successful. `evomemory_sync` is up to date.")


def _remove_injected_code(file_path: Path) -> Tuple[bool, bool, bool]:
    """
    Returns: (file_found, found_import, found_mw_item)
    """
    if not file_path.exists():
        return (False, False, False)

    original_text, encoding = _read_text_with_fallback_encodings(file_path)
    updated_text = original_text

    # 1) from evomemory_sync.middleware import EvoMemorySyncMiddleware
    import_pat = re.compile(
        r"^[ \t]*from[ \t]+evomemory_sync\.middleware[ \t]+import[ \t]+EvoMemorySyncMiddleware[ \t]*$",
        flags=re.MULTILINE,
    )
    found_import = bool(import_pat.search(original_text))
    updated_text, n_import = import_pat.subn("", updated_text)
    found_import = found_import or n_import > 0

    # 2) EvoMemorySyncMiddleware(), in mw list (handle whitespace/newlines)
    # Prefer line-based removal to keep formatting clean.
    item_line_pat = re.compile(
        r"^[ \t]*EvoMemorySyncMiddleware\s*\(\s*\)\s*,[ \t]*(?:#.*)?\r?\n",
        flags=re.MULTILINE,
    )
    found_item_line = bool(item_line_pat.search(updated_text))
    updated_text, n_item_line = item_line_pat.subn("", updated_text)
    found_item = found_item_line or n_item_line > 0

    # Fallback: remove the expression across possible newlines between tokens.
    if not found_item:
        item_any_pat = re.compile(r"\bEvoMemorySyncMiddleware\s*\(\s*\)\s*,", flags=re.DOTALL)
        updated_text, n_item_any = item_any_pat.subn("", updated_text)
        found_item = n_item_any > 0

    if updated_text != original_text:
        _write_text(file_path, updated_text, encoding=encoding)

    return (True, found_import, found_item)


def cmd_uninstall(_: argparse.Namespace) -> None:
    print("请输入本地 `EvoScientist.py`（或 Agent 启动文件）的绝对或相对路径：")
    raw_path = input("> ").strip()
    if not raw_path:
        print(
            _color_red(
                "错误：未提供文件路径。将仅卸载 Python 包；注入代码请手动删除，以避免运行时触发 ModuleNotFoundError。"
            )
        )
        file_path = None
    else:
        p = Path(os.path.expanduser(raw_path))
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        file_path = p

    found_file = False
    found_import = False
    found_mw_item = False

    if file_path is not None:
        found_file, found_import, found_mw_item = _remove_injected_code(file_path)
        if not found_file:
            print(_color_red(f"警告：找不到文件：{file_path}。请手动在源码中删除对应注入代码："))
            print(_color_red(" - `from evomemory_sync.middleware import EvoMemorySyncMiddleware`"))
            print(_color_red(" - `EvoMemorySyncMiddleware(),`（在 `mw` 列表中）"))
            print(_color_red("为避免运行时触发 ModuleNotFoundError，请手动删除后再运行 EvoScientist。"))
        else:
            if not (found_import and found_mw_item):
                missing = []
                if not found_import:
                    missing.append("import 行")
                if not found_mw_item:
                    missing.append("mw 列表项")
                print(_color_red(f"警告：在该文件中未能自动匹配/删除：{', '.join(missing)}。"))
                print(_color_red("请手动在源码中删除，避免运行时触发 ModuleNotFoundError。"))

    print("正在卸载 Python 包 `evomemory_sync` ...")
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "evomemory_sync"], check=False)

    print("代码挂载和 Python 包已清除。您现在可以安全地直接删除整个 evomemory-skill 文件夹，如果您想清除凭证，请一并删除 .env 文件。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage evomemory_sync plugin: upgrade or uninstall.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub_upgrade = sub.add_parser("upgrade", help="Upgrade: git pull (if git repo) + pip install -e .")
    sub_upgrade.set_defaults(func=cmd_upgrade)

    sub_uninstall = sub.add_parser("uninstall", help="Uninstall: remove injected code from EvoScientist.py and uninstall evomemory_sync")
    sub_uninstall.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

