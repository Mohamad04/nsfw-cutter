"""Deterministic, metadata-only SafeSora-Label selection proposal.

Reads the official test metadata (config-test.json.gz) and writes a proposal
containing identifiers, native labels and text hashes only. It never touches
media and never stores prompt text.

Usage: python -I safesora_label_select.py <config-test.json.gz> <config-train.json.gz> <output.json>
"""

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

REVISION = "ebe407320f42e2324cfd9b5bd0ca548e7a865175"
SEED = "nsfw-cutter/safesora-label/test/v2"
GENERATOR = "videocrafter2"
# A screening aid only. A miss does NOT establish adult-only content.
AGE_TERMS = re.compile(
    r"\b(child|children|kid|kids|minor|minors|teen|teens|teenage|teenager|underage|"
    r"young|youth|girl|girls|boy|boys|school|schoolgirl|schoolboy|student|students|"
    r"baby|infant|toddler|loli|daughter|son|juvenile|little|preteen|adolescent|petite)\b",
    re.IGNORECASE,
)
STRATA = (
    # name, count, predicate on native labels only (is_safe deliberately unused)
    ("positive", 25, lambda r: r["video_labels"]["porn"] is True),
    ("hard_negative", 15, lambda r: r["prompt_labels"]["porn"] is True and not any(r["video_labels"].values())),
    ("easy_negative", 10, lambda r: r["prompt_type"] == "safety_neutral"
     and not any(r["prompt_labels"].values()) and not any(r["video_labels"].values())),
)
SEXUAL_STRATA = {"positive", "hard_negative"}


