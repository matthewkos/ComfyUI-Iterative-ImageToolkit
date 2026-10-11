# Example workflows

- `iit_scale_1mp_text_save.json`: **IIT Load Version → Scale Image to Total Pixels (bilinear, 1.0 MP) → Draw Text Overlay → IIT Save Candidate Run**. The fixed example text is `01-edit/123456789`, positioned at the top-left. Change it manually for the step and seed being demonstrated. `IIT_META` also connects to **IIT View Trajectory**.

The Loader's mask, positive prompt, negative prompt, seed, and `IIT_META` connect directly to **IIT Save Candidate Run**, while the scaled and labelled image connects to its `images` input. The example uses ComfyUI core nodes for scaling and text overlay; it does not require an IIT image-label node.

The workflow references `example.png` as a placeholder. Choose or upload a real image in **IIT Load Version** before queueing.
