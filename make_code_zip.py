"""Build ZYRO-code-agent.zip -- the shareable CODE-mode update.

    venv\\Scripts\\python make_code_zip.py

The zip holds only the files this update adds or changes, so it can be
unzipped straight over an existing D:\\zyro install.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIP_NAME = "ZYRO-code-agent.zip"

FILES = [
    # the agent itself
    "agent/__init__.py",
    "agent/config.py",
    "agent/diff.py",
    "agent/workspace.py",
    "agent/checkpoint.py",
    "agent/llm.py",
    "agent/loop.py",
    "agent/session.py",
    "agent/cli.py",
    "agent/README.md",
    # the tool registry
    "agent/tools/__init__.py",
    "agent/tools/base.py",
    "agent/tools/coding.py",
    "agent/tools/files.py",
    "agent/tools/search.py",
    "agent/tools/system.py",
    "agent/tools/productive.py",
    "agent/tools/web.py",
    "agent/tools/media.py",
    "agent/tools/vision.py",
    "agent/tools/memory.py",
    "agent/tools/meta.py",
    # window + tests + docs
    "gui.py",
    "gui_agent.py",
    "theme.py",
    "main.py",
    "test_agent.py",
    "test_gui.py",
    "test_ollama_lifecycle.py",
    "INSTALL-code-mode.txt",
    # changed core files
    "core/browser.py",
    "core/downloads.py",
    "core/ollama_lifecycle.py",
]


def main():
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        print("missing files, nothing was built:")
        for name in missing:
            print("  " + name)
        return 1
    target = ROOT / ZIP_NAME
    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = ROOT / name
            archive.write(path, name)
            total += path.stat().st_size
    size = target.stat().st_size
    print(f"built {target}")
    print(f"  {len(FILES)} files, {total / 1024:.0f} KB of source, "
          f"{size / 1024:.0f} KB zipped")
    print("\ncontents:")
    for name in FILES:
        print("  " + name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