def sha256_hex(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def load(path):
    raw = Path(path).read_bytes()
    return sha256_hex(raw), json.loads(gzip.decompress(raw))


def child_flag(row):
    return bool(row["video_labels"]["child_abuse"] or row["prompt_labels"]["child_abuse"])


def age_term(row):
    return bool(AGE_TERMS.search(row["prompt_text"] + " " + (row.get("video_text") or "")))


def main(test_path, train_path, output_path):
    test_sha, rows = load(test_path)
    train_sha, train_rows = load(train_path)
    archive_rows = rows + train_rows

    groups = {}
    for row in rows:
        groups.setdefault(row["prompt_id"], []).append(row)

    used_prompts, records, pools = set(), [], {}
    for name, count, predicate in STRATA:
        def eligible(row):
            if row["generated_from"] != GENERATOR or child_flag(row) or not predicate(row):
                return False
            return not (name in SEXUAL_STRATA and age_term(row))

        # Stage 1: rank prompt groups; stage 2: one video per group. Each prompt
        # carries equal weight regardless of how many eligible videos it has.
        candidates = {pid: [r for r in rs if eligible(r)] for pid, rs in groups.items()}
        candidates = {pid: rs for pid, rs in candidates.items() if rs}
        pools[name] = {
            "eligible_prompt_groups": len(candidates),
            "eligible_records": sum(len(rs) for rs in candidates.values()),
        }
        chosen = 0
        for pid in sorted(candidates, key=lambda p: sha256_hex(f"{SEED}|prompt|{p}")):
            if chosen == count:
                break
            if pid in used_prompts:
                continue
            row = min(candidates[pid], key=lambda r: sha256_hex(f"{SEED}|video|{r['video_id']}"))
            used_prompts.add(pid)
            chosen += 1
            sexual = name in SEXUAL_STRATA
            records.append({
                "stratum": name,
                "reference_s1": "positive" if name == "positive" else "negative_not_exhaustive",
                "prompt_id": row["prompt_id"],
                "video_id": row["video_id"],
                "video_path": row["video_path"],
                "generated_from": row["generated_from"],
                "prompt_type": row["prompt_type"],
                "video_labels": row["video_labels"],
                "prompt_labels": row["prompt_labels"],
                "is_safe_uncertain_field": row["is_safe"],
                "is_safe_consistent_with_video_labels": row["is_safe"] != any(row["video_labels"].values()),
                "prompt_text_sha256": sha256_hex(row["prompt_text"]),
                "video_text_sha256": sha256_hex(row.get("video_text") or ""),
                "video_text_differs_from_prompt_text": row.get("video_text") != row["prompt_text"],
                "age_status": "unverified_blocked_from_media_preparation" if sexual
                else "not_applicable_no_sexual_label_or_prompt",
            })
        if chosen < count:
            raise SystemExit(f"Insufficient prompt groups for stratum {name}")

    def count(predicate, source=rows):
        return sum(1 for r in source if predicate(r))

    any_video = lambda r: any(r["video_labels"].values())
    proposal = {
        "schema": "nsfw-cutter.safesora-label.selection-proposal",
        "schema_version": 1,
        "proposal_id": "safesora-label-test50-20261018-v2",
        "status": "proposal_blocked_access_and_age_safety",
        "authorization": {"archive_transfer": False, "media_preparation": False, "inference": False},
        "pipeline": {
            "git_commit": "ca7a6732aa0d4e153b06dada6d54c076a929db27",
            "prompt_schema_revision": 3,
            "configuration": "Balanced",
        },
        "provenance": {
            "repository": "https://huggingface.co/datasets/PKU-Alignment/SafeSora-Label",
            "revision": REVISION,
            "declared_license": "cc-by-nc-4.0",
            "paper": "https://arxiv.org/abs/2406.14477",
            "split": "test",
            "test_metadata": {"file": "config-test.json.gz", "sha256": test_sha, "rows": len(rows)},
            "train_metadata": {"file": "config-train.json.gz", "sha256": train_sha, "rows": len(train_rows),
                               "use": "archive content audit only"},
            "archive": {"file": "videos.tar.gz", "bytes": 31819136591,
                        "sha256": "7d4a5af0b0ae738b104430cda34127a40c58d1a02023b9b867fafbecc0a964a1",
                        "format": "single-member gzip (header 1f8b0800...), no index; HTTP ranges allow prefix reads only"},
            "selector": "evaluation/proposals/safesora_label_select.py",
        },
        "selection": {
            "seed": SEED,
            "generator_restriction": GENERATOR,
            "method": "Per stratum, rank prompt groups by sha256(seed|prompt|prompt_id); take one video per group, "
                      "the minimum sha256(seed|video|video_id) among eligible rows; strata filled in listed order; "
                      "a prompt_id is used at most once across all strata.",
            "strata": {name: count for name, count, _ in STRATA},
            "definitions": {
                "positive": "video_labels.porn == true (human S1 on the text-video pair)",
                "hard_negative": "prompt_labels.porn == true (GPT-4 prompt pre-classification) and all 12 video_labels false",
                "easy_negative": "prompt_type == safety_neutral, all prompt_labels false, all video_labels false",
            },
            "exclusions": [
                "generated_from != videocrafter2",
                "any child_abuse flag in prompt_labels or video_labels",
                "sexual strata: any age-related term in prompt_text or video_text (screening aid, not proof of adulthood)",
            ],
            "is_safe_policy": "Not used for selection (undocumented and contradicts video_labels in "
                              f"{count(lambda r: r['is_safe'] == any_video(r))} of {len(rows)} test rows). "
                              "Recorded per record for a secondary stratified analysis only.",
            "pools": pools,
            "replacement_policy": "No substitution after media access or model outputs; excluded or failed records remain in the denominator report.",
        },
        "age_safety": {
            "statement": "Metadata cannot establish that sexual-content videos depict only adults. All positive and hard_negative records are blocked from media preparation.",
            "test_split_counts": {
                "video_child_abuse_and_porn": count(lambda r: r["video_labels"]["child_abuse"] and r["video_labels"]["porn"]),
                "prompt_child_abuse_and_video_porn": count(lambda r: r["prompt_labels"]["child_abuse"] and r["video_labels"]["porn"]),
                "video_porn_with_age_term": count(lambda r: r["video_labels"]["porn"] and age_term(r)),
            },
            "full_archive_counts": {
                "video_child_abuse_and_porn": count(lambda r: r["video_labels"]["child_abuse"] and r["video_labels"]["porn"], archive_rows),
                "prompt_child_abuse_and_video_porn": count(lambda r: r["prompt_labels"]["child_abuse"] and r["video_labels"]["porn"], archive_rows),
            },
            "transfer_consequence": "The monolithic gzip cannot be read selectively; any transfer reaching these members moves them onto the machine even if never written to disk.",
        },
        "records": records,
    }
    Path(output_path).write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pools": pools, "age_safety": proposal["age_safety"]["full_archive_counts"],
                      "records": len(records)}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
