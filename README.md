# AoC Memory For AI Agent

Persistent memory for AI agents, modeled on Ant Colony Optimization. Memories are pheromone trails: a memory that gets used grows stronger, one that sits idle evaporates, one that gets contradicted collapses fast. Retrieval is plain numeric ranking, so there are no embeddings and no vector database. The whole engine is a single Python file on the standard library.

## Why

LLM agents lose context between sessions. The usual fixes each have a cost: replaying transcripts is expensive, vector databases need infra and embedding calls, and plain note files only ever grow. This borrows the ACO idea (ants leaving pheromone trails that fade unless reinforced) and applies it to notes. Every memory carries a strength value `tau` that decays with idle time and gets reinforced by real outcomes. What the agent actually uses stays alive, what it never uses quietly archives itself.

## The math

- Retrieval rank: `P = tau^alpha * eta^beta` with `alpha=1, beta=2`, so query relevance dominates and pheromone breaks ties.
- `eta` (desirability) = token overlap between query and entry, scaled by the entry's success ratio. Range 0..1, 0.5 prior for untried entries.
- Evaporation: `tau *= (1 - rho)^idle_days` with `rho = 0.01/day`. A fresh trail (`tau=1`) halves after ~69 idle days and sinks below the forget threshold (0.05) after ~298 days.
- Reinforcement: proven useful `-> tau += 0.1, success+1`. Misleading `-> tau *= 0.9, fail+1`.
- Contradiction (`spike`): `tau *= 0.5`, optionally linked to the replacement entry via `--superseded-by`.
- Forgetting (`decay`): `tau < 0.05` moves the entry to `archive.json`. Nothing is hard-deleted.
- Near-duplicates: adding content with Jaccard >= 0.8 against an existing trail merges into it (counts as re-learn) instead of storing a copy.

## Install

Python 3.8+, zero dependencies:

```bash
git clone https://github.com/MyKineID/aoc-memory-for-ai-agent.git
```

Data lives in `~/.ant-memory/` by default. Set `ANT_MEMORY_DIR` to point it somewhere else, which is how you keep multiple agents or test runs isolated.

## Usage

```bash
# store a memory (write content and tags with the words you will query later)
python3 ant_memory.py add "deploy preview runs via GH Actions on every push" --tags ci,deploy

# retrieve, ranked by P = tau^1 * eta^2
python3 ant_memory.py recall "how does deploy work" --n 5

# a trail provably helped / did not help
python3 ant_memory.py reinforce 3f9a12c0
python3 ant_memory.py fail 3f9a12c0

# new info contradicts an old trail
python3 ant_memory.py spike 3f9a12c0 --superseded-by <new-id>

# global evaporation + prune (run once per heavy session or via cron)
python3 ant_memory.py decay

python3 ant_memory.py list
python3 ant_memory.py forget 3f9a12c0   # manual archive
```

Entry shape: `{id, content, tags, tau, success, fail, created, last_access}`. IDs are the first 8 hex chars of the content hash, and any unique prefix is accepted.

## Integrating with an agent

`SKILL.md` at the repo root is a ready-made skill file (Hermes/Claude-style frontmatter). The working loop:

1. Before answering from memory: `recall` the topic first.
2. After a trail demonstrably led to a working solution: `reinforce`. When it wasted the attempt: `fail`.
3. Once per heavy session: `decay`.
4. When a trail proves permanently valuable, promote it to real long-term storage (system prompt, native memory, docs) and let the trail die naturally.

Routing guidance: this store fits living knowledge such as work patterns, research findings, and project facts that stay useful through repeated access. Identity, credentials, and permanent procedures belong in dedicated long-term memory, because evaporation eventually eats even reinforced trails that are rarely queried (~298 idle days from fresh).

## Robustness

- Atomic writes (`tmp` + `os.replace`) with an exclusive `flock` on every write command, so parallel agent processes on the same store do not corrupt it.
- A corrupted store file is salvaged automatically: intact JSON objects are recovered, the broken original is kept as `*.corrupt.<timestamp>`.
- Idempotent learning: identical content is a re-learn, paraphrases merge, `--force` bypasses merging.

## Tests

```bash
python3 tests/test_smoke.py
```

Covers add/re-learn/merge/force, recall ranking, reinforce/fail/spike, decay pruning with backdating, forget, corruption salvage, and 10-way concurrent writes.

## License

MIT
