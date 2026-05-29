# DesignLab

**Status: planned. Interface documented, not yet implemented.**

DesignLab is a design intelligence module that brings the same verification-and-memory approach to UI generation that OpenCobalt applies to code. It aims to prevent the generic AI-assisted UI pattern -- the same purple gradient, the same rounded cards, the same "unlock your productivity" copy -- from appearing in projects built with AI tools.

## Planned Capabilities

### Design token generation
- Accept a project brief as input
- Generate a coherent color palette, type scale, and spacing system
- Produce a `tokens.ts` file for React/TypeScript projects
- Store the token set in the local memory spine for consistency across sessions

### Local style memory
- Record design decisions (palette, typography, motion rules) per project
- Recall previous decisions when generating new screens
- Flag when a new generation conflicts with established project DNA

### Anti-slop enforcement
- Check generated designs against the anti-slop checklist in DESIGN_SYSTEM.md
- Flag specific violations with file references
- Suggest concrete fixes, not vague guidelines

### Screenshot critique loop
- Run Playwright to capture screenshots of running UI
- Send screenshots to a vision model for critique (requires configured API)
- Produce structured feedback: what looks generic, what works, what to change
- Track critique history to show improvement over time

### Image generation adapter
- Accept design briefs and generate logo, icon, and illustration prompts
- Route prompt to configured image generation tool (DALL-E, Midjourney, local diffusion)
- Store generated assets with provenance notes

### Visual regression baseline
- Capture baseline screenshots on first run
- Compare subsequent screenshots to baseline
- Flag regressions before commits

## CLI Interface (Planned)

```bash
# Show current project brief
opencobalt design brief

# Generate design tokens from a description
opencobalt design tokens --description "dark terminal-native tool for developers"

# Run anti-slop check on screenshots
opencobalt design check --screenshots assets/screenshots/

# Critique a specific screenshot with vision model
opencobalt design critique assets/screenshots/status.png

# Generate image generation prompt for logo
opencobalt design logo-prompt --project opencobalt
```

## Implementation Priority

DesignLab is Phase 5 in the roadmap. It requires:
1. Stable UI foundation (Phase 4)
2. Context memory working well (Phase 2)
3. Optional API adapter (Phase 3)

The anti-slop checklist in DESIGN_SYSTEM.md is the first deliverable and is already available.
