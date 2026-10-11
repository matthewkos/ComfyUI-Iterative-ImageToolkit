import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const CLASS_NAME = "IITLoadVersion";

const styleId = "iit-version-browser-style";
if (!document.getElementById(styleId)) {
  const style = document.createElement("link");
  style.id = styleId;
  style.rel = "stylesheet";
  style.href = new URL("./iterative-image-toolkit.css", import.meta.url).href;
  document.head.append(style);
}

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function value(node, name) {
  return widget(node, name)?.value ?? "";
}

function stepKey(node) {
  const index = String(Number(value(node, "step_idx"))).padStart(2, "0");
  const name = String(value(node, "step_name"))
    .trim()
    .replace(/[^A-Za-z0-9._ -]+/g, "-")
    .replace(/[ .-]+/g, "-")
    .replace(/^[ .-]+|[ .-]+$/g, "") || "step";
  return `${index}-${name}`;
}

async function fetchJson(url, options = {}) {
  const response = await api.fetchApi(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${response.status} ${response.statusText}`);
  return body;
}

function query(node, extras = {}) {
  return new URLSearchParams({
    project_name: value(node, "project_name"),
    storage_root: value(node, "storage_root"),
    step_key: stepKey(node),
    ...extras,
  });
}

function toast(severity, summary, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary, detail, life: 5000 });
}

function candidateUrl(node, candidateId) {
  return api.apiURL(`/iit/image?${query(node, { candidate_id: candidateId })}`);
}

function currentStep(manifest, node) {
  const step = manifest.steps?.[stepKey(node)];
  if (!step) throw new Error(`Step not found: ${stepKey(node)}`);
  return step;
}

function flattenCandidates(step) {
  return [...(step.runs || [])].reverse().flatMap((run) => [...(run.candidates || [])].reverse());
}

function currentCandidateId(step) {
  const version = (step.versions || []).find((item) => item.version_id === step.current_version_id);
  return version?.accepted_candidate_id || null;
}

function imageElement(node, id) {
  const image = document.createElement("img");
  image.src = candidateUrl(node, id);
  image.draggable = false;
  image.alt = id;
  return image;
}

function createViewer(node, ids, mode, roi) {
  const viewport = document.createElement("div");
  viewport.className = `iit-viewport iit-${mode}`;
  let scale = 1;
  let x = 0;
  let y = 0;
  let dragging = false;
  let startX = 0;
  let startY = 0;

  const stage = document.createElement("div");
  stage.className = "iit-stage";
  viewport.append(stage);

  const apply = () => {
    stage.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    const crop = roi?.enabled ? `inset(${roi.y}% ${100 - roi.x - roi.w}% ${100 - roi.y - roi.h}% ${roi.x}%)` : "none";
    stage.querySelectorAll("img").forEach((image) => (image.style.clipPath = crop));
  };

  if (mode === "slider") {
    const first = imageElement(node, ids[0]);
    const second = imageElement(node, ids[1] || ids[0]);
    first.className = "iit-base";
    second.className = "iit-overlay";
    stage.append(first, second);
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "100";
    slider.value = "50";
    slider.className = "iit-slider";
    slider.addEventListener("input", () => {
      second.style.clipPath = `inset(0 ${100 - Number(slider.value)}% 0 0)`;
    });
    viewport.append(slider);
  } else {
    stage.classList.add("iit-grid-stage");
    ids.slice(0, 4).forEach((id) => {
      const cell = document.createElement("figure");
      const image = imageElement(node, id);
      const caption = document.createElement("figcaption");
      caption.textContent = id;
      cell.append(image, caption);
      stage.append(cell);
    });
  }

  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    scale = Math.max(0.25, Math.min(8, scale * (event.deltaY < 0 ? 1.12 : 0.89)));
    apply();
  }, { passive: false });
  viewport.addEventListener("pointerdown", (event) => {
    if (event.target.tagName === "INPUT") return;
    dragging = true;
    startX = event.clientX - x;
    startY = event.clientY - y;
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    x = event.clientX - startX;
    y = event.clientY - startY;
    apply();
  });
  viewport.addEventListener("pointerup", () => (dragging = false));
  apply();
  return viewport;
}

async function openBrowser(node) {
  let manifest;
  try {
    manifest = await fetchJson(`/iit/manifest?${query(node)}`);
  } catch (error) {
    toast("error", "Iterative Image Toolkit", error.message);
    return;
  }
  const step = currentStep(manifest, node);
  const candidates = flattenCandidates(step);
  if (!candidates.length) {
    toast("warn", "No candidates", "Run IIT Save Candidate Run first.");
    return;
  }

  const dialog = document.createElement("dialog");
  dialog.className = "iit-dialog";
  const panel = document.createElement("div");
  panel.className = "iit-panel";
  dialog.append(panel);
  const header = document.createElement("header");
  header.innerHTML = `<div><strong>${manifest.project_name}</strong><small>${stepKey(node)}</small></div>`;
  const close = document.createElement("button");
  close.textContent = "Close";
  close.onclick = () => dialog.close();
  header.append(close);
  panel.append(header);

  const controls = document.createElement("section");
  controls.className = "iit-controls";
  const mode = document.createElement("select");
  mode.innerHTML = `<option value="slider">A/B slider</option><option value="grid">2–4 image grid</option>`;
  const selectA = document.createElement("select");
  const selectB = document.createElement("select");
  const candidateOptions = candidates.map((item) => `<option value="${item.candidate_id}">${item.candidate_id}</option>`).join("");
  selectA.innerHTML = candidateOptions;
  selectB.innerHTML = candidateOptions;
  const active = currentCandidateId(step);
  selectA.value = active || candidates[0].candidate_id;
  selectB.value = candidates.find((item) => item.candidate_id !== selectA.value)?.candidate_id || selectA.value;
  const roiToggle = document.createElement("label");
  roiToggle.innerHTML = `<input type="checkbox"> ROI % (x/y/w/h)`;
  const roiInputs = ["x", "y", "w", "h"].map((name, index) => {
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "100";
    input.value = [0, 0, 100, 100][index];
    input.title = name;
    return input;
  });
  controls.append(mode, selectA, selectB, roiToggle, ...roiInputs);
  panel.append(controls);

  const viewerHolder = document.createElement("main");
  panel.append(viewerHolder);
  const render = () => {
    const selected = mode.value === "grid"
      ? [selectA.value, selectB.value, ...candidates.map((item) => item.candidate_id).filter((id) => ![selectA.value, selectB.value].includes(id)).slice(0, 2)]
      : [selectA.value, selectB.value];
    const roi = {
      enabled: roiToggle.querySelector("input").checked,
      x: Number(roiInputs[0].value), y: Number(roiInputs[1].value),
      w: Number(roiInputs[2].value), h: Number(roiInputs[3].value),
    };
    viewerHolder.replaceChildren(createViewer(node, selected, mode.value, roi));
  };
  [mode, selectA, selectB, roiToggle, ...roiInputs].forEach((element) => element.addEventListener("change", render));
  render();

  const footer = document.createElement("footer");
  const accept = document.createElement("button");
  accept.textContent = "Set Current";
  const promote = document.createElement("button");
  promote.textContent = "Promote to Next Step";
  const mask = document.createElement("button");
  mask.textContent = "Stage for Mask Editor";
  const update = async (action) => {
    try {
      const result = await fetchJson("/iit/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: value(node, "project_name"), storage_root: value(node, "storage_root"),
          step_key: stepKey(node), candidate_id: selectA.value, action,
        }),
      });
      widget(node, "source").value = "current_version";
      refreshLoadControls(node);
      widget(node, "candidate_id").value = selectA.value;
      node.setDirtyCanvas(true, true);
      toast("success", action === "promote" ? "Version promoted" : "Current version set", result.version_id);
      dialog.close();
    } catch (error) {
      toast("error", "Update failed", error.message);
    }
  };
  accept.onclick = () => update("set_current");
  promote.onclick = () => update("promote");
  mask.onclick = async () => {
    try {
      const result = await fetchJson("/iit/stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: value(node, "project_name"), storage_root: value(node, "storage_root"), step_key: stepKey(node), candidate_id: selectA.value }),
      });
      await navigator.clipboard.writeText(result.image).catch(() => {});
      const imageWidget = widget(node, "image");
      const sourceWidget = widget(node, "source");
      if (imageWidget) {
        const values = imageWidget.options?.values;
        if (Array.isArray(values) && !values.includes(result.image)) values.push(result.image);
        const previous = imageWidget.value;
        imageWidget.value = result.image;
        imageWidget.callback?.(result.image, app.canvas, node, [0, 0], null);
        node.onWidgetChanged?.("image", result.image, previous, imageWidget);
      }
      if (sourceWidget) sourceWidget.value = "initial_image";
      refreshLoadControls(node);
      toast("info", "Staged in IIT Load Version", `${result.image} is now selected on this node. Open its preview/context menu and choose Open in Mask Editor.`);
    } catch (error) {
      toast("error", "Staging failed", error.message);
    }
  };
  footer.append(accept, promote, mask);
  panel.append(footer);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
}

function setWidgetEnabled(item, enabled) {
  if (!item) return;
  if (!item.options) item.options = {};
  item.options.disabled = !enabled;
  item.disabled = !enabled;
}

function refreshLoadControls(node) {
  const source = value(node, "source");
  const initial = source === "initial_image";
  ["image", "positive_prompt", "negative_prompt", "seed"].forEach((name) => setWidgetEnabled(widget(node, name), initial));
  setWidgetEnabled(widget(node, "candidate_id"), source === "candidate");
  node.setDirtyCanvas?.(true, true);
}

function refreshMetaControls(node) {
  const connected = node.inputs?.find((input) => input.name === "iit_meta")?.link != null;
  ["project_name", "step_idx", "step_name", "storage_root"].forEach((name) => setWidgetEnabled(widget(node, name), !connected));
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "iterative-image-toolkit.version-browser",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name === CLASS_NAME) {
      const original = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        original?.apply(this, arguments);
        const sourceWidget = widget(this, "source");
        const originalCallback = sourceWidget?.callback;
        if (sourceWidget) {
          sourceWidget.callback = (...args) => {
            const result = originalCallback?.apply(sourceWidget, args);
            refreshLoadControls(this);
            return result;
          };
        }
        this.addWidget("button", "Open Version Browser", null, () => openBrowser(this));
        this.size[0] = Math.max(this.size[0], 360);
        refreshLoadControls(this);
      };
      const configured = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        configured?.apply(this, arguments);
        refreshLoadControls(this);
      };
    }
    if (nodeData.name === "IITSaveCandidates") {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        created?.apply(this, arguments);
        refreshMetaControls(this);
      };
      const changed = nodeType.prototype.onConnectionsChange;
      nodeType.prototype.onConnectionsChange = function () {
        const result = changed?.apply(this, arguments);
        refreshMetaControls(this);
        return result;
      };
      const configured = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        configured?.apply(this, arguments);
        refreshMetaControls(this);
      };
    }
  },
  getNodeMenuItems(node) {
    if (node.comfyClass !== CLASS_NAME) return [];
    return [{ content: "Open Version Browser", callback: () => openBrowser(node) }];
  },
});
