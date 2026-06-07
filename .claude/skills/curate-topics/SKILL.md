---
name: curate-topics
description: Curate the Mater-trend materials-science taxonomy — decide whether new candidate keywords are noise, existing-topic synonyms, new topics, or parked.
---

# curate-topics

The reasoning core between candidate extraction and topic assignment. Run commands
as `PYTHONNOUSERSITE=1 ./env/bin/mat-trend ...` (needs the `[curate]` extra:
`pip install -e '.[curate]'` plus `python -m spacy download en_core_web_lg`).

## Procedure

1. **Extract candidates**:
   ```
   mat-trend candidates "<CSV>" --journal <label> --period <YYYY-MM> -o /tmp/candidates.json
   ```
   The payload has `existing_topics` (anchor on these) and `candidates` (most
   frequent first), each with a count and example titles.

2. **Decide every candidate** — one of:
   - `existing` — a synonym/variant of an existing topic (give `topic`).
   - `new` — a genuinely distinct materials-science theme (count ≥ ~8, coherent examples).
   - `noise` — generic science vocabulary (study, analysis, method, properties, performance…).
   - `other` — real but niche/uncertain; parked, not assigned yet.

3. **Write `/tmp/decision.json`**: `{"decisions": [{"keyword": ..., "action": ..., "topic": ...}, ...]}`.

4. **Apply & verify**:
   ```
   mat-trend curate --dry-run /tmp/decision.json   # preview
   mat-trend curate /tmp/decision.json             # apply (updates config/*.json)
   mat-trend assign "<CSV>"                         # relabel with the new taxonomy
   ```

## Decision principles

- **Anchor on existing taxonomy** — prefer `existing` over `new`.
- **Keywords must be lowercase** — assignment matches case-sensitively against
  lowercased text, so always emit lowercase keywords. Reuse topic labels exactly as
  in `existing_topics`.
- **Avoid short ambiguous keywords** — assignment is a plain substring match with no
  word boundaries, so 2–3 letter acronyms (`led`, `her`, `oer`, `tem`, `sem`, `ald`,
  `zt`, `mof`) will match unrelated words. Prefer distinctive multiword phrases
  (`oxygen evolution`, `metal-organic framework`, `electron microscopy`).
- **Be conservative with `new`** — a handful of genuinely new materials topics per
  cycle is normal; use `other` when unsure.
- Monthly journal buckets are modest in size, so counts run lower — judge by
  coherence of examples, not just raw count.
