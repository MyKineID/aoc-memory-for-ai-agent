---
name: aoc-memory
description: "Use when saving or recalling cross-session agent memory via ACO pheromone trails."
version: 1.0.0
license: MIT
---

# AoC Memory (ACO-based)

## When to Use

Use when facts must survive across sessions but stay usage-dependent: work patterns, research findings, project state that lives from being accessed. Do not store knowledge that must be permanent here (identity, procedures, credentials); evaporation will eventually consume even reinforced trails that are rarely queried.

Memory layer with pheromone dynamics. State lives in `$ANT_MEMORY_DIR/trails.json` (default `~/.ant-memory/`), entries pruned by decay move to `archive.json` (soft delete). Engine: `python3 ant_memory.py`.

## Protocol

- Entry = {id, content, tags, tau, success, fail, created, last_access}
- Retrieval: `P = tau^alpha * eta^beta`, alpha=1 beta=2 (relevance dominates). eta is computed at read time: token overlap between query and (content+tags), scaled by the success/fail prior. No embeddings, so write content and tags using the exact keywords you will query with later.
- Evaporation: `tau *= (1-0.01)^idle_days`, materialized lazily on every command. Trails touched by recall get their idle timer reset, so frequently used memories persist.
- Reinforce: a trail demonstrably helped -> `reinforce <id>` (tau += 0.1, success+1). It misled the agent -> `fail <id>` (tau *= 0.9).
- Pruning: `decay` moves trails with tau < 0.05 to archive.json.
- Contradiction / new info: `spike <id> --superseded-by <new-id>`, then `add` the replacement.
- Near-duplicate: add with Jaccard >= 0.8 against an old trail merges into it (tau += K, tags unioned) instead of duplicating. Force a separate entry with `--force`. Identical content is a re-learn (tau += K).
- IDs accept any unique prefix (e.g. `0dd7` suffices); ambiguous or unknown prefixes exit 1 with a clean message.

## Usage

    python3 ant_memory.py add "fact" --tags topic1,topic2 [--force]
    python3 ant_memory.py recall "query" --n 5
    python3 ant_memory.py reinforce|fail|spike|forget <id>
    python3 ant_memory.py decay|list

## Discipline

- Before answering from past experience: `recall` first.
- After a solution is proven working: `reinforce` the trail behind it.
- Once per heavy session: `decay`.
- When a trail proves permanently valuable: promote it to dedicated long-term memory (system prompt, native memory, docs). Do not just reinforce forever.
- Never hard-delete: archive.json is the safety net.
