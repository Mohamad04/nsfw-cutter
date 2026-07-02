# WindowsApplication QML Structure

This folder holds the editable frontend implementation. The older `components` and
`pages` folders mostly contain compatibility wrappers that forward to these files.

- `AppShell`: pages, headers, page layout, and top-level screen composition.
- `VideoPlayer`: video rendering, playback controls, timeline, subtitle popup,
  seek buttons, preview timeline, and cut mode selector.
- `CutList`: cut list panels, cut rows, selected cut details, totals, and export
  actions.
- `CutEditor`: current cut form, keyframe-safe cut info, and selected cut
  inspector.
- `Discovery`: AI pick list and discovered video list panels.
- `Settings`: settings dialog and theme toggle.
- `Shared`: reusable controls such as buttons, inputs, scrollbars, theme values,
  icon rendering, and simple panels.
