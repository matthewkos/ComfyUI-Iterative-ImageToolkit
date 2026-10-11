# Changelog

## Unreleased

- Make IIT Load Version a Load Image replacement with initial upload, manual prompts/seed, saved-source restoration, and IIT_META.
- Let IIT Save Candidate Run consume IIT_META and disable overridden project widgets.
- Require descriptions for nodes, inputs, outputs, conditional inputs, and custom datatypes.
- Update the example workflow to use ComfyUI core Scale Image to Total Pixels at 1.0 MP, followed by Draw Text Overlay and candidate saving.
- Remove the IIT Add Step / Seed Label custom node; the example now uses the core text-overlay node.

## 0.1.0

- Add run/candidate/project manifest model with sidecar JSON.
- Add accepted-version and promote-to-next-step operations.
- Add optional prompt, negative prompt, seed, and mask round-trip.
- Add slider/grid version browser with synchronized pan/zoom and ROI.
- Add native Mask Editor staging flow.
- Add robust edited-crop locator and diagnostics.
