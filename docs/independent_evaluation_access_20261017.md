# Independent evaluation: access requests and technical benchmark

Prepared 2026-10-17. Proposal only. No email sent, agreement accepted, media downloaded or inference run.
Production remains at ca7a6732aa0d4e153b06dada6d54c076a929db27, Qwen schema 3, Balanced.

## Access evidence and decisions

- Pornography-2k: Recod.ai requires a formal request and signed responsibility agreement; contact Prof. Anderson Rocha. Current Unicamp faculty directory lists rocha@ic.unicamp.br. Explicitly request the 2019 frame-level annotation release, not just the earlier video labels. Approval and storage terms remain unknown.
- NPDI-800: official repository requires a signed licence agreement sent to Sandra Avila, sandra@ic.unicamp.br. Research must be non-profit; third-party rights remain. The linked PDF could not be read through the web tool because of an expired signed redirect. Obtain/read the current agreement before signing; do not infer its detailed terms from the repository's MIT licence.
- UCF101: anonymous HTTP HEAD on 2026-10-17 returned 200 for all 25 URLs in the proposal manifest and for the official RAR (6,932,971,618 bytes). HEAD confirms server availability and declared sizes, not file integrity or permission. The Google Storage mirror used by TFDS returned 403. Use original individual UCF URLs, not that mirror.
- No explicit licence granting media reuse was identified on the UCF101 page. Public availability is not permission to redistribute or a CC0 licence. Institutional usage clearance or clarification from the provider is required before acquisition.
- LSPD: the official page explicitly says the data cannot be made freely available and requires a request to duypd@uit.edu.vn. Not an immediate open alternative.
- Unsafe-VidGraph: official dataset page requires case-by-case access approval and licence acceptance; no immediate open alternative.
- SafeWatch: public project/repository exist, but the paper describes restricted case-by-case evaluation-set access; labels originate from multi-agent models with sampled human verification. Do not treat the public repository or dataset-card licence as proof of unrestricted media rights or individually human-established labels.
- This bounded search found no verified replacement meeting all three requirements: anonymous video access, clear research reuse permission, and independently established relevant NSFW ground truth. This is not proof that no such dataset exists.

## Email 1: Pornography-2k

To: rocha@ic.unicamp.br

Subject: Academic access request — Pornography-2k and 2019 temporal annotations — ENSTA internship

Dear Professor Rocha,

My name is [Full name], and I am undertaking a non-commercial engineering internship project at ENSTA, supervised by [Supervisor name, role and institutional email], with [Host laboratory/organisation]. The project evaluates NSFW-Cutter, a video content detection pipeline, using independent research datasets. Our production model configuration is frozen, and the requested data would be used for evaluation, not model training.

I would like to request access to Pornography-2k, particularly the original videos and the frame-level/temporal annotations associated with “Multimodal data fusion for sensitive scene localization” (Information Fusion, 2019).

Could you please provide the current application procedure and responsibility agreement, and clarify:

1. Which original videos, audio tracks, video-level labels and temporal annotations are available, including release identifiers, official splits and checksums?
2. What are the annotation definitions, frame-index conventions, interval endpoints, time bases, completeness and documented uncertainty? Are identifiers linking Pornography-2k to NPDI-800 available?
3. Would an official small, reproducibly identified evaluation subset be available to shorten preparation time?
4. What licensing, citation and publication conditions apply, including whether aggregate results and non-sensitive evaluation code may be published?
5. What storage and processing conditions are permitted: encrypted local institutional workstation, approved personnel/supervisor access, backups, derived frames and caches, retention period, deletion, and any geographical or cloud restrictions?

Our proposed workflow uses local processing with restricted access, no redistribution of media, and preservation of the original annotations. We would not interpret unannotated NSFW categories as negatives. These arrangements would be confirmed against your terms before any download or processing. This request does not constitute acceptance of an agreement.

I can provide an institutional confirmation or supervisor endorsement if required.

Thank you for your consideration.

Kind regards,
[Full name]
[Engineering programme / internship role], ENSTA
[Host laboratory/organisation]
[Institutional email]
[Supervisor contact]

## Email 2: NPDI-800

To: sandra@ic.unicamp.br

Subject: Non-commercial research access request — NPDI Pornography Database — ENSTA internship

Dear Professor Avila,

My name is [Full name], and I am undertaking a non-commercial ENSTA engineering internship project evaluating video content detection, supervised by [Supervisor name, role and institutional email], with [Host laboratory/organisation]. We wish to evaluate our frozen NSFW-Cutter pipeline on independently labelled videos, without training or tuning on the evaluation data.

I am contacting you following the access instructions in the official NPDI Pornography Database repository. Could you please confirm the current licence agreement and application requirements, including whether a supervisor or institutional signatory is required?

We would like access to the original NPDI-800 videos and original video-level labels, official folds, easy/difficult negative identifiers, release metadata and checksums. Please also clarify whether any independently established temporal pornography annotations are available; we understand that shot segmentation alone is not temporal content ground truth.

