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
    start = _function_body(APP, "const startConversation = () => {", "const ensureConversation")
    ensure = _function_body(APP, "const ensureConversation = async () => {", "const persistConversationRouting")
    send = _function_body(APP, "const send = async (content) => {", "const cancel = async")
    assert "api.createConversation" not in start
    assert "updateConversationRouting" not in start
    assert "routingPatchFromControls" not in start
    assert "defaultComposerControls(settingsRef.current)" in start
    assert "setDrafting(true)" in start
    assert "setDraftProjectPath(\"\")" in start
    assert "updateConversationRouting" in ensure
    assert "routingPatchFromControls(draftControls)" in ensure
    assert "write_seq: 1" in ensure
    assert "draftControls" in ensure
    assert "controlsRef.current" in ensure
    assert "project_path" in ensure
    assert "created: true" in ensure
    assert "setDrafting(false)" in ensure
    assert "ensured.created ? defaultComposerControls" not in send
    assert "const sendControls = { ...controlsRef.current };" in send
    assert "runGenerationRef.current === generation" in send
    persist = _function_body(APP, "const persistConversationRouting = (nextControls, conversationId) => {", "const updateControls")
    assert "write_seq: seq" in persist
    assert "Conversation routing was not saved" in persist
    assert "setNotice" in persist
    assert 'from "./routingPersist"' in APP
    assert "queued.generation !== generation" in PERSIST
    assert "createPerConversationWriteQueue" in PERSIST
    patch = _function_body(APP, "function routingPatchFromControls(controls) {", "function routingControlsEqual")
    assert "personaId" not in patch
    assert "cognitivePolicy" not in patch
    assert "persona_id" not in patch
    assert "cognitive_policy" not in patch


def test_draft_repository_stays_local_until_conversation_creation():
    start = _function_body(APP, "const startConversation = () => {", "const ensureConversation")
    ensure = _function_body(APP, "const ensureConversation = async () => {", "const persistConversationRouting")
    attach = _function_body(APP, "const attachRepository = async (event) => {", "const openMission")
    assert "setDraftProjectPath(path)" in attach
    assert "api.createConversation" not in attach
    assert "api.createConversation" not in start
    assert "payload.project_path = projectPath" in ensure
    assert "canAttachRepository" in APP
    assert "draftingRef.current" in APP
    assert "if (!draftingRef.current && !draftTransferRef.current)" in APP
    assert "attachedProjectPath" in APP
    assert "composerSession" in APP
    select = _function_body(APP, "const selectConversation = useCallback((conversationId) => {", "}, []);")
    assert "setDraftProjectPath(\"\")" in select
    assert "setDrafting(false)" in select


def test_new_conversation_is_instant_without_title_or_repo_form():
    assert "id=\"conversation-create\"" not in COMPONENTS
    assert 'onClick={() => onCreate({})}' in COMPONENTS
    assert "startConversation" in APP
    assert "Attach a local repository" in APP
    assert 'placeholder="Ask OpenCobalt"' in APP
    assert "Write a goal. OpenCobalt will choose how to handle it." in APP


def test_desktop_chat_layout_is_named_grid_not_stacked_panes():
    assert 'grid-template-areas: "rail chat"' in CSS
    assert "grid-template-columns: minmax(15rem, 17.5rem) minmax(0, 1fr)" in CSS
    assert ".chat-layout > .conversation-backdrop { display: none; }" in CSS
    assert ".conversation-rail {\n  grid-area: rail;" in CSS
    assert ".chat-main {" in CSS and "grid-area: chat;" in CSS
