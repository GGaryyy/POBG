# System Flow

Updated 2026-11-12 (0.9.0: Path of Building codes and the PoB updater; 0.8.0: gear data).

## System flow

```mermaid
flowchart LR
    subgraph Source
        P[poe2db.tw /us/ + /tw/]
        H[cdn.poe2db.tw hover snippets]
        N[poe.ninja]
        POB[PoB2 tree.json 0_5]
        TD[poe2db tree data 4.5, us + tw JSON]
    end

    subgraph Catalog["src/catalog"]
        SPEC[poe2db_sources.json]
        PROBE[probe.py]
        EI[entity_index.py]
    end

    subgraph Scrapers["src/scrapers + ladder fetcher"]
        CG[collect_gems.py]
        PT[collect_passives.py]
        GL[collect_glossary.py]
        PN[fetch_poe_ninja_builds.py]
        CI[collect_items.py]
    end

    subgraph Data["data/"]
        GEM[(gem *_Detail / *_Listing / gemcutting)]
        PAS[(passive_nodes / passive_edges / classes.json)]
        COM[(poe_ninja_builds)]
        ITM[(items/bases, uniques, modifiers, classes.json)]
        IDX[(catalog/entity_index.jsonl)]
        KW[(kg/keywords.jsonl)]
        ST[(kg/passive_stats.jsonl)]
    end

    subgraph Index["indexes/ (git-ignored)"]
        KG[(knowledge_graph.json, rebuilt in memory when missing)]
    end

    subgraph App["src/tools"]
        LK[lookup.py + items.py]
        BT[build_tools.py + pathing.py]
        MT[maintenance.py: status + scoped update]
        MCP[MCP server pobg: 18 tools + build_guide / status / update prompts]
        PE[pob_export.py: XML + zlib + base64 build code]
        PU[pob_update.py: CLI, PoB release into a new folder]
    end

    subgraph Clients
        CC[Claude Code plugin + poe2-advisor skill]
        OC[Claude Desktop, Cursor, VS Code, Gemini CLI, Codex CLI, any stdio client]
    end

    SPEC --> PROBE --> P
    SPEC --> CG --> P
    CG --> GEM
    POB --> PT
    P -->|listing cards en + zh-TW| PT
    TD -->|zh-TW names + stat lines by node id, class names| PT
    PT --> PAS
    P -->|keyword links| GL
    H --> GL --> KW
    PAS --> SS[kg/stats.py] --> ST
    N --> PN --> COM
    P -->|57 item class pages en + zh-TW, embedded ModsView JSON| CI --> ITM
    ITM --> EI
    ITM --> LK
    GEM --> EI
    PAS --> EI
    P -->|/tw/ listing names| EI
    EI --> IDX
    GEM --> KGB[kg/build_graph.py]
    PAS --> KGB
    KW --> KGB
    ST --> KGB
    KGB --> KG
    IDX --> LK
    KG --> LK
    KW --> LK
    ST --> LK
    LK --> MCP
    LK --> BT
    COM -->|class, main skill, rank only| BT
    BT --> MCP
    BT -->|export_pob: class ids, route, gem ids| PE
    PE -->|code, no file| MCP
    MT --> MCP
    MT -->|one scope per call| CG
    MT -->|passives scope| PT
    MT -->|rebuild| EI
    MCP -->|uv run, stdio| CC
    MCP -->|uv run, stdio| OC
    CC -->|/pobg:update-pob, uv run, after the user agrees| PU
    PU -->|GitHub release + SHA-256, PoeCharm2 commit| PBF[(user's Path of Building, new folder)]
```

## Data flow (gem collection)

```mermaid
flowchart TD
    A[listing page /us/Skill_Gems] -->|parse_listing| B[rows: slug, name, tier, tag_slugs, colour]
    B -->|one request per slug, 0.8 s delay| C[detail page /us/slug]
    C -->|parse_detail: GemPopup index 0 + Level Effect + attributes| D[record]
    B -->|merge tag_slugs, colour| D
    D --> E{validate: count >= expect_min, <=2% skipped, schema}
    E -->|ok| F[(data/<kind>/*_Detail.jsonl)]
    E -->|fail| G[abort, nothing overwritten]
    F --> H[entity_index build]
    T[/tw/ listing pages cached in output/cache/tw/] --> H
    H --> I[(data/catalog/entity_index.jsonl)]
```

## Lookup flow (entity index)

```
query "躍擊" ──make_aliases──▶ ["躍擊"] ──exact alias──▶ Leap_Slam (skill_gem)
                                                   ├─ url_en  https://poe2db.tw/us/Leap_Slam
                                                   ├─ url_zh_tw https://poe2db.tw/tw/Leap_Slam
                                                   └─ record() → full JSON from data/skill_gems/Skill_Gems_Detail.jsonl
```

## Tool flow

