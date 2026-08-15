"""Source contracts for Chat rail daily-use behavior that has no JS test runner."""

from pathlib import Path

COMPONENTS = Path("ui/src/components.jsx").read_text()
APP = Path("ui/src/App.jsx").read_text()
CSS = Path("ui/src/index.css").read_text()
PERSIST = Path("ui/src/routingPersist.js").read_text()


def _function_body(source: str, signature: str, end_marker: str) -> str:
    start = source.index(signature)
    end = source.index(end_marker, start)
    return source[start:end]


def test_desktop_select_does_not_collapse_the_conversation_rail():
    assert "onClick={() => onSelect(conversationId)}" in COMPONENTS
    assert "setConversationOpen(false);" in APP
    assert "if (!isNarrow) setRailCollapsed(true);" in APP
    rail = COMPONENTS[COMPONENTS.index("export function ConversationRail") :]
    rail = rail[: rail.index("export const panelIcons")]
    assert "onClose?.()" in rail
    assert 'onClick={() => onSelect(conversationId)}' in rail
    assert "onClose" not in rail.split("onClick={() => onSelect(conversationId)}")[1].split("</button>")[0]


def test_new_conversation_ui_does_not_copy_active_chat_routing():
    create = _function_body(APP, "const createConversation = async (input = {}) => {", "const ensureConversation")
    ensure = _function_body(APP, "const ensureConversation = async () => {", "const persistConversationRouting")
    assert "updateConversationRouting" not in create
    assert "updateConversationRouting" not in ensure
    assert "routingPatchFromControls" not in create
    assert "routingPatchFromControls" not in ensure
    assert "created: true" in ensure
    persist = _function_body(APP, "const persistConversationRouting = (nextControls, conversationId) => {", "const updateControls")
    assert "write_seq: seq" in persist
    assert "Conversation routing was not saved" in persist
    assert "setNotice" in persist
    assert 'from "./routingPersist"' in APP
    assert "queued.generation !== generation" in PERSIST
    assert "createPerConversationWriteQueue" in PERSIST


def test_new_conversation_is_instant_without_title_or_repo_form():
    assert "id=\"conversation-create\"" not in COMPONENTS
    assert 'onClick={() => onCreate({})}' in COMPONENTS
    assert "Attach repository" in APP
    assert 'placeholder="Ask OpenCobalt"' in APP
    assert "Write a goal. OpenCobalt will choose how to handle it." in APP


def test_desktop_chat_layout_is_named_grid_not_stacked_panes():
    assert 'grid-template-areas: "rail chat"' in CSS
    assert "grid-template-columns: minmax(15rem, 17.5rem) minmax(0, 1fr)" in CSS
    assert ".chat-layout > .conversation-backdrop { display: none; }" in CSS
    assert ".conversation-rail {\n  grid-area: rail;" in CSS
    assert ".chat-main {" in CSS and "grid-area: chat;" in CSS
