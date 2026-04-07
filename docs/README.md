# Docs Layout

This repository separates long-lived design documents from agent-facing and agent-produced documents.

## Directory Map

### `docs/design/`

Design and architecture documents.

- `specs/`: canonical design specs, architecture notes, validation design, and behavior models

Use this area for:

- system design
- architecture decisions
- runtime behavior contracts
- validation design
- future capability design

### `docs/agent/`

Agent workflow documents and agent-produced outputs.

- `plans/`: tasking docs, implementation plans, and work breakdowns prepared for agents
- `reviews/`: review notes, rereviews, and assessment documents
- `deliveries/`: delivery reports and completion summaries produced after implementation

Use this area for:

- assigning work to agents
- recording review findings and rereview outcomes
- capturing implementation completion and residual risks

## Other Top-Level Docs

These remain top-level because they are operator or repository guides rather than design specs or agent workflow artifacts.

- `runtime-console-operator-guide.md`
- `transport-architecture.md`
- `upgrade-and-rollback-guide.md`

## Rule Of Thumb

When adding a new document:

1. If it defines how the system should work, place it under `docs/design/`.
2. If it tells an agent what to build, place it under `docs/agent/plans/`.
3. If it records review findings, place it under `docs/agent/reviews/`.
4. If it records what an implementation round delivered, place it under `docs/agent/deliveries/`.
