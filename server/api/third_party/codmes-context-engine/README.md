# Codmes context engine

Dependency-free extraction of the existing Codmes token budget, conversation
compaction planner and native/semantic/failure orchestration. Codmes imports it
directly; KNU vendors a versioned, checksum-verified snapshot of the same files.
This is internal code reuse, not a published npm package or a Hermes engine.

The host provides native and semantic compaction callbacks, storage and model
metadata. The engine never loads credentials, opens a network connection, or
reads session files. `bridge.mjs` exposes the same engine over JSONL pipes for a
Python host; only conversation content and compaction results cross the pipe.

Token counts are conservative heuristics, not exact tokenizer measurements.
Use actual provider/runner context limits when available and reserve room for
instructions, tools, the incoming question and output. Original messages must
be stored separately. Compaction is lossy; retrieval of originals is a separate
host feature. On summary failure the original context is returned; the host
must reject an oversized request rather than silently drop messages.

Run `node --test packages/context-engine/*.test.mjs` and the existing Codmes
runtime tests. No npm dependencies are needed.
