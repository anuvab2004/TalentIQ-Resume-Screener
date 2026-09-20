NAVY = "#131b3d"
NAVY_DARK = "#0c1230"
TEAL = "#0d9488"
TEAL_LIGHT = "#14b8a6"
GOLD = "#d99a3d"
BG = "#f4f6fb"

CSS = f"""
<style>
    #MainMenu, footer {{visibility: hidden;}}
    .stApp {{
        background: {BG};
    }}
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {NAVY} 0%, {NAVY_DARK} 100%);
    }}
    section[data-testid="stSidebar"] * {{
        color: #e7ebf7 !important;
    }}

        

    section[data-testid="stSidebar"] .stRadio label {{
        font-size: 0.95rem;
        padding: 2px 0;
    }}
    section[data-testid="stSidebar"] div.stButton > button {{
        background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.25); width: 100%;
    }}
    section[data-testid="stSidebar"] div.stButton > button:hover {{
        background: rgba(255,255,255,0.16); border-color: rgba(255,255,255,0.45);
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
        display:flex; align-items:center; justify-content:space-between;
        background:{NAVY}; color:white; padding:14px 22px; border-radius:14px;
        margin-bottom: 22px; box-shadow: 0 6px 18px rgba(19,27,61,0.18);
    }}
    .tiq-brand {{ display:flex; align-items:center; gap:10px; font-weight:800; font-size:1.25rem; }}
    .tiq-brand-badge {{
        background:{TEAL}; width:34px; height:34px; border-radius:9px;
        display:flex; align-items:center; justify-content:center; font-size:1.05rem;
    }}
    .tiq-status-pill {{
        background: rgba(13,148,136,0.18); color:{TEAL_LIGHT}; border:1px solid rgba(20,184,166,0.4);
        padding:5px 14px; border-radius:20px; font-size:0.8rem; font-weight:600;
    }}
    .tiq-user {{ text-align:right; font-size:0.8rem; opacity:0.85; line-height:1.2; }}

    /* KPI cards */
    .tiq-kpi {{
        background:white; border-radius:14px; padding:18px 20px; box-shadow:0 2px 10px rgba(19,27,61,0.06);
        border:1px solid #e7eaf3;
    }}
    .tiq-kpi .label {{ font-size:0.78rem; color:#6b7290; font-weight:600; text-transform:uppercase; letter-spacing:0.02em;}}
    .tiq-kpi .value {{ font-size:1.9rem; font-weight:800; color:{NAVY}; margin-top:4px;}}

    /* generic card */
    .tiq-card {{
        background:white; border-radius:14px; padding:20px 22px; box-shadow:0 2px 10px rgba(19,27,61,0.06);
        border:1px solid #e7eaf3; margin-bottom: 16px;
    }}
    .tiq-card h4 {{ margin-top:0; color:{NAVY}; }}

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
    .chip-match {{ background:#e6fbf6; color:#0d9488; border:1px solid #b7ede4;}}
    .chip-missing {{ background:#fff1f2; color:#be123c; border:1px solid #fecdd3;}}
    .chip-extra {{ background:#f1f5f9; color:#475569; border:1px solid #e2e8f0;}}

    .tiq-rank-row {{
        display:flex; align-items:center; padding:10px 6px; border-bottom:1px solid #eef1f8;
    }}

    h1, h2, h3 {{ color:{NAVY}; }}

    div.stButton > button[kind="primary"] {{
        background:{TEAL}; border-color:{TEAL}; font-weight:700; border-radius:9px;
    }}
    div.stButton > button[kind="primary"]:hover {{
        background:{TEAL_LIGHT}; border-color:{TEAL_LIGHT};
    }}
    div.stButton > button {{
        border-radius:9px;
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background: white; border-radius:8px 8px 0 0; padding: 8px 16px; border:1px solid #e7eaf3; border-bottom:none;
    }}
    .stProgress > div > div > div > div {{ background-color: {TEAL}; }}
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
