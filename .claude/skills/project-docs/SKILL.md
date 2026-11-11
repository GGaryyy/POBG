---
name: project-docs
description: This skill should be used when creating or updating this project's documentation — the changelog, issue logs, README, client guide, or flow/workflow docs — typically after implementing or changing code.
---

# Project Documentation

## docs/ layout

```
docs/
├── flow/
│   └── system_flow.md   # System flow + data flow diagrams (Mermaid) with description
├── clients.md           # How to connect each MCP client (see README & clients below)
├── workflow/
│   └── workflow.md      # Current development workflow and processes
├── changelog/
│   └── CHANGELOG.md     # Keep a Changelog format
├── issues/
│   └── ISSUE_NNN.md     # One file per issue (NNN = sequential number)
└── reports/             # Test / security / code-review reports (see testing-and-reports skill)
```

## Changelog — `docs/changelog/CHANGELOG.md`
- Follow the [Keep a Changelog](https://keepachangelog.com/) format strictly. Categories: Added, Changed, Deprecated, Removed, Fixed, Security.
- Semantic versioning `[MAJOR.MINOR.PATCH]` with date `YYYY-MM-DD`.
- Every code change gets an entry, added immediately after implementation. Maintain the file manually — it does not depend on git.

## Issue log — `docs/issues/ISSUE_NNN.md`
- Create one when a bug or problem is encountered during development.
- Required sections: **Problem** (what happened), **Cause** (root cause analysis), **Solution** (how it was fixed), **Prevention** (how to avoid recurrence).
- Link the issue number in the related changelog entry when applicable.

## README & clients
- `README.md` (project root): the project's **purpose** and **use cases** — what problem it solves, who/when it is for, and how to get started quickly.
- `README.zh-TW.md`: the Traditional Chinese version of the README; update both together.
- `docs/clients.md`: **how to connect** — one section per MCP client (config file, launcher command, requirements), each labelled tested or not tested, and how to check that it works.

## Flow & workflow docs
- `docs/flow/system_flow.md`: both a **system flow diagram** (component interactions and call relationships) and a **data flow diagram** (input → processing → output/storage). Update whenever the system design or data flow changes.
- `docs/workflow/workflow.md`: development process, build steps, deploy steps, environment-specific notes. Update when the workflow changes.
- All diagrams in this project are **Mermaid** — never screenshots or non-editable image files.
