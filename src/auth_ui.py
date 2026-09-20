"""
Sign-in / sign-up screen. Shown by ``app.main()`` until ``st.session_state["user"]``
is set; nothing else in the app renders for an anonymous visitor.
"""
import streamlit as st

from . import auth, settings_store

_AUTH_CSS = """
<style>
    /* the workspace sidebar has no place on the sign-in screen */
    /* Hide the workspace sidebar on the sign-in screen */
    section[data-testid="stSidebar"] {
    display: none !important;
    }

    /* Form card: a light blue-grey tint, so the (white) input boxes stand out
       even before any border is drawn. */
    [data-testid="stForm"] {
        background: #eef2f9 !important; border: 1px solid #d9e0ee !important;
        border-radius: 14px !important; padding: 24px 26px !important;
        box-shadow: 0 2px 10px rgba(19,27,61,0.06);
    }
    [data-testid="stForm"] button[kind="primary"],
[data-testid="stForm"] button[type="submit"] {
    width: 100%;
}

    /* labels sit right above their box */
    [data-testid="stTextInput"] { gap: 0.3rem !important; }
    [data-testid="stTextInput"] label p { font-weight: 600 !important; color: #131b3d !important; }

    /* The input box itself. The theme (.streamlit/config.toml: borderColor +
       showWidgetBorder) already outlines it; this makes the outline stronger and
       adds a clear focus ring. Only the stable data-testid hook is used. */
    [data-testid="stTextInputRootElement"] {
        background: #ffffff !important;
        border: 2px solid #b9c2d9 !important;
        border-radius: 10px !important;
        min-height: 46px !important;
        transition: border-color .15s, box-shadow .15s;
    }
    [data-testid="stTextInputRootElement"]:hover { border-color: #8f9bbd !important; }
    [data-testid="stTextInputRootElement"]:focus-within {
        border-color: #0d9488 !important;
        box-shadow: 0 0 0 4px rgba(13,148,136,0.20) !important;
    }
    [data-testid="stTextInput"] input {
        color: #131b3d !important; font-size: 0.98rem !important;
        -webkit-text-fill-color: #131b3d !important;
    }
    [data-testid="stTextInput"] input::placeholder {
        color: #5f6884 !important; -webkit-text-fill-color: #5f6884 !important; opacity: 1 !important;
    }

    /* flat tabs instead of boxed ones on this screen */
    .stTabs [data-baseweb="tab"], .stTabs [role="tab"] { background: transparent !important; border: none !important; }
    .stTabs [role="tab"]:focus, .stTabs [role="tab"]:focus-visible { outline: none !important; box-shadow: none !important; }
    /* Keep Streamlit's password show/hide button on the right */
[data-testid="stTextInputRootElement"] {
    position: relative !important;
}

[data-testid="stTextInputRootElement"] button {
    position: absolute !important;
    right: 8px !important;
    left: auto !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    margin: 0 !important;
    z-index: 5 !important;
}

/* Leave enough room for the eye button */
[data-testid="stTextInputRootElement"] input {
    padding-right: 42px !important;
}
</style>
"""


def _brand_header():
    st.markdown(
        """
        <div style="text-align:center;margin:36px 0 22px 0;">
            <div style="display:inline-flex;align-items:center;gap:12px;">
                <div style="background:#0d9488;width:46px;height:46px;border-radius:12px;
                            display:flex;align-items:center;justify-content:center;font-size:1.5rem;">🧭</div>
                <div style="font-weight:800;font-size:2rem;color:#131b3d;">TalentIQ</div>
            </div>
            <div style="color:#6b7290;margin-top:8px;">
                Smarter shortlisting through AI — sign in to your HR workspace
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _start_session(user: dict):
    """Log the visitor in with a clean slate, then rerun into the app."""
    st.session_state.clear()          # nothing from a previous visitor can leak in
    st.session_state["user"] = user
    st.rerun()


def _sign_in_form():
    with st.form("signin_form"):
        email = st.text_input("Email", key="si_email", placeholder="you@company.com")
        password = st.text_input("Password", type="password", key="si_password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        ok, message, user = auth.sign_in(email, password)
        if ok:
            _start_session(user)
        else:
            st.error(message)
    st.caption("New here? Open the **Create account** tab.")


def _sign_up_form():
    with st.form("signup_form"):
        name = st.text_input("Full name", key="su_name", placeholder="Asha Rao")
        email = st.text_input("Work email", key="su_email", placeholder="you@company.com")
        c1, c2 = st.columns(2)
        password = c1.text_input("Password", type="password", key="su_password")
        confirm = c2.text_input("Confirm password", type="password", key="su_confirm")
        st.caption(f"At least {auth.MIN_PASSWORD_LEN} characters, with a letter and a number.")
        submitted = st.form_submit_button("Create account", type="primary")
    if submitted:
        ok, message, user = auth.sign_up(name, email, password, confirm)
        if ok:
            if user and user.get("id"):
                org = settings_store.load_org_settings(user["id"])
                org["hr_sender_name"] = user["name"]
                settings_store.save_org_settings(org, user["id"])
                _start_session(user)
            else:
                st.success(message)
        else:
            st.error(message)


def render_auth_page():
    st.markdown(_AUTH_CSS, unsafe_allow_html=True)
    _brand_header()
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        from . import db
        if not db.is_configured():
            st.warning("⚠️ **Supabase not configured**: Please set `SUPABASE_URL` and `SUPABASE_KEY` in your `.env` file or environment variables.")
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            _sign_in_form()
        with tab_up:
            _sign_up_form()
        st.caption("🔒 Authentication is secured directly by Supabase Auth.")
