# ============================================================
# TALENTIQ COLOR PALETTE
# ============================================================

NAVY = "#123B7A"          # Main brand blue
NAVY_DARK = "#071A3D"     # Deep navy
BLUE = "#2563EB"          # Primary action blue
BLUE_LIGHT = "#60A5FA"    # Light blue accent
CYAN = "#06B6D4"          # AI / technology accent
CYAN_LIGHT = "#67E8F9"    # Soft cyan
GOLD = "#F59E0B"          # Warning / premium accent

BG = "#F4F7FB"            # Main application background
CARD = "#FFFFFF"          # Cards
TEXT = "#172033"          # Main text
TEXT_MUTED = "#64748B"    # Secondary text
BORDER = "#E2E8F0"        # Borders

CSS = f"""
<style>
    #MainMenu, footer {{visibility: hidden;}}
    .stApp {{
        background: {BG};
    }}
    section[data-testid="stSidebar"] {{
        background:
            radial-gradient(
                circle at 20% 10%,
                rgba(96, 165, 250, 0.18),
                transparent 30%
            ),
            linear-gradient(
                180deg,
                #071A3D 0%,
                #0B285A 45%,
                #123B7A 100%
            );
        border-right: 1px solid rgba(255,255,255,0.08);
    }}

    section[data-testid="stSidebar"] * {{
        color: #EAF2FF !important;
    }}

    section[data-testid="stSidebar"] .stRadio label {{
        font-size: 0.95rem;
        padding: 7px 10px;
        border-radius: 8px;
        transition: all 0.2s ease;
    }}

    section[data-testid="stSidebar"] .stRadio label:hover {{
        background: rgba(255,255,255,0.10);
    }}

    section[data-testid="stSidebar"] div.stButton > button {{
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.16);
        width: 100%;
        color: white !important;
    }}

    section[data-testid="stSidebar"] div.stButton > button:hover {{
        background: rgba(96,165,250,0.20);
        border-color: rgba(96,165,250,0.45);
    }}

    section[data-testid="stSidebar"] hr {{
        border-color: rgba(255,255,255,0.12);
    }}
    div.block-container {{
        padding-top: 4.5rem;
        max-width: 1250px;
    }}

    /* Top brand bar */
        .tiq-topbar {{
            display:flex;
            align-items:center;
            justify-content:space-between;

            background:
                linear-gradient(
                    135deg,
                    #071A3D 0%,
                    #123B7A 60%,
                    #2563EB 100%
                );

            color:white;
            padding:14px 22px;
            border-radius:14px;
            margin-bottom:22px;

            box-shadow:
                0 8px 24px rgba(7,26,61,0.18);
        }}
        .tiq-brand {{ display:flex; align-items:center; gap:10px; font-weight:800; font-size:1.25rem; }}
        .tiq-brand-badge {{
        background: linear-gradient(
            135deg,
            #06B6D4,
            #2563EB
        );

        width:34px;
        height:34px;
        border-radius:9px;

        display:flex;
        align-items:center;
        justify-content:center;

        font-size:1.05rem;

        box-shadow:
            0 4px 12px rgba(6,182,212,0.30);
    }}
    .tiq-status-pill {{
        background: rgba(34,197,94,0.12);
        color: #86EFAC;
        border: 1px solid rgba(34,197,94,0.30);

        padding:5px 14px;
        border-radius:20px;
        font-size:0.8rem;
        font-weight:600;
    }}
    .tiq-user {{ text-align:right; font-size:0.8rem; opacity:0.85; line-height:1.2; }}

    /* KPI cards */
    .tiq-kpi {{
        background: white;
        border-radius: 14px;
        padding: 18px 20px;

        box-shadow:
            0 4px 14px rgba(15, 23, 42, 0.05);

        border: 1px solid #E2E8F0;

        transition:
            transform 0.2s ease,
            box-shadow 0.2s ease;
    }}

    .tiq-kpi:hover {{
        transform: translateY(-2px);

        box-shadow:
            0 8px 22px rgba(15, 23, 42, 0.08);
    }}

    .tiq-kpi .label {{
        font-size:0.78rem;
        color:#64748B;
        font-weight:600;
        text-transform:uppercase;
        letter-spacing:0.02em;
    }}

    .tiq-kpi .value {{
        font-size:1.9rem;
        font-weight:800;
        color:{NAVY};
        margin-top:4px;
    }}
    /* generic card */
    .tiq-card {{
        background: {CARD};
        border-radius: 14px;
        padding: 20px 22px;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
        border: 1px solid {BORDER};
        margin-bottom: 16px;
    }}

    .tiq-card h4 {{
        margin-top: 0;
        color: {NAVY};
    }}

    /* badges */
    .tiq-badge {{ padding: 3px 12px; border-radius:20px; font-size:0.76rem; font-weight:700; display:inline-block;}}
    .badge-strong {{ background:#dcfce7; color:#15803d; }}
    .badge-good {{ background:#dbeafe; color:#1d4ed8; }}
    .badge-review {{ background:#fef3c7; color:#b45309; }}
    .badge-low {{ background:#fee2e2; color:#b91c1c; }}

    .tiq-skill-chip {{
        display:inline-block; padding:3px 10px; border-radius:14px; font-size:0.75rem;
        margin:2px 4px 2px 0; font-weight:600;
    }}
    .chip-match {{
    background: #ECFEFF;
    color: #0E7490;
    border: 1px solid #A5F3FC;
    }}
    .chip-missing {{ background:#fff1f2; color:#be123c; border:1px solid #fecdd3;}}
    .chip-extra {{ background:#f1f5f9; color:#475569; border:1px solid #e2e8f0;}}

    .tiq-rank-row {{
        display:flex; align-items:center; padding:10px 6px; border-bottom:1px solid #eef1f8;
    }}

    h1, h2, h3 {{ color:{NAVY}; }}

    div.stButton > button[kind="primary"] {{
        background: {BLUE};
        border-color: {BLUE};
        color: white !important;
        font-weight: 700;
        border-radius: 9px;
        box-shadow: 0 4px 10px rgba(37, 99, 235, 0.20);
    }}

    div.stButton > button[kind="primary"]:hover {{
        background: #1D4ED8;
        border-color: #1D4ED8;
        box-shadow: 0 6px 14px rgba(37, 99, 235, 0.28);
    }}
    div.stButton > button {{
        border-radius:9px;
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background: white; border-radius:8px 8px 0 0; padding: 8px 16px; border:1px solid #e7eaf3; border-bottom:none;
    }}
    .stProgress > div > div > div > div {{
        background-color: {BLUE};
    }}
</style>
"""


def inject(st):
    st.markdown(CSS, unsafe_allow_html=True)


def topbar(st, subtitle="Resume Screening"):
    import html
    user = st.session_state.get("user")
    who = (f"<b>{html.escape(user['name'])}</b><br/>{html.escape(user['email'])}"
           if user else "<b>Not signed in</b>")
    st.markdown(
        f"""
        <div class="tiq-topbar">
            <div class="tiq-brand">
                <div class="tiq-brand-badge">🧭</div>
                TalentIQ <span style="font-weight:400;opacity:0.6;font-size:0.85rem;">| {subtitle}</span>
            </div>
            <div style="display:flex; align-items:center; gap:16px;">
                <div class="tiq-status-pill">● AI Engine Ready</div>
                <div class="tiq-user">{who}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(st, label, value):
    st.markdown(
        f"""<div class="tiq-kpi"><div class="label">{label}</div><div class="value">{value}</div></div>""",
        unsafe_allow_html=True,
    )


def status_badge_html(status: str) -> str:
    cls = {
        "Strong Match": "badge-strong",
        "Good Match": "badge-good",
        "Review": "badge-review",
        "Low Match": "badge-low",
    }.get(status, "badge-review")
    return f'<span class="tiq-badge {cls}">{status}</span>'
