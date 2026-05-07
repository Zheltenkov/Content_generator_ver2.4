# Didactics Skills Refactor Plan

## Goal

Create a single, versioned didactics governance layer for agentic content generation:

- one source of truth for style, structure, pedagogy, and thresholds;
- reusable skill fragments for prompts;
- shared machine rules for validators/rubric;
- zero drift between generation and evaluation.

This plan is implementation-focused and split into small PR-sized milestones.

---

## Current Pain Points

1. Rules are duplicated across prompt files, style guard, banned phrases, and rubric regex.
2. Some contracts can drift (`Задание` vs `Задача`, theory header variants, chapter formatting).
3. Didactics loading paths are fragmented (prompt files, inline API rewrite rules, shared didactics helpers).
4. No canonical rule IDs linking prompt guidance and validator checks.
5. HITL/rewrite policies are not unified with core didactics contracts.

---

## Target Architecture

## 1) Didactics Manifest as the Control Plane

Add versioned manifest (single authority):

- `content_gen/didactics/manifest.yaml`
- `content_gen/didactics/loader.py` (already present, extend)
- `content_gen/didactics/__init__.py`

Manifest responsibilities:

- declare `bundle_version`, `locale`, and `schema_version`;
- declare skill modules and machine-rule references;
- declare agent bindings (which skills each agent receives);
- map thresholds from `content_gen/config/thresholds.py`;
- publish compatibility mode (`legacy`, `mixed`, `strict`).

## 2) Skills as Reusable Prompt Fragments

Add:

- `content_gen/didactics/skills/*.md` (domain-readable, short, composable)

Skill groups:

- `voice.*` (tone, pronouns, directive ban, anti-CTA)
- `brand.*` (School 21 naming, p2p conventions)
- `structure.*` (H2/H3 contracts)
- `pedagogy.*` (SJM, p2p artifact clarity, theory-to-practice bridge)
- `quality.*` (length constraints, hard/soft expectations)
- `rewrite.*` (preserve structure + targeted edits)

## 3) Shared Machine Rules

Add single pattern registry:

- `content_gen/didactics/patterns.py`

Rules consumed by:

- `content_gen/agents/practice.py`
- `content_gen/agents/theory.py`
- `content_gen/validators/theory.py`
- `content_gen/validators/practice_checks.py`
- `content_gen/validators/rubric/scorer.py`
- `content_gen/validators/rubric/chapter*_checker.py`

No direct regex copies in multiple places unless strictly adapter-level.

## 4) Prompt Composition Layer

Add:

- `content_gen/didactics/composer.py`

Responsibilities:

- compose `system` and `user` additions from manifest-bound skills;
- inject threshold values dynamically (do not hardcode numbers in skill text);
- support `mode=legacy|mixed|strict`;
- return trace metadata: `didactics_bundle_version`, `skills_used`.

---

## Didactics Manifest Contract

Minimal schema (v1):

```yaml
schema_version: 1
bundle_id: school21_readme_ru
bundle_version: "2026.03.0"
locale: ru
mode: mixed

defaults:
  skills:
    - voice.ty_pronoun
    - voice.no_directives
    - voice.no_cta
    - brand.school21_p2p

threshold_refs:
  theory_parts: THRESHOLDS.theory_parts
  theory_words_per_part: THRESHOLDS.theory_words_per_part
  practice_tasks_range: THRESHOLDS.practice_tasks_range
  approach_words_max: THRESHOLDS.approach_words_max

skills:
  - id: structure.practice_h3
    file: skills/structure_practice_h3.md
    machine_rules: [readme.h3.practice_task]
    severity: hard
  - id: structure.theory_h3
    file: skills/structure_theory_h3.md
    machine_rules: [readme.h3.theory_part]
    severity: hard

agent_bindings:
  intro_rules: [voice.ty_pronoun, voice.no_directives, structure.intro_h3]
  theory: [voice.ty_pronoun, voice.no_directives, structure.theory_h3, pedagogy.sjm, quality.theory_bounds]
  practice: [voice.ty_pronoun, voice.no_directives, structure.practice_h3, pedagogy.p2p_artifact, quality.practice_bounds]
  regeneration: [rewrite.structure_preservation, voice.no_directives]
```

Pydantic model (target):

- `DidacticsManifest`
- `DidacticsSkillSpec`
- `DidacticsBindings`
- `DidacticsThresholdRef`

---

## Proposed Folder Layout

```text
content_gen/
  didactics/
    __init__.py
    manifest.yaml
    loader.py
    composer.py
    patterns.py
    rules.py
    skills/
      voice_ty_pronoun.md
      voice_no_directives.md
      voice_no_cta.md
      brand_school21_p2p.md
      structure_intro_h3.md
      structure_theory_h3.md
      structure_practice_h3.md
      pedagogy_sjm.md
      pedagogy_theory_bridge.md
      pedagogy_p2p_artifact.md
      rewrite_structure_preservation.md
```

