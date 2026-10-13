"""ZYRO's hotkey helper -- thin launcher for the source install.

Runs invisibly under pythonw.exe. The real logic is core/hotkey.py,
shared with the portable "ZYRO.exe --hotkey" mode.
"""

from core.hotkey import main

if __name__ == "__main__":
    main()
