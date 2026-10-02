# Local VLM Movie Analysis

Local VLM analysis creates timestamped, review-only NSFW suggestions for **AI Picks**.
It never cuts, exports, deletes, or uploads media automatically. Every suggestion has
`needs_review=true`; a user must inspect it and explicitly accept or reject it before it
can become a cut marker.

## Coarse-to-fine architecture

The production pipeline no longer sends regularly sampled frames from an entire movie
directly to Qwen. It uses a recall-oriented first pass and spends VLM time only on
candidate windows:

```text
video preflight + content fingerprint
  ├─ selected text subtitle, or FFmpeg audio -> faster-whisper + Silero VAD
  └─ coarse interval frames + scene-change frames
       -> pinned Marqo NSFW image prefilter
       -> merge, pad, and split candidate time windows
       -> dense sampling inside candidates only
       -> timestamped contact sheets
       -> Qwen compact grammar-constrained JSON
            └─ one text-only JSON repair when required
       -> atomic per-batch checkpoint
  -> visual/text evidence fusion
  -> review-only AI Picks
```

The Marqo prefilter is `Marqo/nsfw-image-detection-384`, pinned to revision
`0c26ec22111b83f106d72a55f611ec35962bcb65`. Its model weights are approximately
23 MB. It is a fast classifier and candidate gate, not the final decision maker. A
classifier error is handled conservatively within a scoring chunk; if the prefilter is
unavailable entirely, the production run is marked partial and does not fall back to
reviewing the whole movie with Qwen.

Candidate frames are grouped when they are close in time, padded for context, and split
into windows no longer than 30 seconds by default. Text evidence may seed or widen a
candidate window so Qwen can inspect it, but text alone never becomes final visual
evidence or a cut suggestion.

Dense frames are grouped into batches of four by default. Each batch becomes one
timestamped JPEG contact sheet with numbered 384-pixel panels. Qwen therefore receives
one compact image instead of several unrelated full-resolution images. Individual image
processing is additionally bounded to 128-256 Qwen visual tokens.

LangGraph supplies fixed orchestration only. There are no autonomous agents, model tool
calls, or tool-calling loops. FFmpeg, faster-whisper, the Marqo classifier, Qwen, fusion,
and cache persistence are ordinary application services invoked in a fixed order.

## Analysis modes

**Balanced** is the default for full movies. Select a mode under **Settings -> AI
Settings -> Analysis mode**.

| Mode | Coarse interval sampling | Dense candidate sampling | Prefilter gate | Intended use |
|---|---:|---:|---|---|
| Fast | 0.1 FPS (one frame/10 s) + scene changes | 0.5 FPS | Strong candidates (`0.45`) | Quick first look |
| Balanced | 0.2 FPS (one frame/5 s) + scene changes | 1 FPS | Candidate threshold (`0.15`) | Default movie scan |
| Thorough | 0.2 FPS (one frame/5 s) + scene changes | 2 FPS | Candidate threshold (`0.15`) | More detail inside candidates |

Scene-change sampling uses a `0.35` threshold in all three profiles unless an advanced
setting overrides it. Fast can miss more subtle or short events. Thorough increases work
inside candidate windows; it does not decode every frame of the complete movie.

Mode profiles are versioned and included in cache identities. Changing the mode, model,
prompt schema, sampling settings, or relevant thresholds causes the affected work to be
recomputed instead of reusing incompatible evidence.

## Models and GPU placement

The final provider is `Qwen/Qwen2.5-VL-3B-Instruct`, pinned to revision
`66285546d2b821cf421d4f5eb2576359d3770cd3`. Initial output categories are `nudity`,
`sexual_activity`, `sexual_context`, and `uncertain`.

GPU placement defaults to `ai_quantization_mode: "auto"`:

