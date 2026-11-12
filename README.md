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

## Quick start

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.13.4 or newer
   (`uv --version` to check, `uv self update` to upgrade). Older versions still trust the
   eMudhra / emSign certificates whose keys were exposed in October 2026.
2. In **Claude Code**:

   ```
   /plugin marketplace add GGaryyy/POBG
   /plugin install pobg@pobg
   ```

3. Start a new conversation and ask a question. The first start takes a little longer while uv
   sets up Python and about 40 packages.

**Other AI apps** (Claude Desktop, Cursor, VS Code, Gemini CLI, Codex CLI …): clone this repo and
add it as a local MCP server; [docs/clients.md](docs/clients.md) has the setup for each one and
five questions to check it works. ChatGPT is not supported: it only connects to online MCP
servers, and POBG runs on your computer.

## What you can ask

- "What does Leap Slam cost at level 10, and which supports work with it?" / 「躍擊 10 等的消耗是多少？」
- "Which passives give attack speed?" / 「哪些天賦有攻擊速度？」
- "Explain Critical Hits." / 「解釋暴擊」
- "How many passive points does a Witch need to reach Blood Magic and Resolute Technique?"
- "What modifiers can a bow roll, and what are the attack speed tiers?" / 「弓能出哪些詞綴？」
- "What does Quill Rain do?" / 「驟雨之弦有什麼詞綴？」
- "Give me a level 90 lightning Invoker build with full gear and a PoB code." /
  「給我一個 90 級閃電祈靈者流派，包含完整裝備以及 PoB 匯入碼」

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

| Command (Claude Code) | What it does |
|---|---|
| `/pobg:status` | How old each part of the data is; on request, a check of whether poe2db changed |
| `/pobg:update <scope>` | Re-fetches one part of the data after a patch, e.g. `/pobg:update skill_gems` |
| `/pobg:update-pob <folder>` | Updates your Path of Building (PoE2, alone or in a PoeCharm2 folder) into a new folder next to the old one |
| `/pobg:poe2-advisor` | The build instructions Claude Code follows; applied automatically |

In other AI apps `status` and `update` appear as prompts of the `pobg` server. Scopes, request
counts and details: [docs/data.md](docs/data.md#commands).

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
| [docs/flow/system_flow.md](docs/flow/system_flow.md) | System and data flow diagrams |
| [ROADMAP.md](ROADMAP.md), [CHANGELOG](docs/changelog/CHANGELOG.md) | What is next, what changed |
