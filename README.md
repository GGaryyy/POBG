# POBG — Path of Exile 2 data and build tools for AI assistants

**English** | [繁體中文](README.zh-TW.md)

Ask your AI assistant about **Path of Exile 2** (in English or Traditional Chinese) and get
answers taken from real game data, with a link to where each fact came from and the date it
was fetched. Ask for a build
and you get skills, passives and gear that have each been checked against that data, plus a
[Path of Building](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) code to
paste into PoB and see the numbers.

POBG is an unofficial [Model Context Protocol](https://modelcontextprotocol.io) server and
Claude Code plugin. Its data is a local copy of [poe2db.tw](https://poe2db.tw), the
[PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) passive
tree and a [poe.ninja](https://poe.ninja/poe2/builds) ladder snapshot. Not affiliated with
Grinding Gear Games, poe2db.tw, PathOfBuilding or poe.ninja.

POBG only stands on the shoulders of giants: without the data that poe2db.tw, the Path of
Building community and poe.ninja have collected and published over the years, this project would
not exist. Thank you.

## Quick start

POBG runs on your own computer. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
first; it must be version **0.13.4 or newer** (`uv --version` to check, `uv self update` to upgrade).

**We recommend Claude Code or Codex.** In both, POBG installs as a plugin: the plugin starts the MCP
server on your computer (the tools) and brings the build instructions and the `pobg` commands. Ask
questions in plain words; use a `pobg` command to check or update the data. These are the setups
that produced complete builds in our tests.

**On Windows, use WSL.** Both were installed and tested inside WSL (Ubuntu), with uv installed there
as well. For Claude Code on Windows we recommend WSL. Codex CLI in PowerShell or cmd was
not tested, so we cannot say how it behaves there. macOS and Linux need nothing extra.

### Claude Code (recommended)

Type these two lines inside Claude Code:

```
/plugin marketplace add GGaryyy/POBG
/plugin install pobg@pobg
```

Start a new conversation and ask a question. The first start takes a little longer while uv sets up
Python and about 40 packages. Commands start with `/pobg:` (for example `/pobg:status`; see [Commands](#commands)).

### Codex CLI (recommended)

Run these two lines in a terminal (not inside a Codex chat):

```
codex plugin marketplace add GGaryyy/POBG
codex plugin add pobg@pobg
```

Start `codex` and ask a question; the first start takes a little longer, as in Claude Code. Commands
start with `$pobg:` (for example `$pobg:status`; typing `$pobg` lists them). When you ask for a Path of
Building code, **take it from the file Codex saves**: a long code retyped into the terminal can come out
wrong (tested 2026-11-13).

### Other AI apps

Claude Desktop, the ChatGPT desktop app, Cursor, VS Code, Gemini CLI … can run POBG as a local MCP
server too, with more steps, and we have tested them less: [docs/clients.md](docs/clients.md) has the
setup for each and what was tried. Without the skills (the ChatGPT desktop app, for one) the tools
work but a build answer came out thinner. ChatGPT and Claude on the web are not supported: they only
connect to online MCP servers, and POBG runs on your computer.

## What you can ask

- "What does Leap Slam cost at level 10, and which supports work with it?"
- "Which passives give attack speed?"
- "Explain Critical Hits."
- "How many passive points does a Witch need to reach Blood Magic and Resolute Technique?"
- "What modifiers can a bow roll, and what are the attack speed tiers?"
- "What does Quill Rain do?"
- "Give me a level 90 lightning Invoker build with full gear and a PoB code."

You can ask in Traditional Chinese too; see the [繁體中文 README](README.zh-TW.md) for examples.

## What a build answer contains

The assistant builds from the data, not from what is popular, and checks every name before it
writes:

- **Skills and supports**, each with the reason from its gem record.
- **Passives**: the targets, the route to reach them and the points used out of 123 (+8
  ascendancy).
- **Gear**: a base or unique per slot, and for rares up to 3 prefixes and 3 suffixes to look
  for, in order of importance.
- **Attributes and Spirit**: what the build needs against what it has, and what to change when
  it falls short.
- **Compared with the ladder**: what this build shares with ladder characters on poe.ninja
  and where it differs.
- **Sources**: a list of poe2db links for everything above. Names that do not exist in the data
  are removed and listed.
- **A Path of Building code** (next section).

## Importing into Path of Building

Copy the code from the answer. In Path of Building (PoE2): **Import/Export Build** → paste it →
**Import**. First update PoB to its latest release (`/pobg:update-pob <your PoB folder>` does it
for you; see [docs/data.md](docs/data.md#updating-path-of-building)). The passive tree comes from
PoB's development branch and can be ahead of its latest release: an older PoB skips passives and
gems it does not know and may refuse the tree version or ascendancy.

**What the code holds:** class and ascendancy, the passive route, skill groups with their
supports, gear, and PoB Configuration options. Notes about the build are in PoB's **Notes** tab.

**Worked out from the data, not guessed by the AI:**

- Character level, from the points spent (123 points is level 100), or the level you asked for.
- Each skill gem's level: the highest that character level can use.
- Which attribute each attribute passive takes: what the gems and gear require first.
- Spirit: what the persistent skills reserve against quest rewards, a sceptre and Spirit on
  gear and passives, computed the way PoB does.

**Assumptions to know about:**

- **Gear values are an ideal.** Every modifier is at the top of its best tier (e.g. "+(100—119)
  to maximum Life" becomes "+119"). Real items roll lower; edit them in PoB's Items tab. Choosing
  a tier or value is planned for later. Quality, runes, soul cores, sockets and jewels are not
  included; without a weapon, attack skills show as disabled.
- **Configuration** is switched on only where the build itself gives a reason: a charge it
  gains, an ailment it inflicts, lightning hits that Shock … The answer lists each option with
  its reason. Charges count at their maximum; to try fewer, enter a number in "count if not
  maximum" in the Configuration tab.
- **Comparing with the ladder:** poe.ninja's PoB exports switch on a fixed set of states for
  every character, so a ladder character's damage can look higher for that reason alone. The
  notes name the states the ladder assumes that this build has no source for.

## Commands

POBG has four commands. Their names are the same in Claude Code and Codex; each app has its own sign
for calling one: `/` in Claude Code, `$` in Codex (typing `$pobg` there lists them). The full flow of
each one (what it calls, where it decides, when it writes) is drawn in
**[docs/flow/commands.md](docs/flow/commands.md)**.

| Command | Claude Code | Codex | What it does |
|---|---|---|---|
| status | `/pobg:status` | `$pobg:status` | Shows, per data set, how many records there are, when they were fetched and how old they are. After you agree, it also checks the live sites: did poe2db's pages change, is there a newer passive tree |
| update | `/pobg:update <scope> [names]` | `$pobg:update <scope> [names]` | Re-fetches **one** data set after a game patch. Shows what would be fetched first, then updates it |
| update-pob | `/pobg:update-pob <folder>` | `$pobg:update-pob <folder>` | Updates your Path of Building (PoE2, alone or inside a PoeCharm2 folder) to the latest release. Checks versions first; after you agree, downloads into a **new folder** next to the old one, which is never changed or deleted |
| poe2-advisor | `/pobg:poe2-advisor` | `$pobg:poe2-advisor` | The instructions followed to answer PoE2 questions and write builds. You do not run it yourself; it is applied automatically when you ask |

`update` always needs a scope; there is no "update everything":

| Scope | Updates |
|---|---|
| `skill_gems` | Skill gems |
| `spirit_gems` | Spirit gems (persistent skills) |
| `support_gems` | Support gems |
| `passives` | The passive tree, plus PoB's level table and Spirit quest rewards used in build codes |
| `items` | Gear bases, uniques and modifiers (also flasks, charms, jewels); add item class names to update only those |
| `glossary` | Glossary terms |
| `ninja` | The poe.ninja ladder snapshot (no character or account names are kept) |

Examples (in Codex write `$` instead of `/`):

```
/pobg:status
/pobg:update skill_gems
/pobg:update support_gems Fire Attunement, Brutality I
/pobg:update items Bows
/pobg:update-pob "D:\PoB\PoeCharm2"
```

Plain words work too, e.g. "update the skill gems older than 30 days". A balance patch that only
changes numbers does not change the gem listing page, so a plain update finds nothing; name the
gems from the patch notes, or ask for gems older than N days.

In other AI apps `status` and `update` are prompts of the `pobg` server (the "+" menu in Claude
Desktop, `/pobg.status` in VS Code, slash commands in Gemini CLI); `update-pob` is run from a
terminal there. Request counts per scope and more notes: [docs/data.md](docs/data.md#commands).

## Limits

- The data is a snapshot (gems 2026-11-10, items, glossary and ladder 2026-11-11). Balance
  patches change numbers; `/pobg:status` shows the age and `/pobg:update` refreshes it.
- POBG checks that every name exists and quotes its facts; it does not judge how strong a build
  is or calculate damage. PoB does the maths.
- Modifiers are random: the gear in an answer is a target to look for, not a promise.
- The passive route is a good one, not a proven shortest one; weapon-set passive points and
  jewels are not planned.
- The ladder comparison uses a sample of about 600 characters near the top of several rankings.
- Not covered: crafting, currency, spawn weights, endgame items, a few bases and meta gems
  ([details](docs/data.md#sources-and-scope-of-use)).

## Data sources and license

The **code** is released under the MIT License (`LICENSE`). The **data** in `data/` is not covered
by MIT:

- Path of Exile 2 content belongs to Grinding Gear Games.
- The poe2db.tw material is used under the terms poe2db states on its
  [General disclaimer](https://poe2db.tw/us/General_disclaimer) page (read 2026-11-11):
  "Wikis Content is available under CC BY-NC-SA 3.0 unless otherwise noted." That means
  attribution, non-commercial use, and sharing derived data under the same licence. Every
  record keeps its poe2db source URL as attribution.
- The passive tree and PoB's quest tables come from PathOfBuilding-PoE2 (MIT).
- The ladder snapshot comes from poe.ninja and stores no character or account names.

Data is fetched only when someone runs an update, with an identifying User-Agent and a pause
between requests; [docs/data.md](docs/data.md#sources-and-scope-of-use) lists every URL. If you
reuse the data, follow those terms rather than MIT. This project is not affiliated with or
endorsed by any of these parties. If you maintain one of these sites and want the project to
change how it uses your data, please open an issue.

## For developers

| Document | Contents |
|---|---|
| [docs/clients.md](docs/clients.md) | Setting up each MCP client, what was tested |
| [docs/tools.md](docs/tools.md) | The 18 MCP tools and prompts, what `export_pob` computes |
| [docs/data.md](docs/data.md) | Sources, update scopes, full crawl, development and tests |
| [docs/flow/commands.md](docs/flow/commands.md) | The full flow of the four commands |
| [docs/flow/system_flow.md](docs/flow/system_flow.md) | System and data flow diagrams |
| [ROADMAP.md](ROADMAP.md), [CHANGELOG](docs/changelog/CHANGELOG.md) | What is next, what changed |