---

## Migration Mapping (Old -> New)

| Legacy Source | New Skill/Rule |
|---|---|
| `prompts/theory/system.md` tone block | `voice.*` skills |
| `prompts/practice/system.md` tone block | `voice.*` skills |
| `prompts/intro_rules/system.md` tone block | `voice.*` + `structure.intro_h3` |
| `config/banned_phrases.py` directives | `voice.no_directives` machine rules |
| `StyleGuardAgent` pronoun/cta/eval bans | `voice.ty_pronoun`, `voice.no_cta`, `voice.no_eval_labels` |
| Rubric regex task/theory headers | `structure.practice_h3`, `structure.theory_h3` from `patterns.py` |
| Inline rewrite system in API | `rewrite.structure_preservation` + bound skills |

---

## Implementation PR Plan

## PR-1: Contracts and Registry (no behavior change)

Scope:

- Add manifest schema and loader validation.
- Add `patterns.py` with exported regex constants.
- Add `composer.py` skeleton and unit tests.

Files:

- `content_gen/didactics/*`
- `tests/config/test_loader.py` (extend)
- `tests/validators/*` (pattern import smoke)

Definition of done:

- Manifest validates.
- Existing pipeline still runs without using composer.

## PR-2: Generation Path Integration (mixed mode)

Scope:

- Integrate composer into `TheoryAgent`, `PracticeAgent`, `IntroRulesAgent`, `RegenerationAgent`.
- Keep legacy prompt text, append composed didactics blocks in `mixed` mode.

Files:

- `content_gen/agents/theory.py`
- `content_gen/agents/practice.py`
- `content_gen/agents/intro_rules.py`
- `content_gen/agents/regeneration.py`
- `content_gen/didactics/composer.py`

Definition of done:

- Prompt assembly logs `didactics_bundle_version` and `skills_used`.
- No drop in test pass rate.

## PR-3: Validator/Rubric Convergence

Scope:

- Replace duplicated regexes in validators/rubric with imports from `didactics/patterns.py`.
- Enforce single task heading contract.

Files:

- `content_gen/validators/practice_checks.py`
- `content_gen/validators/theory.py`
- `content_gen/validators/rubric/scorer.py`
- `content_gen/validators/rubric/chapter3_checker.py`

Definition of done:

- No local duplicate regex for core structure contracts.
- Legacy compatibility gate controlled by manifest `mode`.

## PR-4: Rewrite + HITL Alignment

Scope:

- Route rewrite endpoint system prompt through composer.
- Stepwise artifact metadata includes didactics bundle/rules.

Files:

- `api/routers/readme_improvement.py`
- `api/routers/generation.py`
- `api/utils/stepwise_store.py`

Definition of done:

- Rewrite uses same structure contracts as generation/rubric.

## PR-5: Strict mode switch + cleanup

Scope:

- Switch default from `mixed` to `strict` after acceptance.
- Remove legacy duplicated prompt blocks and dead compatibility branches.

Definition of done:

- Drift tests are green.
- Removed duplicate tone/structure snippets from prompts.

---

## Testing Strategy

1. Unit tests:
   - manifest validation;
   - composer deterministic output by agent;
   - pattern contracts.
2. Contract tests:
   - generated markdown parses with shared rules;
   - rubric sees expected sections.
3. Golden regression:
   - fixed seed set (10-30 seeds);
   - compare rubric floor, structural pass, and warnings.
4. Rewrite regression:
   - rewrite preserves required headers (`2.N`, `Задание N`) in strict mode.

---

## KPIs

- Structural mismatch incidents (`generator != validator`) -> 0.
- `% final outputs with hard issues` decreases release-over-release.
- p95 generation latency stable or better after refactor.
- Prompt drift incidents (manual bug reports about format mismatch) -> near 0.
- Rewrite success rate (structure-preserving) > 98%.

---

## Risk Register

1. **Behavior drift in prompt outputs** after composition.
   - Mitigation: `mixed` mode + golden suite.
2. **Over-constrained strict mode** may reduce creativity.
   - Mitigation: severity tiers and optional soft skills.
3. **Legacy data consumers expect old headers**.
   - Mitigation: compatibility regex in `mixed`, explicit cutover date.
4. **Hidden dependencies on old prompt text**.
   - Mitigation: phased rollout and per-agent feature flag.

---

## Current Status

Refactor milestones PR-1 .. PR-5 are implemented.

Current operating contract:

1. `strict` mode is default and only runtime mode.
2. didactics prompt assembly uses `skill_specs` + `agent_bindings` only.
3. legacy/mixed compatibility branches are removed from composer flow.
