# 0001. Record architecture decisions

- Status: accepted
- Date: 2026-09-28

## Context

Synapse is built by a very small team and will be continued across machines and over a long time. When the reasoning behind decisions is lost, teams repeat the same mistakes and documentation drifts from the code.

## Decision

Every decision that is hard to reverse, or that a new contributor would otherwise have to rediscover, is recorded as an ADR in `docs/adr/`, numbered sequentially, using [0000-template.md](0000-template.md).

- ADRs are short. Evidence and long comparisons live in `docs/research/` and are linked.
- An accepted ADR is never edited to change its meaning. A new ADR supersedes it, and the old one gets `Status: superseded by NNNN`.
- A pull request that contradicts an accepted ADR must either be changed or come with a new ADR.

## Consequences

Decisions can be reviewed and challenged with their context. The cost is a few minutes of writing per decision.

## Alternatives considered

- Decisions only in commit messages or chat: not discoverable, lost across machines.
- One large design document: becomes stale as a whole and hides which parts are still valid.