1. On CUDA, try bitsandbytes NF4 4-bit loading with the complete Qwen model on the GPU.
2. If automatic 4-bit initialization is unavailable or fails, use FP16 Accelerate
   placement, filling GPU memory first and offloading only overflow layers to system RAM.
3. If CUDA is disabled or unavailable, use the CPU implementation. This is supported but
   can be extremely slow and memory hungry.

Setting `ai_quantization_mode` to `"4bit"` makes 4-bit CUDA strict: missing or failed
bitsandbytes initialization becomes a clear error rather than a fallback. Setting it to
`"none"` selects FP16 GPU/CPU placement. The UI reports the actual result as **GPU**,
**GPU + CPU offload**, or **CPU**, together with the quantization name once Qwen is
loaded. The lightweight Marqo prefilter uses FP16 CUDA when available and FP32 CPU as a
fallback. Whisper independently uses CTranslate2 CUDA when its runtime is available and
otherwise retries with int8 CPU inference.

## Compact, reliable structured output

Qwen generation is deterministic and grammar-constrained with `lm-format-enforcer`.
The compact wire schema uses one-based frame numbers rather than asking the model to
copy floating-point timestamps. It permits at most four suggestions per batch and short
reasons; application code converts valid frame references back to batch timestamps and
then applies strict Pydantic validation.

The normal generation budget is 192 new tokens. If the first response still cannot be
validated, the provider performs one repair pass with a 128-token budget. That pass is
text-only: it receives the bounded candidate output and does not encode the contact
sheet again. A second malformed response fails that batch, is checkpointed, and does not
discard other successful batches.

The default 75-second per-batch deadline starts when batch review begins and is shared by
model setup, the first generation, and any repair. It is a **soft timeout** checked
before generation and between generated tokens. It cannot forcibly interrupt model
loading, a long native GPU kernel, driver stalls, or another third-party call that does
not return control to the stopping criterion. The first batch can therefore cross the
wall-clock deadline while model loading is still inside third-party code, then stop when
control returns.

## Install and run from source

Python 3.12 or newer and FFmpeg are required. Run these commands from the repository
root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# NVIDIA/CUDA build used by this project. Install it before requirements-ai.txt.
.\.venv\Scripts\python.exe -m pip install torch==2.13.0+cu130 torchvision==0.28.0+cu130 --index-url https://download.pytorch.org/whl/cu130

