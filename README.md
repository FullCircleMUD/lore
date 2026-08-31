# FullCircleMUD — World Lore

Embedded world knowledge for NPC intelligence. This repository is **content only**: YAML files, and a
manifest naming them. They are read into the game's lore table by the `lore import` command, embedded,
and retrieved semantically at runtime so NPCs can answer questions nobody hand-authored for them.

See `design/lore-memory.md` for the system architecture, and the
[evennia-ai-memory](https://github.com/FullCircleMUD/evennia-ai-memory) library for the code that reads
this repository.

---

## How it works

NPCs with lore enabled retrieve relevant entries at conversation time. When a player asks a bartender
about the Shadow War, the question is embedded, the lore is searched within the NPC's scope, and the
best matches are put into the prompt. The NPC's personality decides how it delivers them.

Which entries an NPC can reach is decided by **scope tags**:

- **Continental** lore has no tags — every NPC knows it.
- **Regional** lore is tagged with a zone, e.g. `millholm`.
- **Local** lore is tagged with a district, e.g. `millholm_town`.
- **Faction** lore is tagged with a faction, e.g. `mages_guild`.

An entry is reachable only when **every** tag it carries is one the NPC holds. So an entry tagged
`["millholm", "thieves_guild"]` reaches a guild member in Millholm and nobody else — not a Millholm
baker, and not a thief in another city.

---

## Layout

```
index.yaml                    # the manifest — names every content file
continental.yaml              # world-wide common knowledge
millholm/
    regional.yaml             # Millholm zone-level lore
    millholm_town.yaml        # town district
    raven_sage.yaml           # a location's local knowledge
factions/
    mages_guild.yaml
    thieves_guild.yaml
    temple.yaml
    warriors_guild.yaml
    merry_bandits.yaml
```

**`index.yaml` is the manifest, and it is what the repository consists of.** The importer reads the
paths it names; it does not go looking. A file that isn't listed is never imported, so add a new lore
file to the manifest in the same commit that adds the file. A file listed but missing stops the import
rather than passing quietly — that is deliberate, and it catches a deletion that forgot the list.

---

## YAML format

Each file carries a `source` identifier and a list of entries:

```yaml
source: "millholm/regional.yaml"
entries:
  - title: "Founding of Millholm"
    scope_level: regional
    scope_tags: ["millholm"]
    content: |
      Millholm was founded roughly four hundred years ago by four
      families from the eastern coast: the Stonefields, the
      Brightwaters, the Goldwheats, and the Ironhands. They followed
      the Old Trade Way westward until they found a crossroads with
      good soil and fresh water, and decided to settle.
```

Every entry needs all four fields:

- `title` — a human-readable label. With `source`, it identifies the entry, which is how a re-import
  knows an edit from a new entry.
- `scope_level` — `continental`, `regional`, `local` or `faction`. Descriptive; the tags decide access.
- `scope_tags` — the list deciding who can reach it. Empty means everyone.
- `content` — the lore text.

---

## Getting lore into the game

A superuser runs:

```
lore import
```

It reads this repository, validates all of it, and brings the lore table into line. New entries are
created, edited ones re-embedded, unchanged ones left alone, and **entries no longer in the YAML are
removed** — this repository is the source of truth, so the table mirrors it.

Nothing is written unless every entry validates. Adding lore is therefore safe to attempt: a mistake
refuses the run and reports what was wrong, rather than half-importing.

```
lore import dry
```

reports what would change and stops, which is worth doing before a large edit.

---

## Writing good lore entries

Each entry should be **focused and self-contained** — one topic, roughly paragraph-length. This matters
for embedding quality:

- **Too short** ("Millholm is a town") — weak embedding, matches too many questions.
- **Too long** (an entire history in one entry) — the relevant sentence is buried.
- **Right size** — a paragraph on one specific topic, place, person or event.

Write facts, not narration. The NPC's personality template decides the delivery: a bartender turns a
fact into gossip, a scholar into a lecture. The entry supplies only what is true.

---

## Scope tags in use

Tags match Evennia room tags and NPC faction tags set in the game.

| Tag | Category | Set on | Reaches |
|---|---|---|---|
| `millholm` | zone | Rooms | Every NPC in the Millholm zone |
| `millholm_town` | district | Rooms | NPCs in the town centre |
| `millholm_farms` | district | Rooms | NPCs on the farms |
| `millholm_woods` | district | Rooms | NPCs in the woods |
| `millholm_southern` | district | Rooms | NPCs in the southern district |
| `millholm_sewers` | district | Rooms | NPCs in the sewers |
| `millholm_cemetery` | district | Rooms | NPCs in the cemetery |
| `mages_guild` | faction | NPCs | Mages Guild members |
| `thieves_guild` | faction | NPCs | Thieves Guild members |
| `temple` | faction | NPCs | Temple and cleric members |
| `warriors_guild` | faction | NPCs | Warriors Guild members |

Geographic tags are inherited from the NPC's room. Faction tags are set on the NPC when it spawns.