```mermaid
sequenceDiagram
    participant AI as AI client
    participant M as MCP server pobg
    participant L as LookupService
    participant D as data/ + knowledge graph
    participant W as poe2db (only refresh_gem)
    AI->>M: lookup_entity("躍擊")
    M->>L: lookup_entity
    L->>D: entity index (exact → prefix → substring)
    L-->>AI: Leap_Slam + url_en / url_zh_tw
    AI->>M: get_gem("Leap_Slam")
    L->>D: record + keywords + SUPPORTS edges
    L-->>AI: record, glossary terms, supports, sources (fetched_at)
    AI->>M: passives_with_stat("攻擊速度")
    L->>D: stat index (zh template → family)
    L-->>AI: nodes with poe2db page first, small nodes summarised (PoB2 source)
    AI->>M: refresh_gem("Leap_Slam")
    L->>W: GET /us/Leap_Slam
    L-->>AI: changed_fields + updated record
```

## Cited build flow

The model searches freely, but only names that `verify_build` finds by exact match (slug,
English or Traditional Chinese name, passive node id) may appear in the answer. The source list
is rendered by code, not by the model. Names that were removed are echoed inside code spans, so
nothing the caller typed can render as a link or as HTML. Class and ascendancy start nodes do
not verify as passives.

```mermaid
sequenceDiagram
    participant U as Player
    participant AI as Model (skill, build_guide prompt or build_workflow tool)
    participant M as MCP server pobg
    participant B as BuildTools
    participant D as data/ + knowledge graph
    U->>AI: "fire slam warrior build"
    AI->>M: reference_builds(class, main skill)   (optional)
    B->>D: poe.ninja snapshot (whitelisted fields, no character names)
    B-->>AI: counts, common gems / keystones, source_markdown
    AI->>M: gems_by / supports_for / passives_with_stat / get_gem
    AI->>M: verify_build(gems, passives, lang)
    B->>D: exact match per name
    B-->>AI: verified facts (cite n) + unverified (reason, suggestions) + sources_markdown
    AI->>M: verify_build(final list)   (at most two rounds)
    AI->>M: path_to(class, verified passives)
    B->>D: passive tree neighbours, stat index, classes.json (point limits)
    B-->>AI: ordered route, points vs limits, stat totals, per-target cost
    AI-->>U: build written from the verified facts + sources_markdown
```

## Passive pathing

```mermaid
flowchart TD
    IN[class or ascendancy + target names] --> R[resolve class via classes.json, targets by exact match]
    R -->|unknown names| UV[unverified, with suggestions]
    R --> SP{target in an ascendancy tree?}
    SP -->|no| MAIN[main tree: no ascendancy nodes, no nodes locked to another ascendancy]
    SP -->|yes| ASC[that ascendancy's tree, from its start node]
    MAIN --> G[attach the nearest target first]
    ASC --> G
    G --> K[key-path exchange: replace a stretch of travel nodes when a shorter link exists]
    K --> O[allocation order = breadth-first from the start]
    O --> OUT[path, points vs 123 / 8, stat totals, points_alone / added_points, unreachable, sources]
```

## Data commands (status and update)

`update` always names one scope. Gem scopes are capped per call and repeated until nothing is
left; a gem that was selected but not fetched yet keeps its old listing row, so the next call
selects it again.

```mermaid
flowchart TD
    U[update command: scope + optional names / older than N days] --> V{scope valid?}
    V -->|no scope, all, unknown| R[refuse, list the scopes, no request]
    V -->|glossary| GL1[listing pages, a few gem pages, then hover snippets: at most 100 requests per call, kept in a run cache]
    GL1 -->|not finished| U
    GL1 -->|all fetched and at least 90 % of the known terms reached| GLW[merge with the old entries and write]
    V -->|items| IT1[item class pages, all or the named classes: at most 20 per call, kept in a run cache]
    IT1 -->|not finished| U
    IT1 --> IG{every page parsed, counts and Chinese names ok?}
    IG -->|no| A
    IG -->|yes| IW[write bases, uniques, modifiers; named classes are merged into the stored data]
    V -->|ladder| LD[poe.ninja: index, result pages, dictionaries, at most 14 requests]
    LD --> LG{at least 100 characters, most with class and skill?}
    LG -->|no| A
    LG -->|yes| LW[write the snapshot without names]
    V -->|skill_gems / spirit_gems / support_gems| L[fetch the listing page]
    L --> S[select: requested, new, listing changed, broken, stale]
    S -->|dry run| D[report what would be fetched, write nothing]
    S -->|at most max_gems| F[fetch detail pages, 0.8 s apart]
    F --> G{parse quality and counts ok?}
    G -->|no| A[abort, nothing written]
    G -->|yes| W[write detail + listing files]
    V -->|passives| P[fetch tree.json, 2 tree data files, 4 listing pages]
    P --> PG{tree and stat lines validate?}
    PG -->|no| A
    PG -->|yes| PW[write nodes, edges, classes, stat index]
    W --> I[rebuild entity index, Chinese names reused; rebuild graph file if present]
    PW --> I
    GLW --> I
    IW --> I
    LW --> RL
    I --> RL[server reloads its data; result says how many gems are left]
    RL -->|left > 0| U
```

`status` reads the local files only. With the online check it runs the catalog probe (about 19
requests) and reports pages that no longer parse and newer passive tree versions.
