# Screenshot Guide

Commands to run and settings to use when capturing screenshots for the README.

## Terminal Settings

- Width: 220 columns
- Height: 50 rows
- Font size: 14pt
- Font: JetBrains Mono or SF Mono
- Theme: Dark background (Catppuccin Mocha or similar dark scheme works well)
- Padding: 8px inner padding if your terminal supports it

## Capture Tool (macOS)

[Warp](https://www.warp.dev) has a built-in screenshot export. Alternatively use [iTerm2](https://iterm2.com) with `Cmd+Shift+4` or the [Ghostty](https://ghostty.org) terminal.

For automated capture consider [vhs](https://github.com/charmbracelet/vhs) (generates GIFs from a tape file).

## Commands to Capture

Run each command from the repo root after `pip install -e ".[dev]"`.

### Status

```
$ opencobalt status
```

Captures: Python version, Ollama status, ledger event count, docs presence, safety scan result, health bar.

### Route (two examples)

```
$ opencobalt route "design the event spine architecture"
$ opencobalt route "summarize this log file"
```

Captures: score table across all tools, recommended tool highlighted, reasoning line.

### Context

```
$ opencobalt context
```

Captures: file count, token estimate.

### Verify

```
$ opencobalt verify
```

Captures: pytest pass/fail, public-check pass/fail, summary line.

## File Naming

Place screenshots in `assets/screenshots/`:

- `status.png`
- `route.png`
- `context.png`
- `verify.png`

The `.gitignore` excludes PNG files from `assets/screenshots/` so screenshots are not committed to the repo.

## Notes

- Sanitize any output that includes your local home directory path before sharing.
- Run `opencobalt context` before `opencobalt status` so the context line shows as present.
- Run `opencobalt log --summary "test entry"` first if you want the ledger to show a non-zero event count.
