"""Streamlit entry point for PinkyDocs AI."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pinkydocs.auth_service import AuthError, AuthService, clear_auth_state
from pinkydocs.config import ConfigurationError, load_settings
from pinkydocs.document_loader import DocumentError
from pinkydocs.gemini_client import GeminiClient, GeminiError
from pinkydocs.qa_service import answer_question
from pinkydocs.storage_service import StorageService
from pinkydocs.supabase_service import SupabaseService
from pinkydocs.usage_service import UsageError, UsageLimiter


st.set_page_config(
    page_title="PinkyDocs AI",
    page_icon="assets/pinkydocs_mascot.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
:root { --pink:#C84D89; --soft:#FFF1F7; --ink:#272334; --muted:#777282; --line:#EAE5EB; --paper:#fff; }
.stApp { background: #FCFAFC; color:var(--ink); font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
[data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--line); }
h1,h2,h3 { font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif !important; letter-spacing:-.035em; }
button[kind="primary"] { background:var(--pink); border-color:var(--pink); }
button[kind="primary"]:hover { background:#B43B76; border-color:#B43B76; }
[data-testid="stChatMessage"] { border:1px solid var(--line); border-radius:18px; padding:.8rem 1rem; background:#fff; }
[data-testid="stChatInput"] { border-radius:18px; }
.brand-caption { color:#777282; font-size:.92rem; margin-top:-.4rem; }
.tiny-label { color:#777282; text-transform:uppercase; letter-spacing:.08em; font-size:.72rem; font-weight:700; }
.welcome-card { border:1px solid #F0DCE6; background:linear-gradient(140deg,#fff 60%,#FFF1F7); border-radius:24px; padding:2rem; }
.pill { border:1px solid #EADCE4; padding:.24rem .65rem; border-radius:999px; color:#777282; font-size:.8rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def _services():
    settings = load_settings(st.secrets)
    settings.validate_web()
    repository = SupabaseService.from_settings(settings)
    return settings, repository, AuthService(repository), StorageService(repository, settings)


def _asset() -> Path:
    return ROOT / "assets" / "pinkydocs_mascot.svg"


def _login_screen(auth: AuthService) -> None:
    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        st.image(str(_asset()), width=96)
        st.markdown("# PinkyDocs AI")
        st.markdown('<p class="brand-caption">Your documents. Your answers.</p>', unsafe_allow_html=True)
        mode = st.radio("Account", ["Log in", "Create account"], horizontal=True, label_visibility="collapsed")
        with st.form("auth_form", clear_on_submit=False):
            username = st.text_input("Username", max_chars=24, autocomplete="username")
            password = st.text_input("Password", type="password", max_chars=128, autocomplete="current-password")
            submitted = st.form_submit_button("Continue" if mode == "Log in" else "Create account", type="primary", use_container_width=True)
        st.caption("Use 3–24 letters, numbers, dots, underscores or hyphens. Passwords must be at least 8 characters.")
        if submitted:
            try:
                with st.spinner("Checking your account…"):
                    identity = auth.login(username, password) if mode == "Log in" else auth.register(username, password)
                now = time.time()
                st.session_state["user_id"] = identity.id
                st.session_state["username"] = identity.username
                st.session_state["authenticated_at"] = now
                st.session_state["last_activity"] = now
                st.session_state["current_conversation_id"] = None
                st.session_state["selected_document_ids"] = []
                st.session_state["messages"] = []
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Account access could not be completed. Please try again.")


def _source_panel(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander(f"Sources · {len(citations)}"):
        for citation in citations:
            st.text(citation.get("label", citation.get("filename", "Document source")))
            excerpt = citation.get("excerpt")
            if excerpt:
                st.text(excerpt)


def _render_messages(messages: list[dict]) -> None:
    mascot = str(_asset())
    for message in messages:
        role = message.get("role", "assistant")
        with st.chat_message(role, avatar=mascot if role == "assistant" else "🧑"):
            st.markdown(message.get("content", ""))
            if role == "assistant":
                _source_panel(message.get("citations") or [])


def _handle_uploads(storage: StorageService, user_id: str, settings) -> None:
    with st.expander("Add a document", expanded=False):
        with st.form("upload_form", clear_on_submit=True):
            uploaded = st.file_uploader(
                "Choose a PDF or TXT file",
                type=["pdf", "txt"],
                max_upload_size=settings.max_upload_mb,
                help=f"Up to {settings.max_upload_mb} MB. Scanned PDFs are not supported.",
            )
            title = st.text_input("Display name (optional)", max_chars=120)
            submit = st.form_submit_button("Upload and index", type="primary")
        if submit:
            if not uploaded:
                st.error("Choose a file first.")
            else:
                try:
                    with st.spinner("Extracting and indexing locally…"):
                        row = storage.upload(user_id, uploaded.name, uploaded.getvalue(), title or None)
                    st.success("Document added and indexed.")
                    st.rerun()
                except DocumentError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc, ValueError) else "Upload failed. Please try again.")

    with st.expander("Paste text", expanded=False):
        with st.form("paste_form", clear_on_submit=True):
            title = st.text_input("Document title", max_chars=120, key="paste_title")
            pasted = st.text_area("Document text", height=150, key="paste_content")
            submit = st.form_submit_button("Save pasted document", type="primary")
        if submit:
            try:
                with st.spinner("Indexing text…"):
                    row = storage.save_pasted_text(user_id, title, pasted)
                st.success("Pasted text added and indexed.")
                st.rerun()
            except DocumentError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "Text could not be saved. Please try again.")


def _new_conversation(repository: SupabaseService, user_id: str) -> None:
    row = repository.create_conversation(user_id, "New conversation", [])
    st.session_state["current_conversation_id"] = str(row["id"])
    st.session_state["selected_document_ids"] = []
    st.session_state["messages"] = []
    st.session_state["document_selector"] = []


def _render_authenticated(settings, repository: SupabaseService, storage: StorageService) -> None:
    user_id = st.session_state["user_id"]
    now = time.time()
    last_activity = st.session_state.get("last_activity", now)
    max_age = settings.session_timeout_minutes * 60
    created = st.session_state.get("authenticated_at", now)
    if (
        now - last_activity > max_age
        or now - created > settings.max_session_lifetime_hours * 60 * 60
    ):
        clear_auth_state(st.session_state)
        st.warning("Your session expired. Please sign in again.")
        st.rerun()
    st.session_state["last_activity"] = now

    try:
        documents = repository.list_documents(user_id)
        conversations = repository.list_conversations(user_id)
    except Exception:
        st.error("Your saved workspace could not be loaded. Please refresh in a moment.")
        st.stop()
    doc_by_id = {str(item["id"]): item for item in documents}

    with st.sidebar:
        st.image(str(_asset()), width=42)
        st.markdown("### PinkyDocs AI")
        st.caption("Signed in as")
        st.text(st.session_state["username"])
        if st.button("＋  New conversation", type="primary", use_container_width=True):
            try:
                _new_conversation(repository, user_id)
                st.rerun()
            except Exception:
                st.error("A new conversation could not be created.")
        st.markdown('<p class="tiny-label">My documents</p>', unsafe_allow_html=True)
        _handle_uploads(storage, user_id, settings)
        if documents:
            for row in documents:
                col_name, col_delete = st.columns([4, 1])
                with col_name:
                    st.text(f"{row['file_type'].upper()} · {row['display_name']}")
                with col_delete:
                    if st.button("×", key=f"delete_{row['id']}", help="Delete this document"):
                        st.session_state["confirm_delete"] = str(row["id"])
                if st.session_state.get("confirm_delete") == str(row["id"]):
                    st.text(row["display_name"])
                    st.warning("Delete the selected document?")
                    confirm_col, cancel_col = st.columns(2)
                    with confirm_col:
                        if st.button("Delete", key=f"confirm_{row['id']}", type="primary"):
                            try:
                                repository.delete_document(user_id, str(row["id"]))
                                st.session_state.pop("confirm_delete", None)
                                st.rerun()
                            except Exception:
                                st.error("Document deletion failed. Please retry.")
                    with cancel_col:
                        if st.button("Cancel", key=f"cancel_{row['id']}"):
                            st.session_state.pop("confirm_delete", None)
                            st.rerun()
        current_id = st.session_state.get("current_conversation_id")
        if current_id and any(str(item["id"]) == current_id for item in conversations):
            stored_ids = repository.get_conversation_documents(user_id, current_id)
            if st.session_state.get("_selector_conversation") != current_id:
                st.session_state["document_selector"] = [item for item in stored_ids if item in doc_by_id]
                st.session_state["_selector_conversation"] = current_id
        else:
            stored_ids = []
            st.session_state.setdefault("document_selector", [])
        if "document_selector" in st.session_state:
            st.session_state["document_selector"] = [
                item for item in st.session_state["document_selector"] if item in doc_by_id
            ]
        if documents and current_id:
            selected_ids = st.multiselect(
                "Use in this conversation",
                options=list(doc_by_id),
                format_func=lambda key: doc_by_id[key]["display_name"],
                key="document_selector",
                placeholder="Select one or more documents",
            )
            st.session_state["selected_document_ids"] = selected_ids
            if current_id and set(selected_ids) != set(stored_ids):
                try:
                    repository.set_conversation_documents(user_id, current_id, selected_ids)
                except Exception:
                    st.error("Document selection could not be saved.")
        elif documents:
            st.info("Start a conversation to choose its sources.")
        else:
            st.info("Upload a document or paste text to get started.")

        st.markdown('<p class="tiny-label">Saved conversations</p>', unsafe_allow_html=True)
        if conversations:
            conversation_ids = [str(item["id"]) for item in conversations]
            labels = {str(item["id"]): item["title"] for item in conversations}
            current = st.session_state.get("current_conversation_id")
            if current not in labels:
                selected_conversation = st.selectbox(
                    "Open conversation",
                    options=conversation_ids,
                    format_func=lambda key: labels[key],
                    label_visibility="collapsed",
                    key="conversation_selector",
                )
                st.session_state["current_conversation_id"] = selected_conversation
                st.session_state["messages"] = repository.get_messages(user_id, selected_conversation)
                st.session_state["_selector_conversation"] = None
                st.rerun()
            selected_conversation = st.selectbox(
                "Open conversation",
                options=conversation_ids,
                index=conversation_ids.index(current),
                format_func=lambda key: labels[key],
                label_visibility="collapsed",
                key="conversation_selector",
            )
            if selected_conversation != current:
                st.session_state["current_conversation_id"] = selected_conversation
                st.session_state["messages"] = repository.get_messages(user_id, selected_conversation)
                st.session_state["_selector_conversation"] = None
                st.rerun()
        if st.button("Log out", use_container_width=True):
            clear_auth_state(st.session_state)
            st.rerun()

    st.markdown("## Your document workspace")
    current_id = st.session_state.get("current_conversation_id")
    selected_ids = st.session_state.get("selected_document_ids", [])
    st.caption(f"{len(selected_ids)} document(s) selected")
    if not current_id:
        st.markdown(
            '<div class="welcome-card"><span class="tiny-label">PinkyDocs AI</span>'
            '<h2>Your documents. Your answers.</h2>'
            '<p>Choose a document in the sidebar, then start a conversation. '
            'Answers are grounded in the passages the app retrieves.</p></div>',
            unsafe_allow_html=True,
        )
        st.image(str(_asset()), width=90)
        if st.button("Start a new conversation", type="primary"):
            _new_conversation(repository, user_id)
            st.rerun()
        st.stop()

    messages = st.session_state.get("messages", [])
    if not messages:
        st.markdown(
            '<div class="welcome-card"><h3>What would you like to find?</h3>'
            '<p>Ask a question about the selected documents. I’ll include source references with the answer.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        prompt_columns = st.columns(3)
        for column, prompt in zip(
            prompt_columns,
            ("Summarize this document.", "Find important dates and deadlines.", "What are the key points?"),
        ):
            if column.button(prompt, disabled=not selected_ids, use_container_width=True):
                st.session_state["suggested_question"] = prompt
    _render_messages(messages)
    typed_question = st.chat_input(
        "Ask a question about your selected documents…",
        disabled=not selected_ids,
    )
    question = st.session_state.pop("suggested_question", None) or typed_question
    if not selected_ids:
        st.info("Select at least one document in the sidebar before asking a question.")
    if question:
        if not question.strip():
            st.warning("Enter a question first.")
            st.stop()
        try:
            with st.spinner("Finding relevant passages and preparing an answer…"):
                chunks = storage.selected_chunks(user_id, selected_ids)
                history = [
                    {"role": item["role"], "content": item["content"]}
                    for item in messages[-settings.max_chat_history_pairs * 2 :]
                ]
                client = GeminiClient(settings)
                limiter = UsageLimiter(repository)
                result = answer_question(
                    question,
                    chunks,
                    client=client,
                    settings=settings,
                    history=history,
                    reserve_usage=lambda: limiter.reserve(
                        user_id,
                        settings.max_questions_per_user_per_day,
                        settings.max_questions_global_per_day,
                    ),
                )
                enriched = []
                for citation in result.citations:
                    source = next(
                        (chunk for chunk in result.evidence if chunk.document_id == citation["document_id"]
                         and chunk.chunk_index == citation["chunk_index"]),
                        None,
                    )
                    enriched.append({**citation, "excerpt": source.content if source else ""})
                repository.add_message(user_id, current_id, "user", question.strip())
                repository.add_message(user_id, current_id, "assistant", result.answer, enriched)
            st.session_state["messages"] = repository.get_messages(user_id, current_id)
            st.rerun()
        except (GeminiError, UsageError, PermissionError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Your question could not be completed. Please try again.")


def main() -> None:
    try:
        settings, repository, auth, storage = _services()
    except (ConfigurationError, ValueError) as exc:
        st.title("PinkyDocs AI")
        st.error(str(exc))
        st.info("Configure these values in a local .env file or Streamlit Community Cloud secrets.")
        st.stop()
    if not st.session_state.get("user_id"):
        _login_screen(auth)
    else:
        _render_authenticated(settings, repository, storage)


if __name__ == "__main__":
    main()
