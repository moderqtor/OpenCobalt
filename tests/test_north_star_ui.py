"""Source contracts for the north-star daily-use product surface."""

from pathlib import Path

APP = Path("ui/src/App.jsx").read_text()
COMPONENTS = Path("ui/src/components.jsx").read_text()
CSS = Path("ui/src/index.css").read_text()
API = Path("ui/src/api.js").read_text()


def test_primary_navigation_promotes_work_and_discloses_system():
    work = COMPONENTS[
        COMPONENTS.index("export const WORK_NAVIGATION") : COMPONENTS.index("export const CONTEXT_NAVIGATION")
    ]
    context = COMPONENTS[
        COMPONENTS.index("export const CONTEXT_NAVIGATION") : COMPONENTS.index("export const SYSTEM_NAVIGATION")
    ]
    system = COMPONENTS[
        COMPONENTS.index("export const SYSTEM_NAVIGATION") : COMPONENTS.index("export const NAVIGATION")
    ]
    assert '["chat", "Chat"' in work
    assert '["missions", "Missions"' in work
    assert '["memory", "Memory"' not in work
    assert '["memory", "Memory"' in context
    assert '["routes", "Routes"' not in work
    assert '["routes", "Routes"' not in context
    assert '["routes", "Routes"' in system
    assert '["ledger", "Ledger"' in system
    assert '["skills", "Skills"' in system
    assert '["providers", "Providers"' in system
    assert '["settings", "Settings"' in system
    assert 'className="nav-system"' in COMPONENTS
    assert "<summary>System</summary>" in COMPONENTS
    assert ">Context</p>" in COMPONENTS


def test_composer_keeps_automatic_primary_and_hides_advanced_controls():
    composer = APP[APP.index("return <form className=\"composer\"") : APP.index("const MESSAGE_STATUS")]
    assert 'placeholder="Ask OpenCobalt"' in composer
    assert "mode-switch" in composer
    assert "OpenCobalt will choose provider and model" in composer
    assert "SelectField label=\"Persona\"" in composer
    assert "SelectField label=\"Provider\"" in composer
    persona_index = composer.index("SelectField label=\"Persona\"")
    advanced_index = composer.index("id=\"composer-advanced\"")
    assert persona_index > advanced_index
    assert "Cognitive policy" not in composer
    assert "Attach a local repository" in composer


def test_chat_provenance_is_compact_and_avoids_receipt_ids():
    spine = COMPONENTS[COMPONENTS.index("export function RouteSpine") : COMPONENTS.index("export function RouteInspector")]
    assert "spine-primary" in spine
    assert "Open Mission" in spine
    assert "receipt integrity" not in spine.lower()
    assert "Inspect how OpenCobalt handled this response" in spine
    assert "event-strip" not in APP
    assert "inspector-summary" in COMPONENTS
    assert "Continue as Mission" in COMPONENTS
    assert "Receipt integrity passed" in COMPONENTS
    assert "does not prove the answer is factually true" in COMPONENTS
    assert "function userFacingReason" in COMPONENTS
    assert "Compare last two answers" in APP
    assert "Compare with previous" not in APP


def test_missions_connect_to_conversations_without_fake_autonomy():
    assert "Open conversation" in APP
    assert "opencobalt.focusMission" in APP
    assert "Needs a decision" in APP
    assert "In progress" in APP
    assert "Continue as Mission creates a durable planning record" in COMPONENTS
    assert "It does not execute the work." in COMPONENTS
    assert "Earlier planning records" in APP
    assert "isEarlierPlanningRecord" in APP
    assert "auto_plan_id" in APP


def test_repository_rename_navigation_and_memory_followup_contracts():
    assert "canonicalizeRepository" in API
    assert "repo-compact" in APP
    assert "repo-chip" in APP
    assert "Rename conversation" in APP
    assert "Rename conversation" in COMPONENTS
    assert "nav-reopen-inline" in APP
    assert 'onOpenNavigation={() => { setNavCollapsed(false); setNavOpen(true); }}' in APP
    assert "position: sticky" in CSS
    memory = APP[APP.index("function MemoryRecord") : APP.index("function LedgerPage")]
    assert '<option value="temporary">Temporary</option>' not in memory
    assert "memoryScopeLabel" in memory


def test_conversation_rail_titles_are_two_line_clamped_with_full_title_tooltips():
    rail = COMPONENTS[COMPONENTS.index("export function ConversationRail") : COMPONENTS.index("export const panelIcons")]
    assert 'title={conversation.title || "Untitled conversation"}' in rail
    assert "-webkit-line-clamp: 2" in CSS
    title_rule = CSS[CSS.index(".conversation-item b") : CSS.index(".conversation-item span")]
    assert "white-space: nowrap" not in title_rule


def test_conversation_patch_client_exists():
    assert "updateConversation:" in API


def test_narrow_viewports_overlay_rail_and_navigation():
    assert 'useViewportFlag("(max-width: 1180px)")' in APP
    assert "@media (max-width: 1180px)" in CSS
    assert "@media (max-width: 1024px)" in CSS
    assert "@media (min-width: 1181px)" in CSS
    assert "inset: 0 auto 0 228px" in CSS
    assert ".conversation-list { display: grid" in CSS
