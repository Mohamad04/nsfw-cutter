# SafeSora-Label secondary agreement study: protocol (blocked)

Prepared 2026-10-18. Metadata only: no archive transfer, no media opened, no inference.
Pipeline frozen at ca7a6732aa0d4e153b06dada6d54c076a929db27, Qwen schema 3, Balanced.
Selection: `safesora_label_test50.v2.json`, produced by `safesora_label_select.py` (deterministic; re-run verified byte-identical).
Status: **postponed — blocked by archive access/age safety (section 5)**. Not executable without the gates in section 7.

## 1. Source and provenance

- PKU-Alignment/SafeSora-Label, revision ebe407320f42e2324cfd9b5bd0ca548e7a865175, declared CC BY-NC 4.0, paper arXiv:2406.14477.
- Test metadata sha256 d1f6b4e3ca2c86dff5a32a7ec7ffa2b81e70cdb7d786fc196d2edf3bfd2139d2 (5,745 rows, 1,471 prompts).
- Train metadata sha256 da7a3f369f602ca12a2e85c750f6d24c0a28e3b6b05e3ff606884237bdbcb977 (51,588 rows; used only to audit archive content).
- Media: one `videos.tar.gz`, 31,819,136,591 bytes, single-member gzip without index. HTTP ranges work but only allow prefix reads; individual videos are not published.
- The proposal stores identifiers, native labels and SHA-256 of prompt texts only; no prompt text is committed.

## 2. Label semantics

| Field | Meaning | Applies to |
|---|---|---|
| `video_labels.porn` | Human S1 "Adult, Explicit Sexual Content" (nudity, sexual behaviour, innuendo) | Text-video pair; guidelines tell annotators to consider the text with the video |
| `prompt_labels.*` | GPT-4 pre-classification of the prompt | Text only; not human ground truth |
| `is_safe` | Undocumented; contradicts `video_labels` in 587/5,745 test rows (383 `porn=true` rows are `is_safe=true`) | Uncertain; recorded, never used for selection |
| `prompt_type` | Prompt design (`safety_critical` / `safety_neutral`) | Text only |
| `video_text` | Prompt actually given to the generator, LLM-refined in 41% of rows; which text annotators saw is not documented | Text only |

Negatives are not exhaustive. The guidelines do not require an explicit yes/no per tag, define no meaning for an absent tag, and the paper's own analysis (App. E.1) notes annotators may stop tagging ambiguous labels once the most suitable label is applied. "All 12 tags false" therefore means *no harm tag recorded*, not *no nudity or sexual context*.

## 3. Selection policy (v2)

Changes from the scratchpad v1: `is_safe` removed from every stratum definition (v1 conditioned on it, keeping only concordant cases and inflating agreement); sampling is now two-stage by prompt group.

- Restriction: `generated_from == videocrafter2`; exclude any `child_abuse` flag in prompt or video labels.
- Strata: 25 positives (`video_labels.porn`), 15 hard negatives (`prompt_labels.porn`, no video tag), 10 easy negatives (`safety_neutral`, no prompt or video tag).
- Sexual strata additionally exclude rows whose prompt or video text contains an age-related term. This is a screening aid, never evidence of adult-only content.
- Rank prompt groups by sha256(seed|prompt|prompt_id); take one video per group (minimum sha256(seed|video|video_id) among eligible rows). One prompt per record across all strata; seed `nsfw-cutter/safesora-label/test/v2`.
- Eligible pools: positives 303 groups / 639 rows; hard negatives 322 / 781; easy negatives 715 / 2,168.
- Selected positives: 10/25 have `is_safe=true` and 3/25 carry another harm tag; 27/50 used refined prompts. All are kept and reported.
- No substitution after media access or model output; exclusions stay in the denominator report.

## 4. Metrics and interpretation

The reference is an imperfect, pair-level human judgment. Report agreement, not accuracy:

- **Positive percent agreement (PPA)**: alerted / 25 S1-positive records.
- **Negative percent agreement (NPA)**: not alerted / 25 records with no recorded tag; also NPA on the 15 hard negatives and the 10 easy negatives separately.
- Wilson 95% intervals. At n=25 the half-width is roughly 15–20 points; at n=15 about 20–25.
- Secondary: PPA split by `is_safe` value (concordant vs discordant positives), descriptive only.
- Alert definition fixed in advance: any final NSFW-Cutter suggestion in {nudity, sexual_activity, sexual_context}.

Not valid: precision/PPV, F1 or prevalence-dependent accuracy (the prevalence is fixed by design); per-category results (S1 merges all three of our categories); temporal localisation (no intervals exist); claims of true NSFW-Cutter sensitivity/specificity (a disagreement may be a label omission, a text-driven label, or a model error); generalisation to real footage, audio, or long videos.

Pipeline caveat: clips are ~1–3 s without audio. At Balanced 0.2 fps the coarse stage yields about one frame (t≈0), so the result mainly measures first-frame prefiltering plus 1–2 VLM frames, not temporal behaviour.

## 5. Annotation bias

- Text leakage: S1 is judged on the pair, so a sexual prompt can produce a positive on a visually ambiguous video; this inflates apparent misses.
- Non-exhaustive negatives: under-tagging inflates apparent false alerts, worst for hard negatives.
- Spectrum: synthetic, low-resolution, near-static clips from one generator.
- `is_safe` is not used; selecting on it (v1) would have biased agreement upward.

## 6. Age safety and access blockers

- Metadata cannot establish that sexual-content records depict only adults. Every positive and hard-negative record is marked `unverified_blocked_from_media_preparation`. A text filter is not proof.
- The archive contains 36 videos human-labelled both `child_abuse` and `porn` (9 test, 27 train) and 499 with a child-abuse prompt and a porn-labelled video. Because the gzip is monolithic, a full-stream extraction necessarily transfers them to the machine, even if nothing is written to disk.
- French law (Code pénal art. 227-23) covers representations of minors, including virtual ones. Any transfer therefore requires prior written institutional legal/ethics clearance. This is not something the project can resolve technically.
- Prefix-only transfer (stopping early) reduces but does not remove this exposure, and introduces an unverifiable archive-order bias.

## 7. Gates before any execution

1. Written institutional legal/ethics clearance covering the full archive transfer, or a filtered per-file subset obtained from the dataset authors.
2. A named, supervisor-approved age-review procedure; any ambiguous clip is excluded and counted, never replaced.
3. Separate user approval for transfer, preparation and inference.
4. A thin SafeSora runner. The UCF101 technical runner is locked to its own proposal digest and clearance and must not be modified for this.

## 8. Cost–value assessment

| | SafeSora (this protocol) | UCF101 technical benchmark |
|---|---|---|
| Status | Blocked (section 6) | Implemented; awaiting usage clearance |
| Transfer / disk | ~31.8 GB transfer, ~30 MB kept | 12 MB, 25 files |
| Preparation | ~1 day + clearance of unknown duration | Ready |
| Inference | 30 min–2 h (estimate) | 10–30 min (estimate) |
| Evidence | PPA/NPA vs imperfect labels on synthetic 1–3 s clips; CI ±15–20 pts | Runtime, RTF, failures, alert rate on presumed-benign real clips; no accuracy |

Decision: postpone. The expected secondary result (a single wide-interval agreement estimate on synthetic clips) does not justify the legal exposure and clearance effort within the internship timeline. Revisit only if the authors supply a filtered per-file subset.
