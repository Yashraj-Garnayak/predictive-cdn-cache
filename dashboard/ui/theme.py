"""Look of the live view: colours, fonts, spacing and the page CSS. Change the design here."""
from __future__ import annotations

# ---------- colours (Apple dark-mode palette) ----------
BG = "#000000"
CARD = "rgba(28, 28, 30, 0.72)"        # #1C1C1E, see-through so the blur shows
CARD_SOLID = "#1C1C1E"
BORDER = "rgba(255, 255, 255, 0.08)"
TEXT = "#F5F5F7"
MUTED = "#8E8E93"
GREEN = "#30D158"                      # model predicted it
PINK = "#FF375F"                       # model missed it

# One colour per policy, used everywhere (chart lines, legends, cards)
POLICY_COLORS = {"Hybrid": "#0A84FF", "LFU": "#BF5AF2", "Predictive": "#FF9F0A", "LRU": "#8E8E93"}

# ---------- type and spacing ----------
FONT = ('-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, '
        '"Helvetica Neue", Helvetica, Arial, sans-serif')
RADIUS = "20px"                        # cards
RADIUS_SM = "12px"                     # inputs, buttons, table rows
GAP = "24px"                           # space between cards
PAD = "24px"                           # space inside cards
BLUR = "blur(24px) saturate(180%)"     # frosted glass
SHADOW = "0 10px 40px rgba(0, 0, 0, 0.45), 0 1px 0 rgba(255, 255, 255, 0.04) inset"
EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)"


def css_vars() -> str:
    """The theme as CSS custom properties, shared by the page and the bubble component."""
    return (f":root {{ --bg: {BG}; --card: {CARD}; --card-solid: {CARD_SOLID}; --border: {BORDER};"
            f" --text: {TEXT}; --muted: {MUTED}; --green: {GREEN}; --pink: {PINK};"
            f" --blue: {POLICY_COLORS['Hybrid']}; --purple: {POLICY_COLORS['LFU']};"
            f" --orange: {POLICY_COLORS['Predictive']}; --font: {FONT}; --radius: {RADIUS};"
            f" --radius-sm: {RADIUS_SM}; --gap: {GAP}; --pad: {PAD}; --blur: {BLUR};"
            f" --shadow: {SHADOW}; --ease: {EASE}; }}")


# Keys of the st.container cards; Streamlit gives each one the CSS class "st-key-<key>".
CARD_KEYS = ["lv_header", "lv_bubbles", "lv_table", "lv_chart"]

