"""Source contracts for Chat rail daily-use behavior that has no JS test runner."""

from pathlib import Path

COMPONENTS = Path("ui/src/components.jsx").read_text()
APP = Path("ui/src/App.jsx").read_text()
CSS = Path("ui/src/index.css").read_text()


def _function_body(source: str, signature: str, end_marker: str) -> str:
    start = source.index(signature)
    end = source.index(end_marker, start)
    return source[start:end]


def test_desktop_select_does_not_collapse_the_conversation_rail():
    body = _function_body(COMPONENTS, "const select = (conversationId) => {", "const create = async")
    assert "onSelect(conversationId);" in body
    assert "onClose" not in body
    assert "setConversationOpen(false);" in APP
    assert "if (!isNarrow) setRailCollapsed(true);" in APP


def test_create_form_title_is_empty_with_placeholder_not_prefilled_text():
    assert 'useState({ title: "", project_path: "" })' in COMPONENTS
    assert 'placeholder="New conversation"' in COMPONENTS
    assert 'value={draft.title}' in COMPONENTS
    create_form = COMPONENTS[COMPONENTS.index("id=\"conversation-create\"") :]
    assert 'disabled={isCreating || !draft.title.trim()}' not in create_form


def test_desktop_chat_layout_is_named_grid_not_stacked_panes():
    assert 'grid-template-areas: "rail chat"' in CSS
    assert "grid-template-columns: minmax(15rem, 17.5rem) minmax(0, 1fr)" in CSS
    assert ".chat-layout > .conversation-backdrop { display: none; }" in CSS
    assert ".conversation-rail {\n  grid-area: rail;" in CSS
    assert ".chat-main {" in CSS and "grid-area: chat;" in CSS
