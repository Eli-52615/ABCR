# ABCR Exploration Control V1

Status: implementation candidate. This amendment does not merge or replace R2.

1. Experiment goals originate from `human_claude_manual`. The system validates and compiles; it does not design.
2. Exploration processes receive only content-addressed dev bundles. Calibration and holdout remain structurally unreachable.
3. Probe output is permanently `exploratory_learning_only` and `citable=false`.
4. Human approval uses Ed25519 v2 bound to audience, deployment, protocol, request, batch and envelope bytes. HMAC v1 remains historical/fixture only.
5. Inbox/outbox, incidents and missions live in a control database separate from scientific evidence ledgers.
6. Code repair uses a plain candidate tree. Trusted parent-process external oracles, not candidate exit status/JUnit, authorize low-risk release.
7. Scientific, evidence, approval and control TCB paths are always `human_required`.
8. Releases are immutable finite trees; activation is broker-mediated compare-and-swap with an external canary and rollback receipt.