.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
.\.venv\Scripts\python.exe -m pip check
.\scripts\prepare_ffmpeg.ps1
```

If the machine cannot use the CUDA 13.0 wheel, install the matching `torch 2.13.0` and
`torchvision 0.28.0` pair from the [official PyTorch selector](https://pytorch.org/get-started/locally/), then install
`requirements-ai.txt`. Verify what the application will see:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

Model weights are not installed by either requirements file. Downloads are denied by
default. Explicitly permit lazy first-run downloads into the per-user model cache:

```powershell
$env:NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD = "1"
.\.venv\Scripts\python.exe main.py
```

Select a video, open **AI Picks**, and choose **Analyze video**. The Marqo prefilter is
needed on every uncached production analysis. Qwen is loaded when at least one candidate
batch needs review. The configured faster-whisper model is needed only when no readable
text subtitle is selected. Keep the opt-in set until the required models have been
cached, then close the app, remove the opt-in, and launch normally:

```powershell
Remove-Item Env:NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe main.py
```

Without the opt-in, a missing dependency or model produces a diagnostic and no network
download. To put all AI models on another drive, set an absolute writable directory
before both download and normal use:

```powershell
$env:NSFW_CUTTER_MODEL_CACHE = "D:\NSFW-Cutter-Models"
$env:NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD = "1"
.\.venv\Scripts\python.exe main.py
```

Relative model-cache paths and paths inside the source or installed application
directory are rejected.

## Result cache and per-batch resume

Nothing is written into the installation directory, and model weights are neither
committed to Git nor bundled in releases. Windows defaults are:

```text
Models       %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\models
Records      %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis\records\<analysis-key>.json
Checkpoints  %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis\checkpoints\<analysis-key>\<batch-key>.json
Prefilter    %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis\prefilter\<analysis-key>\<score-key>.json
Work         %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis\work\<job-id>
Logs         %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\logs\video-cut.log
```

Each completed or failed Qwen batch is written atomically. A batch key covers the
analysis cache identity, ordered frame timestamps, prompt-schema revision, and model
settings. On a later unchanged run, completed checkpoints are loaded without calling
Qwen again; failed batches are retried. A corrupt checkpoint is ignored in isolation.
Cancellation or a late failure cannot replace an already completed final record.

Resume currently avoids repeated Qwen inference for completed batches. Coarse sampling,
prefiltering, and temporary contact-sheet construction run again so the same stable
batches can be identified. Temporary frames, contact sheets, and extracted audio are
removed after normal completion, cancellation, or failure. A process crash can leave a
work directory for manual inspection or cleanup.

Final records contain fingerprints, resolved settings and revisions, media summary,
candidate windows, structured evidence, suggestions, aggregate metrics, provider device
diagnostics, warnings, errors, and timestamps. They do not contain the source media path
or full transcript.

Prefilter checkpoints contain path-free timestamp/probability pairs, and batch checkpoints
contain timestamps, the validated response or sanitized error, timing,
repair state, and bounded raw/repaired model output. Those short model outputs can still
describe sensitive content. They remain local, are not copied into final records or
logs, and should be treated as private when sharing a debug bundle.

## Progress and local monitoring

AI Picks reports the current stage and overall progress. During candidate review it also
shows the actual Qwen device/quantization, candidate count, completed/total batches,
resumed, repaired, and failed counts, plus an ETA after enough fresh batch durations are
available. ETA is an estimate based on recent batches and can change with workload or
GPU contention.

Follow the application log:

```powershell
Get-Content "$env:LOCALAPPDATA\MohamadElHajj\NSFW Cutter\logs\video-cut.log" -Wait
```

Monitor NVIDIA utilization and VRAM in another PowerShell window:

```powershell
nvidia-smi --query-gpu=timestamp,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv -l 1
```

Inspect the newest final record and batch checkpoint locally:

```powershell
$vlmCache = "$env:LOCALAPPDATA\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis"
$latestRecord = Get-ChildItem "$vlmCache\records" -Filter *.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestRecord) { Get-Content $latestRecord.FullName -Raw }

