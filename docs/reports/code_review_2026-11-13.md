# Code Review — 2026-11-13 (0.11.0, Claude Desktop installer)

One pass by the `reviewer` agent on the uncommitted installer, then fixes by the main session. Verdict of
the pass: **Needs Revision** (one High, six Medium, the rest Low or Info). No Critical finding, no security
finding: in every case tried, nothing from the config other than the `pobg` command reached stdout or stderr.
The fixes were checked by the main session with a test per finding and by the runs in
`test_report_2026-11-13.md`, not by a second review.

## Scope

`src/tools/install_desktop.py` (new), `install_claude_desktop.bat` (new), `tests/unit/test_install_desktop.py`
(new), `.gitattributes`, against `docs/plan_desktop_install.md`. The reviewer worked in temporary folders and
did not open the user's real config.

## Findings and resolutions

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | High | `Path.resolve()` on uv followed links to a versioned folder (Homebrew `Cellar/uv/0.x.y`, scoop `apps\uv\0.x.y`), which an upgrade removes; a mise shim resolved to `mise` itself | The path is made absolute, not resolved; when PATH reaches the same file by another path, that stable path is written |
| 2 | Medium | Only `OSError` was caught while writing: an unencodable value gave a traceback and left a `.tmp` file and an unreported backup | The text is built and encoded before anything is written; the temporary file and the backup are removed on any failure |
| 3 | Medium | A huge number or very deep nesting in the config raised outside the caught errors | `ValueError` and `RecursionError` are refusals with the "left unchanged" message |
| 4 | Medium | `Infinity` / `NaN` were read and written back, after which Claude Desktop could not parse its config | Refused on read |
| 5 | Medium | A linked config was replaced by a regular file with mode 0600 | The link's target is the file replaced; its mode is copied |
| 6 | Medium | Claude Desktop rewrites its config while running and could silently undo the change | Docs and the `.bat` say to quit it first; the file's size and time are compared before the replace and a change is refused |
| 7 | Medium | A relative `--config` was printed relative | Made absolute; a folder is accepted and completed with the file name |
| 8 | Low | `cd /d` fails on UNC paths | The `.bat` passes the folder to `uv run --directory` and does not change folder |
| 9 | Low | The first existing folder won, even when another place held the config | The place that holds a file wins; two files ask for `--config` |
| 10 | Low | `--config <folder>` gave a misleading error | Completed with the file name |
| 11 | Low | `"mcpServers": null` refused | Read as none registered |
| 12 | Low | A failed write left its backup | The backup is taken after the new file is written and removed when the replace fails |
| 13 | Low | Non-ASCII paths could not be printed on some console code pages | Output is ASCII-escaped JSON |
| 14 | Low | An injected environment without PATH fell back to the real one | No fall-back |
| 15 | Low | The `.bat` lost the exit code | Returned after the pause |
| 16 | Info | The user's extra keys moved in front of `command` | The entry keeps its key order |
| 17, 18 | Info | `.bat` quoting, CRLF and conventions are fine; `ROOT` repeats `lookup.BASE_DIR` | Kept: the installer then needs none of the server's dependencies |

Found by the main session on the real machine, outside the review: an `env` on the existing entry would have
been dropped, and Windows' `uv.EXE` spelling made an identical entry look changed. Both fixed with tests.

## Test-quality audit

The reviewer listed what the first 24 tests would not catch; each item now has a test (43 in all): the link
behind uv, the errors outside `OSError`, `Infinity`, a linked config and its mode, a relative or folder
`--config`, a `pobg` that is not an object, backup name collisions, several config locations, the leftover
backup on a failed write, and the `--remove` output with an `env`. The `.bat` has no automated test; it was
run through `cmd.exe` in check mode.

## Notes

- Backups are kept without a limit and hold whatever the config held, including other servers' secrets, with
  the same file mode. The user deletes them when they are no longer wanted.
- With `uv run --directory`, a relative `--config` given to the `.bat` is read against the POBG folder.
- The size-and-time comparison narrows, but cannot close, the window in which a running Claude Desktop writes
  its config; quitting it first is the instruction.
- The Microsoft Store location is matched by `Packages\*Claude*\LocalCache\Roaming\Claude`; the exact package
  name was not verified on a machine with that build.
