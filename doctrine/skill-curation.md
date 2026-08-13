# Doctrine: Skill Curation

This doctrine governs the behavior of the `skill-curator` role and any agent attempting to ingest new skills or modify the model fleet routing.

## 1. The Principle of Starvation

An agent is considered "starved" if it exhibits one or more of the following triggers:
- Repeating the same code generation error > 3 times (Linter loops).
- Explicitly emitting "I need a tool for X" or "I lack context about Y" in its output.
- Failing a task due to `limit-exhausted` or `rate-limit` (Fleet Limit Starvation).

**Action**: The Curator must prioritize the most frequent and blocking starvation triggers first, adding them to the `Wishlist`.

## 2. Universal Skill Conversion

When discovering a solution (a book, a guide, or an MCP server), the Curator MUST synthesize it into the Universal Skill format.

**Rules for Synthesis**:
- All skills must reside in `skills/<category>/SKILL.md`.
- They must have a YAML frontmatter containing `name`, `type` (`mcp` or `knowledge`), `applies_to` (list of roles), and `supported_clients` (`claude`, `gemini`, `codex`, `opencode`, or `all`).
- The content must be atomic. Do not create a monolithic 10,000-line skill. Decompose large documents using `brain-skill ingest-book`.

## 3. Human-in-the-Loop & Proposal Gate

Security is paramount. The Curator CANNOT run `brain-skill mount` for newly downloaded `mcp` skills directly.
1. The Curator creates the skill file in `skills/`.
2. The Curator creates a Proposal in `wiki/proposals/` detailing what the skill does, the source URL, and the roles it applies to.
3. Only after the Proposal is approved (by a human or via council consensus) can the skill be mounted.

## 4. Benchmark & Cost Routing (Fleet Management)

The Curator is responsible for maintaining the `wiki/provider-matrix.json`.
- **Quality**: Monitor public benchmarks (SWE-bench for coding, LMSYS for general).
- **Cost**: Monitor API pricing (input/output tokens).
- **Formula**: Rank models by their `IQ / Cost` ratio.
- **Availability**: If the Fleet Monitor reports `limit-exhausted` for a model, apply a temporary availability penalty to remove it from the top rank, forcing a fallback to the next best model.