Could you confirm the applicable non-commercial research, citation and publication terms, and the permitted storage arrangements: encrypted local institutional storage, authorised users and supervisor access, backups, extracted frames and analysis caches, retention/deletion requirements, and any restrictions on cloud processing or storage location? An official small evaluation subset, if available, would help us begin reproducibly.

Our proposed workflow uses local processing, restricted access and no media redistribution. We would preserve the native labels and report video-level results without assuming that non-pornographic videos are negative for every NSFW category. We would review the agreement with our supervisor before signing or downloading any data; this email does not constitute acceptance.

Thank you for your time and guidance.

Kind regards,
[Full name]
[Engineering programme / internship role], ENSTA
[Host laboratory/organisation]
[Institutional email]
[Supervisor contact]

## Minimal technical benchmark

The proposal is evaluation/proposals/ucf101_technical25.v1.json, a technical-only schema, deliberately NOT a pilot manifest. It contains 25 exact filenames and HEAD sizes, distinct (action class, group) identities, null local metadata and unknown NSFW labels. It has no empty exhaustive event arrays.

Selection is a fixed purposive sample across personal care, music, outdoor activities, sports and body movements. Each class contributes g01/c01 only. Distinct UCF groups are not proof of independent original uploads or absence from model pretraining. Do not claim a random population estimate. No substitutions based on predictions. Record missing/corrupt files and amend the proposal explicitly if necessary.

The original paper documents 320x240/25fps. Resolution diversity cannot honestly be claimed for this set. Preserve original resolution; resizing would only create derived technical stress tests, not independent data. Natural durations and audio presence must be measured after authorised retrieval; they have not been checked. Report duration strata (<5, 5-10, >10 seconds) and any empty strata, without silently selecting new videos. A broader duration/resolution study would require a separately approved extension.

After explicit authorisation and usage clearance:

1. Retrieve only the 25 individual files (12,065,722 declared bytes total), retain source URLs/headers and compute SHA-256; compare hashes with the pilot to reject exact overlaps.
2. Probe duration, resolution, frame timestamps and audio. Remux AVI to MKV using stream copy if compatible, retaining all intended streams and verifying duration/timestamp correspondence. Do not alter the production input validator or silently re-encode.
3. Freeze a resolved manifest, media hashes, effective settings, model revisions, environment and adapter revision. Keep production source hashes identical to the frozen revision.
4. Use a thin separate technical harness around the existing AnalysisPipeline/record observer. Do not call the pilot runner with invented annotations or weaken its require_ready checks. No general-purpose research-dataset adapter is needed for this first technical test.
5. Run sequentially, once per clip, with isolated attempt directories/caches. Record cold-start policy; measure runner wall time separately from pipeline time. Preserve failures and partial outputs; no silent retry or negative conversion. Stop on the first pipeline failure pending a decision, retaining the full selected-count denominator and reporting unattempted clips.
6. Report completed/25, attempted/25, partial/failed/unattempted counts, per-clip and aggregate runtime/RTF, predicted categories/intervals, fraction of completed clips with alerts, suggestions per completed video-hour, and union-alerted duration fraction. Partial-output alert statistics are separate. No TP/FP/FN/TN, false-positive rates, precision, recall, F1 or target coverage; these are N/A because ground truth is unavailable.

Preparation estimate: 2-4 engineering hours for the thin harness, metadata validation and synthetic tests, not the full adapter. Downloads are small; reserve 1 GB initially for originals, remuxes and bounded caches, excluding existing models. No complete archive is needed. At the corpus mean of 7.21 seconds, 25 clips would total about 3 minutes, but selected durations are unknown. RTF scenarios 0.5-2 imply 1.5-6 minutes of pipeline time; allow 10-30 minutes including repeated startup and audio work. Revise after metadata preflight; no runtime guarantee.

Authorisation gates: user approves email text/identity and recipients before sending; authorised institutional signatory approves agreements; user approves downloads only after usage conditions are cleared; separate user approval is required for real inference. No agreement or licence can be accepted automatically by a script.

## Sources

- https://recodpub.wordpress.com/code-data/
- https://ic.unicamp.br/docente/anderson-de-rezende-rocha/
- https://danielmoreira.github.io/publication/2019_if/paper.pdf
- https://github.com/sandraavila/pornographydatabase
- https://github.com/user-attachments/files/17451758/NPDI-Pornography-Database-License-Agreement.pdf
- https://www.crcv.ucf.edu/research/data-sets/ucf101/
- https://www.crcv.ucf.edu/THUMOS14/download.html
- https://arxiv.org/abs/1212.0402
- https://sites.google.com/uit.edu.vn/LSPD
- https://huggingface.co/datasets/yuwan0/Unsafe-VidGraph
- https://safewatch-aiguard.github.io/
- https://proceedings.iclr.cc/paper_files/paper/2025/file/beac6bfb7eac3d651307c16ac747df01-Paper-Conference.pdf
