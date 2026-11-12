---
name: status
description: Show what the local Path of Exile 2 data holds and how old it is (record counts, fetch dates, passive tree versions, ladder snapshot), and optionally check the live sites for changes. Use when the user asks whether the poe2db data is current, outdated or needs an update.
---

# POBG data status

1. Call `data_status`. For each data set show the number of records, when it was fetched, its
   age in days, and whether a command can update it (`update_scope`).
2. Point out what is old, including the ladder snapshot and its league.
3. Ask whether to check the live sites. Only when the user agrees, call `data_status` with
   `check_online: true` (about 19 requests to poe2db.tw and GitHub) and report `problems`:
   pages that no longer parse, or a newer passive tree version.
4. When something should be updated, name the command: `/pobg:update <scope>` with one of
   `skill_gems`, `spirit_gems`, `support_gems`, `passives`, `items`, `glossary`, `ninja`.

Do not call `update_data` from this skill.
