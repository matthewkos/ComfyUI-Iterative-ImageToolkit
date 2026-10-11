import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const LOAD_CLASS = "IITLoadVersion";
const TRAJECTORY_CLASS = "IITViewTrajectory";
const styleId = "iit-version-browser-style";
if (!document.getElementById(styleId)) {
  const style = document.createElement("link");
  style.id = styleId;
  style.rel = "stylesheet";
  style.href = new URL("./iterative-image-toolkit.css", import.meta.url).href;
  document.head.append(style);
}

function widget(node, name) { return node.widgets?.find((item) => item.name === name); }
function value(node, name) { return widget(node, name)?.value ?? ""; }
function setValue(node, name, next) {
  const item = widget(node, name);
  if (!item) return;
  const previous = item.value;
  item.value = next;
  item.callback?.(next, app.canvas, node, [0, 0], null);
  node.onWidgetChanged?.(name, next, previous, item);
}
function slug(valueToSlug) {
  return String(valueToSlug).trim().replace(/[^A-Za-z0-9._ -]+/g, "-")
    .replace(/[ .-]+/g, "-").replace(/^[ .-]+|[ .-]+$/g, "") || "step";
}
function stepKey(node) { return `${String(Number(value(node, "step_idx"))).padStart(2, "0")}-${slug(value(node, "step_name"))}`; }
async function fetchJson(url, options = {}) {
  const response = await api.fetchApi(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${response.status} ${response.statusText}`);
  return body;
}
function toast(severity, summary, detail) { app.extensionManager?.toast?.add?.({ severity, summary, detail, life: 6000 }); }
function projectQuery(node, extras = {}) {
  return new URLSearchParams({ project_name: value(node, "project_name"), storage_root: value(node, "storage_root"), ...extras });
}
function candidateUrl(node, candidateId, key = stepKey(node)) {
  return api.apiURL(`/iit/image?${projectQuery(node, { step_key: key, candidate_id: candidateId })}`);
}
function currentStep(manifest, node) {
  const step = manifest.steps?.[stepKey(node)];
  if (!step) throw new Error(`Step not found: ${stepKey(node)}`);
  return step;
}
function flattenCandidates(step) { return [...(step.runs || [])].reverse().flatMap((run) => [...(run.candidates || [])].reverse()); }
function currentCandidateId(step) {
  return (step.versions || []).find((item) => item.version_id === step.current_version_id)?.accepted_candidate_id || null;
}
function promotedIds(step) {
  return new Set((step.versions || []).filter((item) => item.promoted_to_step_key).map((item) => item.accepted_candidate_id));
}
function candidateLabel(candidate, currentId, promoted, letter = "") {
  const tags = [];
  if (candidate.candidate_id === currentId) tags.push("CURRENT");
  if (promoted.has(candidate.candidate_id)) tags.push("PROMOTED");
  return `${letter ? `${letter} · ` : ""}${candidate.candidate_id}${tags.length ? ` · ${tags.join(" · ")}` : ""}`;
}
function labelledControl(label, control) {
  const wrapper = document.createElement("label");
  wrapper.className = "iit-control";
  const title = document.createElement("span");
  title.textContent = label;
  wrapper.append(title, control);
  return wrapper;
}
function makeImage(src, alt) {
  const image = document.createElement("img");
  image.src = src;
  image.alt = alt;
  image.draggable = false;
  return image;
}
function makeBadge(text, className = "") {
  const badge = document.createElement("span");
  badge.className = `iit-badge ${className}`.trim();
  badge.textContent = text;
  return badge;
}

function createViewer(node, selected, mode, roi, candidates, currentId, promoted, onChooseA) {
  const byId = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const viewport = document.createElement("div");
  viewport.className = `iit-viewport iit-${mode}`;
  const stage = document.createElement("div");
  stage.className = "iit-stage";
  viewport.append(stage);
  let scale = 1, x = 0, y = 0, dragging = false, startX = 0, startY = 0;
  const crop = roi.enabled ? `inset(${roi.y}% ${100 - roi.x - roi.w}% ${100 - roi.y - roi.h}% ${roi.x}%)` : "none";
  const apply = () => { stage.style.transform = `translate(${x}px, ${y}px) scale(${scale})`; };

  if (mode === "slider") {
    const a = byId.get(selected[0]);
    const b = byId.get(selected[1]) || a;
    const imageB = makeImage(candidateUrl(node, b.candidate_id), b.candidate_id);
    const imageA = makeImage(candidateUrl(node, a.candidate_id), a.candidate_id);
    imageB.className = "iit-base";
    imageA.className = "iit-overlay";
    imageB.style.clipPath = crop;
    imageA.dataset.roiClip = crop;
    stage.append(imageB, imageA);
    const labels = document.createElement("div");
    labels.className = "iit-viewer-labels";
    const left = makeBadge(candidateLabel(a, currentId, promoted, "A"), "iit-action-badge");
    const right = makeBadge(candidateLabel(b, currentId, promoted, "B"));
    labels.append(left, right);
    const slider = document.createElement("input");
    slider.type = "range"; slider.min = "0"; slider.max = "100"; slider.value = "50"; slider.className = "iit-slider";
    slider.title = "Left side is A; right side is B";
    slider.addEventListener("input", () => {
      const split = Number(slider.value);
      imageA.style.clipPath = roi.enabled
        ? `polygon(${roi.x}% ${roi.y}%, ${Math.min(roi.x + roi.w, split)}% ${roi.y}%, ${Math.min(roi.x + roi.w, split)}% ${roi.y + roi.h}%, ${roi.x}% ${roi.y + roi.h}%)`
        : `inset(0 ${100 - split}% 0 0)`;
    });
    slider.dispatchEvent(new Event("input"));
    viewport.append(labels, slider);
  } else {
    stage.classList.add("iit-grid-stage");
    selected.forEach((id, index) => {
      const candidate = byId.get(id);
      if (!candidate) return;
      const letter = "ABCD"[index];
      const cell = document.createElement("figure");
      if (index === 0) cell.classList.add("iit-action-target");
      cell.title = index === 0 ? "Action target A" : `Click to swap ${letter} into action target A`;
      const image = makeImage(candidateUrl(node, id), id);
      image.style.clipPath = crop;
      const caption = document.createElement("figcaption");
      const line = document.createElement("strong");
      line.textContent = `${letter} · ${id}`;
      const details = document.createElement("span");
      details.textContent = `Seed: ${candidate.seed ?? "unknown"}`;
      caption.append(line, details);
      if (id === currentId) caption.append(makeBadge("CURRENT", "iit-current-badge"));
      if (promoted.has(id)) caption.append(makeBadge("PROMOTED", "iit-promoted-badge"));
      if (index === 0) caption.append(makeBadge("ACTION TARGET", "iit-action-badge"));
      cell.append(image, caption);
      cell.addEventListener("click", (event) => { if (!dragging && index > 0) onChooseA(index); });
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
    dragging = false;
    startX = event.clientX - x; startY = event.clientY - y;
    viewport.dataset.pointerStart = `${event.clientX},${event.clientY}`;
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!viewport.hasPointerCapture(event.pointerId)) return;
    const [px, py] = (viewport.dataset.pointerStart || "0,0").split(",").map(Number);
    if (Math.hypot(event.clientX - px, event.clientY - py) > 4) dragging = true;
    if (!dragging) return;
    x = event.clientX - startX; y = event.clientY - startY; apply();
  });
  viewport.addEventListener("pointerup", (event) => { if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId); setTimeout(() => { dragging = false; }, 0); });
  apply();
  return viewport;
}

function openPromoteDialog(node, selectedCandidate) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "iit-mini-dialog";
    const form = document.createElement("form");
    form.method = "dialog";
    const nextIndex = Number(value(node, "step_idx")) + 1;
    form.innerHTML = `<h2>Accept A & Send to Next Step</h2><p><strong>Source:</strong> ${stepKey(node)}</p><p><strong>Candidate A:</strong> ${selectedCandidate}</p>`;
    const index = document.createElement("input"); index.type = "number"; index.min = "1"; index.value = String(nextIndex);
    const name = document.createElement("input"); name.type = "text"; name.value = `step-${nextIndex}`; name.placeholder = "e.g. reshape";
    const fields = document.createElement("div"); fields.className = "iit-promote-fields";
    fields.append(labelledControl("Next step index", index), labelledControl("Next step name", name));
    const actions = document.createElement("footer");
    const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Cancel";
    const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Accept & Promote"; submit.className = "iit-primary";
    actions.append(cancel, submit); form.append(fields, actions); dialog.append(form); document.body.append(dialog);
    let completed = false;
    cancel.onclick = () => dialog.close("cancel");
    form.onsubmit = (event) => {
      event.preventDefault();
      if (!name.value.trim()) { name.focus(); return; }
      completed = true;
      resolve({ target_step_idx: Number(index.value), target_step_name: name.value.trim() });
      dialog.close("confirm");
    };
    dialog.addEventListener("close", () => { if (!completed) resolve(null); dialog.remove(); });
    dialog.showModal();
  });
}

async function openBrowser(node) {
  let manifest;
  try { manifest = await fetchJson(`/iit/manifest?${projectQuery(node)}`); }
  catch (error) { toast("error", "Iterative Image Toolkit", error.message); return; }
  let step;
  try { step = currentStep(manifest, node); }
  catch (error) { toast("error", "Version Browser", error.message); return; }
  const candidates = flattenCandidates(step);
  if (!candidates.length) { toast("warn", "No candidates", "Run IIT Save Candidate Run first."); return; }
  const currentId = currentCandidateId(step);
  const promoted = promotedIds(step);
  const options = candidates.map((item) => `<option value="${item.candidate_id}">${candidateLabel(item, currentId, promoted)}</option>`).join("");

  const dialog = document.createElement("dialog"); dialog.className = "iit-dialog";
  const panel = document.createElement("div"); panel.className = "iit-panel"; dialog.append(panel);
  const header = document.createElement("header"); header.className = "iit-header";
  const heading = document.createElement("div"); heading.innerHTML = `<strong>${manifest.project_name}</strong><small>${stepKey(node)}</small>`;
  const close = document.createElement("button"); close.textContent = "Close"; close.onclick = () => dialog.close();
  header.append(heading, close); panel.append(header);

  const controls = document.createElement("section"); controls.className = "iit-controls";
  const mode = document.createElement("select"); mode.innerHTML = `<option value="slider">A/B slider</option><option value="grid">Image grid</option>`;
  const count = document.createElement("select"); count.innerHTML = `<option value="2">2 images</option><option value="3">3 images</option><option value="4">4 images</option>`; count.value = String(Math.min(4, Math.max(2, candidates.length)));
  const selectors = "ABCD".split("").map(() => { const select = document.createElement("select"); select.innerHTML = options; return select; });
  selectors[0].value = currentId || candidates[0].candidate_id;
  const used = new Set([selectors[0].value]);
  for (let index = 1; index < 4; index += 1) {
    const next = candidates.find((candidate) => !used.has(candidate.candidate_id))?.candidate_id || selectors[0].value;
    selectors[index].value = next; used.add(next);
  }
  const roiToggle = document.createElement("input"); roiToggle.type = "checkbox";
  const roiInputs = [0, 0, 100, 100].map((initial, index) => { const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.max = "100"; input.value = String(initial); input.title = ["x", "y", "width", "height"][index]; return input; });
  controls.append(labelledControl("View", mode), labelledControl("Grid count", count));
  selectors.forEach((select, index) => controls.append(labelledControl("ABCD"[index], select)));
  controls.append(labelledControl("ROI", roiToggle));
  roiInputs.forEach((input, index) => controls.append(labelledControl(["x", "y", "w", "h"][index], input)));
  panel.append(controls);

  const comparisonLabels = document.createElement("section"); comparisonLabels.className = "iit-comparison-labels"; panel.append(comparisonLabels);
  const viewerHolder = document.createElement("main"); panel.append(viewerHolder);
  const actionStatus = document.createElement("div"); actionStatus.className = "iit-action-status";
  const footer = document.createElement("footer"); footer.className = "iit-footer";
  const mask = document.createElement("button"); mask.textContent = "Stage A for Mask Editor";
  const accept = document.createElement("button"); accept.textContent = "Accept A as Current Version";
  const promote = document.createElement("button"); promote.textContent = "Accept A & Send to Next Step…"; promote.className = "iit-primary";
  footer.append(actionStatus, mask, accept, promote); panel.append(footer);

  const render = () => {
    const isGrid = mode.value === "grid";
    count.closest("label").hidden = !isGrid;
    selectors.forEach((select, index) => { select.closest("label").hidden = index >= (isGrid ? Number(count.value) : 2); });
    const selected = selectors.slice(0, isGrid ? Number(count.value) : 2).map((select) => select.value);
    const byId = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
    comparisonLabels.replaceChildren(
      makeBadge(candidateLabel(byId.get(selectors[0].value), currentId, promoted, "A"), "iit-action-badge"),
      makeBadge(candidateLabel(byId.get(selectors[1].value), currentId, promoted, "B")),
    );
    actionStatus.textContent = `Actions apply to A only: ${selectors[0].value}`;
    const roi = { enabled: roiToggle.checked, x: Number(roiInputs[0].value), y: Number(roiInputs[1].value), w: Number(roiInputs[2].value), h: Number(roiInputs[3].value) };
    const swapIntoA = (index) => { const oldA = selectors[0].value; selectors[0].value = selectors[index].value; selectors[index].value = oldA; render(); };
    viewerHolder.replaceChildren(createViewer(node, selected, mode.value, roi, candidates, currentId, promoted, swapIntoA));
  };
  [mode, count, ...selectors, roiToggle, ...roiInputs].forEach((element) => element.addEventListener("change", render));
  render();

  const update = async (action, destination = null) => {
    try {
      const result = await fetchJson("/iit/accept", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: value(node, "project_name"), storage_root: value(node, "storage_root"), step_key: stepKey(node), candidate_id: selectors[0].value, action, ...(destination || {}) }),
      });
      if (action === "promote") {
        setValue(node, "step_idx", result.target_step.step_idx);
        setValue(node, "step_name", result.target_step.step_name);
        setValue(node, "source", "promoted_input");
        setValue(node, "candidate_id", "");
        toast("success", "Version promoted", `${result.version_id} → ${result.target_step.step_key}; source set to promoted_input.`);
      } else {
        setValue(node, "source", "current_version");
        setValue(node, "candidate_id", selectors[0].value);
        toast("success", "Current version accepted", result.version_id);
      }
      refreshLoadControls(node); node.setDirtyCanvas(true, true); dialog.close();
    } catch (error) { toast("error", "Update failed", error.message); }
  };
  accept.onclick = () => update("set_current");
  promote.onclick = async () => { const destination = await openPromoteDialog(node, selectors[0].value); if (destination) await update("promote", destination); };
  mask.onclick = async () => {
    try {
      const result = await fetchJson("/iit/stage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_name: value(node, "project_name"), storage_root: value(node, "storage_root"), step_key: stepKey(node), candidate_id: selectors[0].value }) });
      await navigator.clipboard.writeText(result.image).catch(() => {});
      const imageWidget = widget(node, "image");
      if (imageWidget) {
        const values = imageWidget.options?.values;
        if (Array.isArray(values) && !values.includes(result.image)) values.push(result.image);
        setValue(node, "image", result.image);
      }
      setValue(node, "source", "initial_image"); refreshLoadControls(node);
      toast("info", "Staged in IIT Load Version", `${result.image} is selected. Open this node's image in Mask Editor.`);
    } catch (error) { toast("error", "Staging failed", error.message); }
  };
  document.body.append(dialog); dialog.addEventListener("close", () => dialog.remove()); dialog.showModal();
}

