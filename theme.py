"""ZYRO's colours and fonts -- one place, so the window and CODE mode match.

The theme is GRUVBOX DARK (medium contrast), chosen because it is
warm and low-contrast rather than blue:

* the text is a warm off-white (#ebdbb2), never pure white, so it does
  not glare on a dark background;
* the background is warm charcoal, not navy -- blue light late at night
  is the worst offender for tired eyes;
* nothing is fully saturated: the accents are muted aqua, green, yellow
  and red, which keeps status colours (warn / danger) meaningful
  without shouting;
* the contrast between text and background is about 9:1 -- comfortably
  readable, well under the eye-straining 15:1+ you get from #fff on #000.

Owners who prefer the original blue/cyan look can switch by editing the
constants below; nothing else in the app hard-codes a colour.
"""

# ---------------------------------------------------------------- surfaces
BG = "#1d2021"            # window background (bg0_h)
BG_SIDEBAR = "#17191a"    # sidebar, a shade darker than the window
BG_DEEP = "#282828"       # header and input strips (bg0)
PANEL = "#32302f"         # cards, hover (bg1)
BORDER = "#3c3836"        # hairlines (bg2)

# ------------------------------------------------------------------- text
FG = "#ebdbb2"            # main text: warm off-white (fg1)
YOU_CLR = "#d5c4a1"       # what the user typed (fg2, slightly dimmer)
DIM = "#928374"           # secondary text, timestamps, tool output

# ---------------------------------------------------------------- accents
CYAN = "#8ec07c"          # the diamond / brand accent: soft aqua-green
WARN = "#fabd2f"          # yellow: thinking, careful
RED = "#fb4934"           # red: errors, critical, deletions
GREEN = "#b8bb26"         # green: confirmations

# --------------------------------------------------------------- bubbles
BUBBLE_U = "#32302f"      # user bubble
BUBBLE_AI = "#282828"     # ZYRO bubble

# --------------------------------------------------------------- buttons
BTN_BG = "#3c3836"
BTN_ACT = "#504945"
BTN_TEXT = "#ebdbb2"      # button label (warm, never pure white)
DANGER_BG = "#3a211f"     # DECLINE button, a dark warm red
DANGER_ACT = "#4f2b28"

# ------------------------------------------------------------ diff colours
GREEN_DIFF = "#b8bb26"    # added lines
RED_DIFF = "#fb4934"      # removed lines

# ------------------------------------------------------------------ fonts
FONT_CHAT = ("Segoe UI", 12)
FONT_MONO = ("Consolas", 9)      # diffs and tool output
FONT_NAME = ("Segoe UI", 10, "bold")
FONT_TIME = ("Segoe UI", 9)
FONT_UI = ("Segoe UI", 10)
FONT_SIDE = ("Segoe UI", 10)
FONT_BRAND = ("Segoe UI", 16, "bold")
FONT_HEAD = ("Segoe UI", 12, "bold")
FONT_SMALL = ("Segoe UI", 9)