PAGE_CSS = """
/* ---------- page and sidebar ---------- */
.stApp {
  background: radial-gradient(1200px 600px at 10% -10%, rgba(10,132,255,0.16), transparent 60%),
              radial-gradient(900px 500px at 100% 0%, rgba(191,90,242,0.12), transparent 60%),
              var(--bg);
  color: var(--text); font-family: var(--font);
}
.stApp, .stApp p, .stApp label, .stApp span, .stApp li, .stApp h1, .stApp h2, .stApp h3 {
  font-family: var(--font); color: var(--text);
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1440px; }
[data-testid="stSidebar"] {
  background: rgba(28,28,30,0.6); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur);
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] * { color: var(--text); }
[data-testid="stSidebarNav"] a span { color: var(--muted); }
[data-testid="stCaptionContainer"], .stApp small { color: var(--muted) !important; }
[data-testid="stVerticalBlock"] { gap: var(--gap); }

/* ---------- glass cards ---------- */
__CARDS__ {
  background: var(--card); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur);
  border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: var(--pad);
}
.st-key-lv_header { padding: 18px var(--pad); }
.st-key-lv_header [data-testid="stVerticalBlock"],
.st-key-lv_bubbles [data-testid="stVerticalBlock"],
.st-key-lv_table [data-testid="stVerticalBlock"],
.st-key-lv_chart [data-testid="stVerticalBlock"] { gap: 12px; }
.st-key-lv_header [data-testid="stHorizontalBlock"] { align-items: center; }

/* ---------- widgets (colours come from .streamlit/config.toml; this adds the glass look) ---------- */
.stApp [data-testid="stTextInputRootElement"], .stApp [data-testid="stNumberInputContainer"],
.stApp .stSelectbox [role="group"] {
  background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: var(--radius-sm);
}
.stApp input { background: transparent !important; color: var(--text); }

.stButton button {
  width: 100%; white-space: nowrap; border-radius: 999px; padding: 6px 12px; font-weight: 600; letter-spacing: -0.01em;
  background: rgba(255,255,255,0.08); color: var(--text); border: 1px solid var(--border);
  transition: transform .2s var(--ease), background .2s var(--ease);
}
.stButton button:hover { background: rgba(255,255,255,0.14); border-color: rgba(255,255,255,0.18); color: var(--text); }
.stButton button:active { transform: scale(0.97); }
.stButton button[kind="primary"] { background: var(--blue); border-color: transparent; color: #fff; }
.stButton button[kind="primary"]:hover { background: #3b9bff; color: #fff; }
.stButton button p { color: inherit; }

/* ---------- header ---------- */
.lv-title { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.15; }
.lv-sub { color: var(--muted); font-size: 14px; margin-top: 2px; }
.lv-sub b { color: var(--text); font-weight: 500; }
.lv-progress { margin-top: 6px; }
.lv-progress-row { display: flex; justify-content: space-between; font-size: 13px; color: var(--muted); margin-bottom: 8px; }
.lv-progress-row b { color: var(--text); font-weight: 600; }
.lv-track { height: 6px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; }
.lv-fill {
  height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--blue), var(--purple));
  box-shadow: 0 0 12px rgba(10,132,255,0.6); animation: lv-grow .6s var(--ease) both;
}
@keyframes lv-grow { from { width: var(--from); } to { width: var(--to); } }
.lv-status { display: inline-flex; align-items: center; gap: 6px; }
.lv-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.lv-dot.playing { background: var(--green); box-shadow: 0 0 8px var(--green); animation: lv-pulse 1.6s ease-in-out infinite; }
@keyframes lv-pulse { 50% { opacity: .35; } }

/* ---------- metric cards ---------- */
.lv-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--gap); }
@media (max-width: 900px) { .lv-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.lv-metric {
  position: relative; background: var(--card); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur);
  border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 20px var(--pad); overflow: hidden;
}
.lv-metric::before {          /* thin accent glow along the top edge */
  content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent); opacity: .9;
}
.lv-metric-label { font-size: 13px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.lv-info {
  width: 15px; height: 15px; border-radius: 50%; border: 1px solid var(--muted); color: var(--muted);
  font-size: 10px; display: inline-flex; align-items: center; justify-content: center; cursor: help; position: relative;
}
.lv-info .lv-tip {
  visibility: hidden; opacity: 0; position: absolute; left: 50%; top: 22px; transform: translateX(-50%) translateY(-4px);
  width: 230px; padding: 10px 12px; border-radius: var(--radius-sm); background: rgba(44,44,46,0.96);
  border: 1px solid var(--border); color: var(--text); font-size: 12.5px; line-height: 1.4; z-index: 10;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5); transition: opacity .2s var(--ease), transform .2s var(--ease);
}
.lv-info:hover .lv-tip { visibility: visible; opacity: 1; transform: translateX(-50%) translateY(0); }
.lv-metric-value { font-size: 40px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; margin-top: 10px; }
.lv-metric-value small { font-size: 20px; color: var(--muted) !important; font-weight: 600; }
.lv-delta { display: inline-block; margin-top: 8px; font-size: 12.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.lv-delta.good { color: var(--green); background: rgba(48,209,88,0.14); }
.lv-delta.bad { color: var(--pink); background: rgba(255,55,95,0.14); }
.lv-delta.flat { color: var(--muted); background: rgba(142,142,147,0.14); }

/* ---------- section headings and legend ---------- */
.lv-h { font-size: 19px; font-weight: 700; letter-spacing: -0.01em; }
.lv-hsub { font-size: 13px; color: var(--muted); margin-top: 2px; }
.lv-legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: var(--muted); }
.lv-legend span { display: inline-flex; align-items: center; gap: 6px; }
.lv-legend i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }

/* ---------- predicted vs actual table ---------- */
.lv-table { width: 100%; border-collapse: separate; border-spacing: 0 4px; font-size: 13.5px; table-layout: fixed; }
.lv-table th { text-align: left; font-weight: 500; color: var(--muted); font-size: 12px; padding: 0 8px 4px; }
.lv-table td { padding: 7px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lv-table td.rank { color: var(--muted); padding: 7px 4px 7px 0; text-align: right; text-overflow: clip; font-variant-numeric: tabular-nums; }
.lv-table td.num { text-align: right; width: 56px; font-variant-numeric: tabular-nums; color: var(--muted); }
.lv-table td.cell { border-radius: var(--radius-sm) 0 0 var(--radius-sm); }
.lv-table td.cell + td.num { border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.lv-table td.match, .lv-table td.match + td.num { background: rgba(48,209,88,0.13); color: var(--text); }
.lv-table td.match + td.num { color: var(--green); }
.lv-table td.miss, .lv-table td.miss + td.num { background: rgba(255,55,95,0.08); }
.lv-table .gap { width: 10px; }
.lv-pip { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 8px; vertical-align: 1px; }
.lv-pip.match { background: var(--green); box-shadow: 0 0 6px var(--green); }
.lv-pip.miss { background: var(--pink); }
.lv-pip.none { background: rgba(255,255,255,0.18); }

/* ---------- empty state ---------- */
.lv-empty { text-align: center; padding: 56px 24px; }
.lv-empty h2 { font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; }
.lv-empty p { color: var(--muted) !important; max-width: 560px; margin: 0 auto; font-size: 15px; line-height: 1.55; }

/* hidden data hand-off to the bubble component */
.pcache-bubble-data { display: none; }
"""


def page_css() -> str:
    """Complete <style> block for the live view."""
    cards = ", ".join(f".st-key-{k}" for k in CARD_KEYS)
    return f"<style>{css_vars()}{PAGE_CSS.replace('__CARDS__', cards)}</style>"