$latestBatch = Get-ChildItem "$vlmCache\checkpoints" -Recurse -Filter *.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestBatch) { Get-Content $latestBatch.FullName -Raw }
```

Inspect temporary sampled inputs while a run is active:

```powershell
Get-ChildItem "$vlmCache\work" -Recurse -File -Include *.jpg,*.wav | Sort-Object LastWriteTime -Descending
```

These files are local and may contain sensitive frames or audio. Do not upload them
without deliberately reviewing and redacting them.

## Privacy and optional LangSmith tracing

Media analysis is local by default. Raw video, sampled frames, contact sheets, audio,
subtitles, transcripts, local paths, prompts, and raw/repaired Qwen output are not sent
to LangSmith. Framework auto-tracing is suppressed so graph state cannot accidentally
serialize media. The application continues to work without LangSmith configuration.

To opt in to metadata-only developer tracing, configure `LANGSMITH_API_KEY` through the
standard LangSmith environment setup, then launch with:

```powershell
$env:NSFW_CUTTER_LANGSMITH_TRACING = "1"
$env:NSFW_CUTTER_LANGSMITH_PROJECT = "nsfw-cutter-vlm-development"
.\.venv\Scripts\python.exe main.py
```

Only allowlisted, redacted metadata is traced: fingerprints, media duration/FPS, model
identifiers and revisions, stage timings, frame/candidate/batch/suggestion counts,
scores, evidence timestamps, repair/resume/failure counts, status, and sanitized error
types. Unset the opt-in to return to offline behavior:

```powershell
Remove-Item Env:NSFW_CUTTER_LANGSMITH_TRACING -ErrorAction SilentlyContinue
```

## Limitations

- Sampling and a lightweight classifier are deliberate speed/recall tradeoffs. Events
  between coarse samples, weak prefilter positives, or unusual imagery can be missed.
- Qwen sees still contact-sheet panels, not continuous motion. Temporal interpretation
  can therefore be wrong even when the sampled frames are correct.
- Classification is not a safety guarantee. False positives and false negatives remain;
  manual review is mandatory.
- Text can request visual inspection of a time range, but cannot prove visual content or
  create a final suggestion by itself.
- Runtime scales mainly with candidate duration and candidate count, but scene density,
  decoding speed, subtitles/Whisper, GPU, VRAM, quantization availability, and content
  all affect it. The repository does not currently establish a measured two-hour movie
  runtime or SLA.
- The 75-second deadline is cooperative, not a hard process kill. Model loading and some
  native CUDA operations may exceed it before returning control.
- Automatic 4-bit support depends on CUDA, bitsandbytes, the driver, and the GPU. The
  FP16 hybrid fallback can be much slower because layers cross between GPU and RAM.
- CPU Qwen analysis is available but generally unsuitable for long movies.
- Initial model downloads require network access and substantial disk space. There is no
  in-app model manager; downloads require the explicit environment opt-in.
- Cancellation cannot interrupt every third-party model-loading call immediately.
- Resume reuses classifier scores and completed Qwen calls. FFmpeg still recreates
  temporary sampled frames, and text/Whisper evidence is not yet independently cached.

## Performance and manual test checklist

Install developer test tools, then run the exact CI-style checks:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest ruff
.\.venv\Scripts\ruff.exe check . --select E4,E7,E9,F
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Run the focused analysis suite during VLM work:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_analysis_contracts.py tests/test_analysis_prefilter.py tests/test_analysis_structured_output.py tests/test_analysis_qwen_provider.py tests/test_analysis_checkpoints.py tests/test_analysis_pipeline.py tests/test_analysis_scalability.py tests/test_vlm_analysis_integration.py -q
```

Manual checks:

- Verify `torch.cuda.is_available()` and the GPU name with the command in the source setup
  section; confirm AI Picks later reports the actual Qwen placement.
- With downloads disabled and an empty model cache, confirm the app reports a clear
  missing-model diagnostic instead of accessing the network.
- With explicit download opt-in, analyze deterministic 2-minute, 30-minute, and 2-hour
  test media in Balanced mode. Record `started_at`, `completed_at`, candidate/batch
  counts, repaired/failed counts, device, and quantization from the final JSON. This is a
  benchmark procedure, not a claimed two-hour runtime.
- Use mostly safe and candidate-heavy media. Confirm Qwen batch count follows candidate
  windows rather than total movie duration.
- Compare Fast, Balanced, and Thorough on the same unchanged test media. Confirm the
  expected coarse/dense sampling profiles and that their cache identities differ.
- Cancel after at least one Qwen batch completes, rerun unchanged, and confirm **Resumed**
  is nonzero and the completed batch is not inferred again.
- Force or mock malformed JSON. Confirm grammar enforcement or one text-only repair
  yields valid compact output; otherwise only that batch fails and its local checkpoint
  contains bounded diagnostics.
- Analyze with a readable selected subtitle and without one to exercise both subtitle and
  Whisper paths. Confirm text-only evidence never becomes a final suggestion.
- Confirm every published suggestion remains pending review; edit/accept one and reject
  another deliberately. Verify no cut or export happens before acceptance.
- Leave LangSmith tracing disabled and confirm no trace is created. When explicitly
  enabled, inspect the trace and verify it contains metadata only—no paths, prompts,
  transcripts, frames, contact sheets, or raw model output.
