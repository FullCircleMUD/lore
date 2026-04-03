# FullCircleMUD — World Lore

Embedded world knowledge for NPC intelligence. YAML files in this repo are imported into the game's `LoreMemory` database, where they're embedded and retrieved semantically at runtime to give NPCs dynamic awareness of the world.

See `design/LORE_MEMORY.md` in the design repo for the full system architecture.

---

## How It Works

NPCs with `llm_use_lore=True` dynamically retrieve relevant lore at conversation time. When a player asks a bartender about the Shadow War, the system embeds the question, searches the lore database filtered by the NPC's scope tags, and injects the most relevant entries into the LLM prompt. The NPC's personality determines how they deliver the information.

Different NPCs access different lore based on their **scope tags**:
- **Continental** lore is available to every NPC (common knowledge)
- **Regional** lore is available to NPCs in that zone (e.g. Millholm history for Millholm NPCs)
- **Local** lore is available to NPCs in that district (e.g. farm knowledge for farm NPCs)
- **Faction** lore is available to NPCs tagged with that faction (e.g. Mages Guild secrets for guild members)

---

## Directory Structure

```
continental.yaml              # world-wide common knowledge
millholm/
    regional.yaml             # Millholm zone-level lore
    millholm_town.yaml        # town district local knowledge
    millholm_farms.yaml       # farms district local knowledge
    ...
factions/
    mages_guild.yaml          # Mages Guild faction lore
    thieves_guild.yaml        # Thieves Guild faction lore
    temple.yaml               # Temple/Cleric faction lore
    warriors_guild.yaml       # Warriors Guild faction lore
```

---

## YAML Format

Each file contains a `source` identifier and a list of entries:

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

**Required fields per entry:**
- `title` — human-readable label (also used as the idempotent key with `source`)
- `scope_level` — one of: `continental`, `regional`, `local`, `faction`
- `scope_tags` — list of tags that determine who can access this entry
  - Continental entries use `[]` (empty — everyone gets them)
  - Regional entries use zone tags, e.g. `["millholm"]`
  - Local entries use district tags, e.g. `["millholm_town"]`
  - Faction entries use faction tags, e.g. `["mages_guild"]`
- `content` — the lore text (paragraph-length, focused on one topic)

---

## Importing Lore

From the game directory (`FCM/src/game/`), with the venv activated:

```bash
# Import all YAML files from this repo
evennia lore_import

# Import a specific file
evennia lore_import --file millholm/regional.yaml

# Preview what would happen without making changes
evennia lore_import --dry-run

# Override the lore directory path
evennia lore_import --lore-dir /path/to/lore
```

The default lore directory is auto-detected as `FCM/lore/` relative to the game directory.

**The import is idempotent:**
- New entries are created and embedded
- Entries with changed content are updated and re-embedded
- Unchanged entries are skipped (no wasted API calls)

The game server does not need to be running. After import, all NPCs with `llm_use_lore=True` immediately have access to the new knowledge — no restart required.

---

## Writing Good Lore Entries

Each entry should be **focused and self-contained** — one topic per entry, roughly paragraph-length (3-6 sentences). This matters for embedding quality:

- **Too short** ("Millholm is a town") — weak embedding, matches too many queries
- **Too long** (entire history in one entry) — relevant details buried in noise
- **Right size** — a paragraph covering one specific topic, place, person, or event

Write as factual knowledge, not as narrative prose. The NPC's personality template determines how they deliver the information — a bartender turns it into gossip, a scholar turns it into a lecture. The lore entry just provides the facts.

---

## Scope Tags Reference

Tags correspond to Evennia room tags and NPC faction tags set in the game code:

| Tag | Category | Set On | Who Gets This Lore |
|---|---|---|---|
| `millholm` | zone | Rooms | All NPCs in Millholm zone |
| `millholm_town` | district | Rooms | NPCs in town centre |
| `millholm_farms` | district | Rooms | NPCs on the farms |
| `millholm_woods` | district | Rooms | NPCs in the woods |
| `millholm_southern` | district | Rooms | NPCs in southern district |
| `millholm_sewers` | district | Rooms | NPCs in the sewers |
| `millholm_cemetery` | district | Rooms | NPCs in the cemetery |
| `mages_guild` | faction | NPCs | Mages Guild members |
| `thieves_guild` | faction | NPCs | Thieves Guild members |
| `temple` | faction | NPCs | Temple/Cleric members |
| `warriors_guild` | faction | NPCs | Warriors Guild members |

Geographic tags (zone, district) are inherited from the NPC's room automatically. Faction tags are set explicitly on the NPC during spawning.
