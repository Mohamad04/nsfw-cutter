# Release-candidate screenshot evidence

These screenshots record the final physical-monitor release-candidate smoke of the
packaged Windows application. They are documentation evidence only; model weights,
temporary logs, benchmark caches, and runtime caches are intentionally excluded.

| File | Evidence |
|---|---|
| `01-video-manual-cut.png` | A real decoded video frame is visible in the packaged player, with the manual cut workflow and cut-list entry present. |
| `02-ai-picks-ready.png` | AI Picks reports the already provisioned production models ready and exposes the enabled Analyze action without downloading model weights. |
| `03-analysis-progress.png` | The packaged analysis is running through candidate batches and reporting progress/checkpoint state. |
| `04-analysis-partial-result.png` | A model-output validation warning is handled as a partial analysis result while the application remains responsive and preserves the manual editing fallback. |
| `05-smart-export-success.png` | Smart Export completed successfully and displayed its success details, output duration, and FFmpeg execution summary. |

The screenshots were copied byte-for-byte from the temporary files captured during the
approved final smoke; no image processing or alteration was applied.
