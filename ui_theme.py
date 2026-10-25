"""算数・国語共通のカード表示。学習や保存の処理は持ちません。"""
from html import escape

import streamlit as st


def apply_theme():
    st.markdown("""<style>
    :root { --ink: #24483e; --paper: #fffdf7; }
    .stApp { background: var(--paper); color: var(--ink); }
    /* Keep the first line below Streamlit's fixed 3.75rem toolbar on every screen. */
    [data-testid="stMainBlockContainer"] { max-width: 760px;
      padding-top: calc(4.5rem + env(safe-area-inset-top, 0px)); padding-bottom: 3rem; }
    h1,h2,h3 { color: var(--ink); letter-spacing: .025em; }
    h2 { font-size: 1.4rem !important; }
    h3 { font-size: 1.16rem !important; }
    .study-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
    .study-brand > div, .study-card-heading > div { min-width: 0; }
    .study-brand-icon { border: 1px solid #cadace; background: #edf4e7; border-radius: 16px;
      padding: 10px 13px; font-size: 24px; flex: 0 0 auto; }
    .study-title { font-size: clamp(1.2rem,4.8vw,1.75rem); font-weight: 700; letter-spacing: .025em; line-height: 1.45; margin: 0; padding: 0; }
    .study-brand-title + .study-brand-title::before { content: " "; }
    .study-brand p { color: #60776b; font-size: .8rem; margin: 4px 0 0; letter-spacing: .08em; }
    .study-card-heading { display: flex; align-items: center; gap: 14px; margin-bottom: 5px; }
    .study-card-icon { display: grid; place-items: center; width: 46px; height: 46px;
      flex: 0 0 46px; border-radius: 15px; background: #ffffffb3; font-size: 24px; }
    .study-card-heading h3 { padding: 0; margin: 0; overflow-wrap: anywhere; }
    .study-card-heading p { color: #476454; font-size: .86rem; margin: 4px 0 0; line-height: 1.65; }
    [class*="st-key-review_card"], [class*="st-key-practice_card"], .st-key-user_cards {
      border-radius: 24px; padding: 22px !important; border: 1px solid #d9e4d8;
      box-shadow: 0 5px 18px #24483e08; }
    [class*="st-key-review_card"] { background: #d8ead2; }
    .st-key-practice_card_math { background: #e1f0fa; border-color: #cce0ec; }
    .st-key-practice_card_japanese { background: #fce7dc; border-color: #ecd6c9; }
    .st-key-user_cards { background: #fff; }
    [data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button,
    [data-testid="stDownloadButton"] button { min-height: 48px; border-radius: 14px;
      border-color: #d3ded5; color: var(--ink); font-weight: 650; transition: background .15s; }
    [data-testid="stButton"] button p, [data-testid="stFormSubmitButton"] button p,
    [data-testid="stDownloadButton"] button p { white-space: normal; overflow-wrap: anywhere; }
    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind^="primary"] {
      background: #24483e; color: #fffdf7; border-color: #24483e; }
    [data-testid="stButton"] button:hover { border-color: #698a72; background: #edf4e7; }
    [data-testid="stButton"] button[kind="primary"]:hover { background: #315c4e; color: white; }
    button:focus-visible, summary:focus-visible { outline: 3px solid #7b9c62 !important; outline-offset: 3px; }
    [class*="st-key-review_card"] [data-testid="stButton"] button { background: #24483e;
      border-color: #24483e; color: #fffdf7; }
    .st-key-subject_math button { background: #e1f0fa; border-color: #cce0ec; min-height: 66px; }
    .st-key-subject_japanese button { background: #fce7dc; border-color: #ecd6c9; min-height: 66px; }
    .st-key-subject_math button:disabled, .st-key-subject_japanese button:disabled {
      opacity: 1; color: var(--ink); box-shadow: inset 0 -3px #66846f; }
    [data-testid="stExpander"] { border-radius: 16px; border-color: #d5dfd4; background: #ffffff75; }
    [data-testid="stExpander"] summary { min-height: 48px; }
    [data-testid="stMetric"] { padding: 14px; background: #edf4e7; border-radius: 18px; }
    [data-testid="stTabs"] button { min-height: 48px; white-space: normal; }
    [data-testid="stCaptionContainer"] { color: #58705f; }
    [data-testid="stForm"] { border-radius: 22px; background: #fff; }
    @media(max-width:640px) {
      .study-brand-title { display: block; }
      .study-brand-title + .study-brand-title::before { content: none; }
      [data-testid="stMainBlockContainer"] { padding-right: 1rem; padding-left: 1rem; padding-bottom: 2rem; }
      [class*="st-key-review_card"], [class*="st-key-practice_card"], .st-key-user_cards {
        padding: 16px !important; border-radius: 20px; }
      .st-key-subject_navigation [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: .65rem; }
      .st-key-subject_navigation [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; }
      [data-testid="stTabs"] [role="tablist"] { gap: .5rem; }
    }
    @media(prefers-reduced-motion:reduce) { * { transition: none !important; } }
    @media(max-width:360px) { .study-card-heading h3 { font-size: 1.05rem !important; } }
    .study-brand--compact { font-size: 16px; font-weight: 700; margin: 0; line-height: 1.4; }
    [data-testid="stMainBlockContainer"]:has(.study-brand--compact) { padding-top: calc(4rem + env(safe-area-inset-top,0px)); padding-bottom: 1rem; }
    [data-testid="stMainBlockContainer"]:has(.study-brand--compact) > [data-testid="stVerticalBlock"] { gap: .5rem; }
    [data-testid="stMainBlockContainer"]:has(.study-brand--compact) [data-testid="stProgress"] p { margin-bottom: 4px; }
    @media(max-height:740px) { [data-testid="stMarkdown"]:has(.study-brand--compact) { display: none; } }
    .st-key-fc_settings [data-testid="stVerticalBlock"] { gap: .65rem; }
    .st-key-fc_settings_header [data-testid="stHorizontalBlock"],
    .st-key-fc_answer_range [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: .65rem; }
    .st-key-fc_settings_header [data-testid="stColumn"],
    .st-key-fc_answer_range [data-testid="stColumn"] { min-width: 0 !important; }
    .st-key-fc_settings_header [data-testid="stColumn"]:first-child { flex: 0 0 76px !important; }
    .st-key-fc_settings_header [data-testid="stColumn"]:last-child { flex: 1 1 0 !important; }
    .st-key-fc_settings_header button { padding: 6px !important; white-space: nowrap; }
    .st-key-fc_answer_range [data-testid="stColumn"] { flex: 1 1 0 !important; }
    .st-key-fc_settings .fc-settings-title { padding: 10px 0; margin: 0; font-size: 1.1rem !important; line-height: 1.5; }
    .st-key-fc_settings .fc-settings-title span { font-size: .85rem; font-weight: 500; color: #58705f; }
    .st-key-fc_settings .st-key-fc_mode, .st-key-fc_settings .st-key-fc_order { width: 100% !important; }
    .st-key-fc_settings [data-testid="stRadio"] [role="radiogroup"] { display: flex; flex-wrap: nowrap; gap: 6px; width: 100%; }
    .st-key-fc_settings [data-testid="stRadio"] [role="radiogroup"] > div { flex: 1 1 0; min-width: 0; }
    .st-key-fc_settings [data-testid="stRadio"] :is(label[data-baseweb="radio"], [data-testid="stRadioOption"]) {
      flex: 1 1 0; min-width: 0; min-height: 46px; margin: 0; padding: 6px;
      display: flex; justify-content: center; width: 100%;
      border: 1px solid #d3ded5; border-radius: 10px; background: #fffdf7; color: #24483e; }
    .st-key-fc_settings [data-testid="stRadio"] :is(label[data-baseweb="radio"], [data-testid="stRadioOption"]):has(input:checked) {
      background: #24483e; border-color: #24483e; color: #fffdf7; }
    .st-key-fc_settings [data-testid="stRadio"] :is(label[data-baseweb="radio"], [data-testid="stRadioOption"]) p { color: inherit; font-size: .9rem; }
    .st-key-fc_settings [data-testid="stRadioOption"] > div > div:not([data-testid]) { display: none; }
    .st-key-fc_answer_range input { min-height: 44px; font-size: 18px; }
    .st-key-fc_answer_range [data-testid="stNumberInput"] button { min-height: 44px; }
    </style>""", unsafe_allow_html=True)


def brand():
    if st.session_state.get("screen") == "flashcard_settings":
        return
    if st.session_state.get("screen") in ("practice", "jp_practice", "flashcard_practice"):
        st.markdown('<div class="study-brand study-brand--compact" role="heading" aria-level="1">📚 れんしゅう</div>', unsafe_allow_html=True)
        return
    st.markdown('<div class="study-brand"><span class="study-brand-icon" aria-hidden="true">📚</span>'
                '<div><div role="heading" aria-level="1" class="study-title"><span class="study-brand-title">さんすう・こくご</span> '
                '<span class="study-brand-title">れんしゅう</span></div><p>すこしずつ、できた！を ふやそう。</p></div></div>',
                unsafe_allow_html=True)


def card_heading(icon, title, caption):
    st.markdown(f'<div class="study-card-heading"><span class="study-card-icon" aria-hidden="true">{escape(icon)}</span>'
                f'<div><h3>{escape(title)}</h3><p>{escape(caption)}</p></div></div>', unsafe_allow_html=True)
