# Graph Report - C:\Users\User\oki-engine-backend\graphify-out\corpus  (2026-08-14)

## Corpus Check
- Corpus is ~0 words - fits in a single context window. You may not need a graph.

## Summary
- 137 nodes · 203 edges · 9 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Localization Production Workflow|Localization Production Workflow]]
- [[_COMMUNITY_Backend Workers and Reliability|Backend Workers and Reliability]]
- [[_COMMUNITY_Product Models and Voice Policy|Product Models and Voice Policy]]
- [[_COMMUNITY_Roles APIs and Quality Gates|Roles APIs and Quality Gates]]
- [[_COMMUNITY_Rights Compliance Audit Storage|Rights Compliance Audit Storage]]
- [[_COMMUNITY_Core Data Model|Core Data Model]]
- [[_COMMUNITY_Integration Test Coverage|Integration Test Coverage]]
- [[_COMMUNITY_Analytics and Financial Reporting|Analytics and Financial Reporting]]
- [[_COMMUNITY_Delivery Stages|Delivery Stages]]

## God Nodes (most connected - your core abstractions)
1. `Media Workers` - 16 edges
2. `Functional Scope` - 16 edges
3. `End-to-End Workflow` - 15 edges
4. `Oki Creator Localization Engine` - 11 edges
5. `Rights Gate` - 10 edges
6. `Engineering Principles` - 10 edges
7. `Core Database Entities` - 8 edges
8. `Publishing` - 8 edges
9. `Employee SOP` - 8 edges
10. `Analytics & Reporting` - 7 edges

## Surprising Connections (you probably didn't know these)
- `Oki Creator Localization Engine` --references--> `Rights Gate`  [EXTRACTED]
  graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf → graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf  _Bridges community 2 → community 3_
- `Creator and Rights Management` --conceptually_related_to--> `Rights Gate`  [EXTRACTED]
  graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf → graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf  _Bridges community 3 → community 0_
- `Rights Before Processing` --rationale_for--> `Rights Gate`  [EXTRACTED]
  graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf → graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf  _Bridges community 3 → community 4_
- `Rights Tests` --conceptually_related_to--> `Rights Gate`  [EXTRACTED]
  graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf → graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf  _Bridges community 3 → community 6_
- `Audit and Compliance` --conceptually_related_to--> `AuditEvent`  [EXTRACTED]
  graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf → graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf  _Bridges community 5 → community 4_

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Licensed Localization Control Plane** — oki_creator_localization_engine_rights_gate, oki_creator_localization_engine_creator_approval, oki_creator_localization_engine_publishing, oki_creator_localization_engine_audit_compliance [EXTRACTED 1.00]
- **Media Localization Pipeline** — oki_creator_localization_engine_source_ingestion, oki_creator_localization_engine_transcription_analysis, oki_creator_localization_engine_translation, oki_creator_localization_engine_dubbing, oki_creator_localization_engine_audio_mixing, oki_creator_localization_engine_rendering [EXTRACTED 1.00]
- **Delivery Acceptance Chain** — oki_creator_localization_engine_delivery_stages, oki_creator_localization_engine_required_tests, oki_creator_localization_engine_definition_of_done, oki_creator_localization_engine_final_acceptance [EXTRACTED 1.00]

## Communities (9 total, 0 thin omitted)

### Community 0 - "Localization Production Workflow"
Cohesion: 0.10
Nodes (30): Advertisement Segment Review, Audio Mixing, Audio Processing, Audio Quality Gate, Content Analyst, Creator Onboarding, Creator and Rights Management, Dubbing (+22 more)

### Community 1 - "Backend Workers and Reliability"
Cohesion: 0.08
Nodes (27): Analytics-Ingestion Worker, Audio-Mixing Worker, Authentication and Permissions, Backend, Diarization Worker, Frontend, Expensive Jobs Must Be Idempotent, Media Workers (+19 more)

### Community 2 - "Product Models and Voice Policy"
Cohesion: 0.14
Nodes (18): CREATOR_APPROVED_CLONE, Creator Channel Localization, Creator Offer, Definition of Done, Final Acceptance, HUMAN_VOICE_ACTOR, LICENSED_NEUTRAL_VOICE, Licensed Regional Channel (+10 more)

### Community 3 - "Roles APIs and Quality Gates"
Cohesion: 0.15
Nodes (17): Analytics API, API Endpoints, Assets & Workflow API, Creator Approval, Creator Manager, Creator & Rights API, Creator, Employee SOP (+9 more)

### Community 4 - "Rights Compliance Audit Storage"
Cohesion: 0.18
Nodes (11): Audit and Compliance, Creator Approval Portal, Engineering Principles, Originals Must Remain Immutable, No Hidden Modifications, No Sponsor Replacement Without Explicit Permission, Every Public Asset Must Be Traceable, Rights Before Processing (+3 more)

### Community 5 - "Core Data Model"
Cohesion: 0.47
Nodes (9): AdSegment, AuditEvent, Creator, Core Database Entities, LocalizationJob, Publication, RightsAgreement, SourceAsset (+1 more)

### Community 6 - "Integration Test Coverage"
Cohesion: 0.22
Nodes (9): Dubbing and Voice Management, Media Ingestion, Media Tests, Platform Compliance Takes Priority Over Upload Volume, Rendering and Publishing Tests, Required Tests, Rights Tests, Translation and Dubbing Tests (+1 more)

### Community 7 - "Analytics and Financial Reporting"
Cohesion: 0.25
Nodes (8): Analytics & Reporting, Analytics, Creator Metrics, Daily Production Report, Oki Contribution Margin per Licensed Localized Video, Oki Metrics, Production Metrics, Weekly Management Report

### Community 8 - "Delivery Stages"
Cohesion: 0.46
Nodes (8): Delivery Stages, Stage 0 — Architecture and Specification, Stage 1 — Rights, Creators and Ingestion, Stage 2 — Analysis and Translation, Stage 3 — Dubbing and Rendering, Stage 4 — Creator Portal and Publishing, Stage 5 — Shorts and Analytics, Stage 6 — Production Hardening

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Functional Scope` connect `Localization Production Workflow` to `Backend Workers and Reliability`, `Rights Compliance Audit Storage`, `Integration Test Coverage`, `Analytics and Financial Reporting`?**
  _High betweenness centrality (0.348) - this node is a cross-community bridge._
- **Why does `Rights Gate` connect `Roles APIs and Quality Gates` to `Localization Production Workflow`, `Product Models and Voice Policy`, `Rights Compliance Audit Storage`, `Integration Test Coverage`?**
  _High betweenness centrality (0.285) - this node is a cross-community bridge._
- **Why does `Engineering Principles` connect `Rights Compliance Audit Storage` to `Backend Workers and Reliability`, `Product Models and Voice Policy`, `Roles APIs and Quality Gates`, `Integration Test Coverage`?**
  _High betweenness centrality (0.266) - this node is a cross-community bridge._
- **What connects `Creator Channel Localization`, `Licensed Regional Channel`, `Original Local Adaptation` to the rest of the system?**
  _29 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Localization Production Workflow` be split into smaller, more focused modules?**
  _Cohesion score 0.10114942528735632 - nodes in this community are weakly interconnected._
- **Should `Backend Workers and Reliability` be split into smaller, more focused modules?**
  _Cohesion score 0.07977207977207977 - nodes in this community are weakly interconnected._
- **Should `Product Models and Voice Policy` be split into smaller, more focused modules?**
  _Cohesion score 0.1437908496732026 - nodes in this community are weakly interconnected._