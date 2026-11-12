---
name: update-pob
description: Update a local Path of Building (PoE2) to the latest release, alone or inside a PoeCharm2 (中文化) folder, by downloading it into a new folder next to the old one. The user gives the folder.
argument-hint: <Path of Building or PoeCharm2 folder>
disable-model-invocation: true
---

# Update Path of Building

Folder: `$ARGUMENTS`

Build codes from `export_pob` need a Path of Building as new as the data; an older one skips the
passives and gems it does not know. This command updates the user's copy. It downloads into a
**new folder** next to the old one and never changes or deletes the old folder.

**No folder given:** ask for it and stop. It is the folder that holds `manifest.xml` (Path of
Building) or `PoeCharm3.exe` (PoeCharm2, with Path of Building inside it). Do not search the
disk for it.

The command runs from the plugin's folder. On Windows paths such as `G:\POB\poe2` work as
given; under WSL write them as `/mnt/g/POB/poe2`. Put the path in double quotes. If it contains
`"`, `` ` `` or `$`, do not run anything: ask the user to rename the folder or run the command
themselves.

1. Check (2 requests to GitHub, writes nothing):

   ```
   uv run --directory "${CLAUDE_PLUGIN_ROOT}" python -m src.tools.pob_update --dir "<folder>" --check
   ```

   Report `installed` and `latest`, and `note` when there is one. For a PoeCharm2 folder also
   report `poecharm_latest` and `poecharm_latest_date` (the commit that would be installed). When
   `up_to_date` is true, say so and stop. On `error`, show it and stop.
2. Tell the user what the update does and ask to go ahead:
   - downloads Path of Building `latest` from its GitHub release (about 380 MB) and checks it
     against the SHA-256 GitHub publishes; for a PoeCharm2 folder also the latest PoeCharm2
     (about 30 MB; it has no published checksum);
   - unpacks into a new folder next to the old one; the old folder stays as it is;
   - copies the saved builds (`Builds`) and PoeCharm2's language setting; not `Settings.xml`,
     which holds the account login, so the user signs in again.
3. Only after the user agrees, run it without `--check`. It can take several minutes, so give
   the command a 10-minute timeout (600000 ms) or run it in the background and wait for it;
   progress lines go to stderr, the result (JSON) to stdout:

   ```
   uv run --directory "${CLAUDE_PLUGIN_ROOT}" python -m src.tools.pob_update --dir "<folder>"
   ```

4. Report `new_folder`, `version`, `builds_copied`, `checksum` and `next`. On `error`, show it:
   nothing was kept and the old folder is unchanged. If the command was stopped before it
   finished, a `.pobg-update-…` work folder may be left next to the old one; the next run
   removes it after an hour, or the user can delete it.

Never delete the old folder; say the user can delete it once the new one works.
