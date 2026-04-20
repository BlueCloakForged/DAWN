                (Upstream artifacts + ledger state)
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│ LINK: <link_id>  (deterministic pillar / autonomous unit of work)  │
├────────────────────────────────────────────────────────────────────┤
│ 1) Intent (link.yaml)                                              │
│    - apiVersion/kind/metadata                                      │
│    - spec.requires[]   (artifactId, from_link, optional, when)     │
│    - spec.produces[]   (artifactId, path, schema, classify, ttl)   │
│    - steps[] (fixed sequence) + runtime constraints                │
│                                                                    │
│ 2) Contract Enforcement                                            │
│    - validate_requires()  (artifactId → artifact_index lookup)     │
│    - evaluate_when()      (always / on_success / on_failure /      │
│                            if_artifact_exists)                     │
│                                                                    │
│ 3) Execution Sandbox                                               │
│    - working dir: projects/<p>/artifacts/<link_id>/                │
│    - deterministic tools/scripts (no “thinking”)                   │
│                                                                    │
│ 4) Output Validation                                               │
│    - produced artifacts exist                                      │
│    - schema checks (e.g., JSON parse / schema ref)                 │
│                                                                    │
│ 5) Artifacts (what downstream consumes)                            │
│    - files under artifacts/<link_id>/...                           │
│    - digests (sha256) recorded                                     │
│                                                                    │
│ 6) Ledger Events (audit + reward substrate)                        │
│    - STARTED / SUCCEEDED / FAILED / SKIPPED                        │
│    - inputs + outputs + artifact_index + invariant_results         │
└────────────────────────────────────────────────────────────────────┘
                           ▲
                           │
                (Downstream reads artifacts + ledger)