function linkedMetaSource(node) {
  const input = node.inputs?.find((item) => item.name === "iit_meta");
  const link = input?.link != null ? app.graph?.links?.[input.link] : null;
  return link ? app.graph?.getNodeById?.(link.origin_id) : null;
}
function projectNode(node) { return linkedMetaSource(node) || node; }
async function openTrajectory(node) {
  const source = projectNode(node);
  try {
    const trajectory = await fetchJson(`/iit/trajectory?${projectQuery(source)}`);
    const dialog = document.createElement("dialog"); dialog.className = "iit-trajectory-dialog";
    const panel = document.createElement("div"); panel.className = "iit-trajectory-panel";
    const header = document.createElement("header");
    header.innerHTML = `<div><strong>${trajectory.project_name || value(source, "project_name")}</strong><small>Selected image trajectory</small></div>`;
    const close = document.createElement("button"); close.textContent = "Close"; close.onclick = () => dialog.close(); header.append(close);
    const timeline = document.createElement("main"); timeline.className = "iit-timeline";
    const showMetadata = Boolean(value(node, "show_metadata"));
    const thumbSize = Number(value(node, "thumbnail_size")) || 220;
    trajectory.entries.forEach((entry, index) => {
      const card = document.createElement("article"); card.className = `iit-trajectory-card iit-status-${entry.status}`; card.style.setProperty("--iit-thumb", `${thumbSize}px`);
      const title = document.createElement("h3");
      title.textContent = entry.kind === "initial" ? "Initial Image" : `Step ${entry.step_idx} · ${entry.step_name}`;
      card.append(title);
      if (entry.kind === "initial" && entry.image) card.append(makeImage(api.apiURL(`/iit/initial-image?${projectQuery(source)}`), entry.image));
      else if (entry.kind === "version") card.append(makeImage(candidateUrl(source, entry.candidate_id, entry.step_key), entry.candidate_id));
      else { const missing = document.createElement("div"); missing.className = "iit-missing-image"; missing.textContent = "Initial image metadata unavailable"; card.append(missing); }
      const status = entry.status === "pending" ? "CURRENT · NOT PROMOTED" : entry.status === "promoted" ? "PROMOTED" : entry.status.toUpperCase();
      card.append(makeBadge(status, entry.status === "pending" ? "iit-pending-badge" : "iit-promoted-badge"));
      if (entry.kind === "version") {
        const identity = document.createElement("code"); identity.textContent = `${entry.version_id} · ${entry.candidate_id}`; card.append(identity);
        if (showMetadata) {
          const meta = document.createElement("p");
          const prompt = String(entry.positive_prompt || "").slice(0, 100);
          meta.textContent = `Seed: ${entry.seed ?? "unknown"}${prompt ? ` · ${prompt}` : ""}`; card.append(meta);
        }
      }
      timeline.append(card);
      if (index < trajectory.entries.length - 1) { const arrow = document.createElement("div"); arrow.className = "iit-trajectory-arrow"; arrow.textContent = "→"; timeline.append(arrow); }
    });
    panel.append(header, timeline); dialog.append(panel); document.body.append(dialog);
    dialog.addEventListener("close", () => dialog.remove()); dialog.showModal();
  } catch (error) { toast("error", "Trajectory unavailable", error.message); }
}

