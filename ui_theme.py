"""算数・国語共通のカード表示。学習や保存の処理は持ちません。"""
from html import escape

import streamlit as st


def apply_theme():
    st.markdown("""<style>
    :root { --ink: #24483e; --paper: #fffdf7; }
    .stApp { background: var(--paper); color: var(--ink); }
    [data-testid="stMainBlockContainer"] { max-width: 760px; padding-top: 2rem; padding-bottom: 3rem; }
    h1,h2,h3 { color: var(--ink); letter-spacing: .025em; }
    h2 { font-size: 1.4rem !important; }
    h3 { font-size: 1.16rem !important; }
    .study-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
    .study-brand-icon { border: 1px solid #cadace; background: #edf4e7; border-radius: 16px;
      padding: 10px 13px; font-size: 24px; }
    .study-title { font-size: clamp(1.2rem,4.8vw,1.75rem); font-weight: 700; letter-spacing: .025em; line-height: 1.45; margin: 0; padding: 0; }
    .study-brand-title + .study-brand-title::before { content: " "; }
    .study-brand p { color: #60776b; font-size: .8rem; margin: 4px 0 0; letter-spacing: .08em; }
    .study-card-heading { display: flex; align-items: center; gap: 14px; margin-bottom: 5px; }
    .study-card-icon { display: grid; place-items: center; width: 46px; height: 46px;
      flex: 0 0 46px; border-radius: 15px; background: #ffffffb3; font-size: 24px; }
    .study-card-heading h3 { padding: 0; margin: 0; }
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
    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"] {
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
      [data-testid="stMainBlockContainer"] { padding: 1.2rem 1rem 2rem; }
      [class*="st-key-review_card"], [class*="st-key-practice_card"], .st-key-user_cards {
        padding: 16px !important; border-radius: 20px; }
      .st-key-subject_navigation [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: .65rem; }
      .st-key-subject_navigation [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; }
      [data-testid="stButton"] button p { overflow-wrap: anywhere; }
      [data-testid="stTabs"] [role="tablist"] { gap: .5rem; }
    }
    @media(prefers-reduced-motion:reduce) { * { transition: none !important; } }
    @media(max-width:360px) { .study-card-heading h3 { font-size: 1.05rem !important; } }
    </style>""", unsafe_allow_html=True)


def brand():
    st.markdown('<div class="study-brand"><span class="study-brand-icon" aria-hidden="true">📚</span>'
                '<div><div role="heading" aria-level="1" class="study-title"><span class="study-brand-title">さんすう・こくご</span> '
                '<span class="study-brand-title">れんしゅう</span></div><p>すこしずつ、できた！を ふやそう。</p></div></div>',
                unsafe_allow_html=True)


def card_heading(icon, title, caption):
    st.markdown(f'<div class="study-card-heading"><span class="study-card-icon" aria-hidden="true">{escape(icon)}</span>'
                f'<div><h3>{escape(title)}</h3><p>{escape(caption)}</p></div></div>', unsafe_allow_html=True)
