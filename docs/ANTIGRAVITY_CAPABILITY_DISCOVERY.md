# Antigravity CLI Capability Discovery Report

This report presents a factual summary of the locally discovered capabilities of the Google Antigravity CLI (`agy`) runtime. It was generated on June 8, 2026, for the OpenCobalt integration.

## 1. Local Command Path
The `agy` executable is located at:
* Path: local user PATH entry discovered by `shutil.which("agy")`

## 2. Version Output
* Version: `1.0.6`

## 3. Help Output Summary
The main usage of the `agy` CLI displays the following flags and subcommands:

### Flags
* `--add-dir`: Add a directory to the workspace (repeatable) (default `[]`)
* `-c`, `--continue`: Continue the most recent conversation
* `--conversation`: Resume a previous conversation by ID
* `--dangerously-skip-permissions`: Auto-approve all tool permission requests without prompting
* `-i`, `--prompt-interactive`: Run an initial prompt interactively and continue the session
* `--log-file`: Override CLI log file path
* `--model`: Model for the current CLI session
* `-p`, `--print`: Run a single prompt non-interactively and print the response
* `--print-timeout`: Timeout for print mode wait (default `5m0s`)
* `--prompt`: Alias for `--print`
* `--sandbox`: Run in a sandbox with terminal restrictions enabled

### Subcommands
* `changelog`: Show changelog and release notes
* `help`: Show help for subcommands
* `install`: Configure environment paths and shell settings
* `models`: List available models
* `plugin`/`plugins`: Manage plugins (install, uninstall, list, enable, disable)
* `update`: Update CLI

## 4. Supported Commands and Slash Commands
The following features are discoverable via help pages and CLI release history:
* **Plugin Commands**: `list`, `import` (imports from `gemini` or `claude`), `install` (supports `plugin@marketplace`), `uninstall`, `enable`, `disable`, `validate`, and `link` (generates links to a marketplace).
* **Slash Commands**:
  * `/open`: Used for file opening
  * `/add-dir`: Add directory to workspace
  * `/resume`: Conversation picker
  * `/permissions`: Add, edit, or remove permission rules for config files directly inside the CLI
  * `/settings` / `/config` (with `/se` as an alias for `/settings`): Settings manager
  * `/diff`: Displays diff details
  * `/help`: Displays help info
  * `/model`: Configures model options
* **UI Shortcut**: `ctrl+r` opens the Artifact Review panel when confirming permissions or answering questions.

## 5. Non-Interactive Execution Support
* **Status**: Supported
* **Evidence**: Supported via `-p`, `--print`, `--prompt`, and `--print-timeout` flags. These flags run a single prompt non-interactively and output the response.

## 6. Model Selection Support
* **Status**: Supported
* **Evidence**: Supported via the `--model` flag. Additionally, the `models` subcommand lists available models, although in sandboxed or offline environments this subcommand may block or timeout.

## 7. Plugin and Extension Support
* **Status**: Supported
* **Evidence**: Supported via the `plugin` and `plugins` subcommands, allowing users to import, install, uninstall, enable, disable, and validate plugins.

## 8. Skills, Hooks, and Subagents Support
* **Status**: Referenced, protocol unknown
* **Evidence**:
  * Release notes mention "skill-derived slash commands from autocompletion suggestions".
  * Subagents are explicitly referenced in release notes ("Skipped subagent conversations from `/resume`").
  * Permissions for skills, hooks, and subagents are integrated into the permissions manager.
* **Unknown**: The command-line or IPC protocol for discovering or querying subagents is not known from `agy --help`.

## 9. Artifact Export and Import Support
* **Status**: Partially Exposed (UI-only)
* **Evidence**:
  * The Artifact Review panel is accessible in interactive mode via `ctrl+r`.
  * OpenCobalt has a static roadmap for command-line artifact tools (`opencobalt artifacts list/inspect/attach/verify`) but no direct CLI export/import commands are exposed on the `agy` command line.

## 10. Known Artifact Storage Locations
* **Location**: `~/.gemini/antigravity-cli/cache/`
* **Details**: Workspace-to-project mappings are stored in `~/.gemini/antigravity-cli/cache/projects.json`. Additional cache data, metadata, and logs are kept in `~/.gemini/antigravity-cli/cache/` instead of the local workspace.

## 11. Recommended OpenCobalt Adapter Fields
Based on local discoveries, the OpenCobalt configuration in [src/opencobalt/integrations/antigravity_integration.py](../src/opencobalt/integrations/antigravity_integration.py) should define:
```python
name = "google-antigravity"
display_name = "Google Antigravity CLI"
command = "agy"
vendor = "google"
kind = "agent_runtime"
status = "primary"
tier = "executive"
capabilities = ["agent-runtime", "interactive-cli", "artifact-workflows", "browser-workflows"]
```
Discovery logic in [discover_antigravity_runtime](../src/opencobalt/integrations/antigravity_integration.py) should continue to parse the help text of `agy` for `--print`, `--model`, `plugin`, and `--sandbox` flags to mark those capabilities dynamically.

## 12. Unknowns
* The specific command line syntax to trigger browser automation or capture screenshots.
* The exact schema of the SQLite database used by `agy` to track conversations (introduced in version 1.0.4).
* The protocol used by `agy` to discover or query subagents.

## 13. Security Concerns
* **Unrestricted Approvals**: The `--dangerously-skip-permissions` flag auto-approves all permission requests without user prompting. OpenCobalt must avoid passing this flag unless the user has explicitly authorized autonomous execution under safe constraints.
* **Sandbox Escapes**: The `--sandbox` flag runs the CLI with terminal restrictions enabled. It is recommended that OpenCobalt uses this flag for untrusted or worker-tier tasks if routed to `agy`.
* **Credential Exposure**: Any task routed to `agy` that handles credentials or environment configuration must be scrutinized because `agy` has direct terminal and file read/write permissions.

## 14. Suggested Next Integration Tests
* **Non-Interactive Print Test**: Add a test that verifies `agy --print "hello"` (mocked or with a short timeout) executes correctly.
* **Model Validation Test**: Test the behavior of `agy --model <model> --print "hello"` to ensure it handles model selection arguments properly.
* **Sandbox Enforcement Test**: Verify that the `--sandbox` flag propagates correctly during non-interactive runs.
* **Legacy Alias Warning Verification**: Ensure that invoking legacy aliases like `gemini-cli` generates a `DeprecationWarning` and resolves to the `google-antigravity` runtime as coded in [tests/test_antigravity_integration.py](../tests/test_antigravity_integration.py).