function setWidgetEnabled(item, enabled) { if (!item) return; if (!item.options) item.options = {}; item.options.disabled = !enabled; item.disabled = !enabled; }
function refreshLoadControls(node) {
  const initial = value(node, "source") === "initial_image";
  ["image", "positive_prompt", "negative_prompt", "seed"].forEach((name) => setWidgetEnabled(widget(node, name), initial));
  setWidgetEnabled(widget(node, "candidate_id"), value(node, "source") === "candidate");
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
    if (nodeData.name === LOAD_CLASS) {
      const original = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        original?.apply(this, arguments);
        const sourceWidget = widget(this, "source");
        const originalCallback = sourceWidget?.callback;
        if (sourceWidget) sourceWidget.callback = (...args) => { const result = originalCallback?.apply(sourceWidget, args); refreshLoadControls(this); return result; };
        this.addWidget("button", "Open Version Browser", null, () => openBrowser(this));
        this.size[0] = Math.max(this.size[0], 380); refreshLoadControls(this);
      };
      const configured = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () { configured?.apply(this, arguments); refreshLoadControls(this); };
    }
    if (nodeData.name === "IITSaveCandidates" || nodeData.name === TRAJECTORY_CLASS) {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        created?.apply(this, arguments); refreshMetaControls(this);
        if (nodeData.name === TRAJECTORY_CLASS) this.addWidget("button", "Open Trajectory", null, () => openTrajectory(this));
      };
      const changed = nodeType.prototype.onConnectionsChange;
      nodeType.prototype.onConnectionsChange = function () { const result = changed?.apply(this, arguments); refreshMetaControls(this); return result; };
      const configured = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () { configured?.apply(this, arguments); refreshMetaControls(this); };
    }
  },
  getNodeMenuItems(node) {
    if (node.comfyClass === LOAD_CLASS) return [{ content: "Open Version Browser", callback: () => openBrowser(node) }];
    if (node.comfyClass === TRAJECTORY_CLASS) return [{ content: "Open Trajectory", callback: () => openTrajectory(node) }];
    return [];
  },
});
