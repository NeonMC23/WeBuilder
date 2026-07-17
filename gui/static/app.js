"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const clone = (value) => structuredClone(value);
const pathKey = (path) => path.join(".");
const arraysEqual = (left, right) => left.length === right.length && left.every((item, index) => item === right[index]);
const isPrefix = (prefix, value) => prefix.length <= value.length && prefix.every((item, index) => item === value[index]);

const state = {
  config: null,
  catalog: [],
  catalogByType: new Map(),
  themes: [],
  plugins: [],
  assets: [],
  status: null,
  currentPage: 0,
  selection: null,
  history: [],
  future: [],
  collapsed: new Set(),
  dirty: false,
  building: false,
  revision: 0,
  saveTimer: null,
  savePromise: null,
  lastLogs: [],
};

async function api(path, options = {}) {
  const request = { ...options, headers: { Accept: "application/json", ...(options.headers || {}) } };
  if (request.body && !(request.body instanceof FormData) && typeof request.body !== "string") {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(path, request);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The server returned an invalid response (${response.status}).`);
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed with status ${response.status}.`);
  }
  return payload;
}

function normalizeConfig(config) {
  const next = config && typeof config === "object" && !Array.isArray(config) ? config : {};
  if (!next.meta || typeof next.meta !== "object" || Array.isArray(next.meta)) next.meta = {};
  if (!Array.isArray(next.assets)) next.assets = [];
  if (!Array.isArray(next.pages)) next.pages = [];
  next.pages.forEach((page, index) => {
    if (!page || typeof page !== "object" || Array.isArray(page)) next.pages[index] = { path: `page-${index + 1}.html`, components: [] };
    if (!Array.isArray(next.pages[index].components)) next.pages[index].components = [];
  });
  return next;
}

function currentPage() {
  return state.config?.pages?.[state.currentPage] || null;
}

function getChildrenArray(parentPath = [], pageIndex = state.currentPage) {
  const page = state.config?.pages?.[pageIndex];
  if (!page) return null;
  let items = page.components;
  for (const index of parentPath) {
    const component = items?.[index];
    if (!component) return null;
    if (!Array.isArray(component.children)) component.children = [];
    items = component.children;
  }
  return items;
}

function getComponent(path = state.selection, pageIndex = state.currentPage) {
  if (!Array.isArray(path) || !path.length) return null;
  const parent = getChildrenArray(path.slice(0, -1), pageIndex);
  return parent?.[path.at(-1)] || null;
}

function getDefinition(type) {
  return state.catalogByType.get(type) || null;
}

function getVariantDefinition(type, variantName) {
  const definition = getDefinition(type);
  if (!definition) return null;
  return definition.variants.find((variant) => variant.name === variantName)
    || definition.variants.find((variant) => variant.name === definition.defaultVariant)
    || definition.variants[0]
    || null;
}

function createComponent(type) {
  const definition = getDefinition(type);
  const variantName = definition?.defaultVariant || definition?.variants?.[0]?.name || "default";
  const variant = getVariantDefinition(type, variantName);
  const defaults = clone(variant?.defaults || definition?.defaults || {});
  const component = { ...defaults, type, variant: variantName };
  if (!component.content || typeof component.content !== "object" || Array.isArray(component.content)) component.content = {};
  for (const requiredPath of variant?.required || definition?.required || []) {
    if (!requiredPath.startsWith("content.")) continue;
    const key = requiredPath.slice("content.".length);
    if (!(key in component.content)) {
      component.content[key] = /(?:items|lines|options|headers|rows|features|slides|images|members|pages|columns)$/.test(key) ? [] : "";
    }
  }
  if (definition?.acceptsChildren !== false && !Array.isArray(component.children)) component.children = [];
  return component;
}

function snapshot() {
  return JSON.stringify(state.config);
}

function setDirty(dirty, label = "") {
  state.dirty = dirty;
  const dot = $("#document-status-dot");
  const text = $("#document-status");
  dot.className = "status-dot";
  if (dirty) {
    dot.classList.add("is-dirty");
    text.textContent = label || "Unsaved changes";
  } else {
    dot.classList.add("is-saved");
    text.textContent = label || "Saved";
  }
}

function commit(label, mutator, { render = true } = {}) {
  if (!state.config) return;
  const before = snapshot();
  mutator();
  const after = snapshot();
  if (before === after) return;
  state.history.push({ config: before, label });
  if (state.history.length > 60) state.history.shift();
  state.future = [];
  setDirty(true, label);
  if (render) renderAll();
  updateHistoryButtons();
  scheduleSave();
}

function restoreSnapshot(serialized, label) {
  state.config = normalizeConfig(JSON.parse(serialized));
  state.currentPage = Math.min(state.currentPage, Math.max(0, state.config.pages.length - 1));
  state.selection = null;
  setDirty(true, label);
  renderAll();
  scheduleSave();
}

function undo() {
  const entry = state.history.pop();
  if (!entry) return;
  state.future.push({ config: snapshot(), label: entry.label });
  restoreSnapshot(entry.config, `Undo: ${entry.label}`);
  updateHistoryButtons();
}

function redo() {
  const entry = state.future.pop();
  if (!entry) return;
  state.history.push({ config: snapshot(), label: entry.label });
  restoreSnapshot(entry.config, `Redo: ${entry.label}`);
  updateHistoryButtons();
}

function updateHistoryButtons() {
  $("#undo-button").disabled = !state.history.length;
  $("#redo-button").disabled = !state.future.length;
}

function scheduleSave() {
  clearTimeout(state.saveTimer);
  const shouldSave = $("#autosave-toggle").checked || $("#live-build-toggle").checked;
  if (!shouldSave) return;
  state.saveTimer = setTimeout(async () => {
    try {
      await saveNow(true);
      if ($("#live-build-toggle").checked) await runBuild({ quiet: true });
    } catch (error) {
      showToast(error.message, "error");
    }
  }, 850);
}

async function saveNow(silent = false) {
  clearTimeout(state.saveTimer);
  if (state.savePromise) return state.savePromise;
  state.savePromise = api("/api/save", { method: "POST", body: { config: state.config } })
    .then((payload) => {
      state.config = normalizeConfig(payload.config);
      setDirty(false, "Saved");
      if (!silent) showToast("build.json saved", "success");
      return payload;
    })
    .catch((error) => {
      const dot = $("#document-status-dot");
      dot.className = "status-dot is-error";
      $("#document-status").textContent = "Save failed";
      throw error;
    })
    .finally(() => { state.savePromise = null; });
  return state.savePromise;
}

function setBusy(active, message = "Working…") {
  $("#busy-message").textContent = message;
  $("#busy-overlay").hidden = !active;
  $("#save-button").disabled = active;
  $("#build-button").disabled = active;
  $("#preview-button").disabled = active;
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  $("#toast-region").append(toast);
  setTimeout(() => toast.remove(), 3600);
}

function switchTab(side, name) {
  $$(`[data-${side}-tab]`).forEach((button) => button.classList.toggle("is-active", button.dataset[`${side}Tab`] === name));
  $$(`[data-${side}-panel]`).forEach((panel) => panel.classList.toggle("is-active", panel.dataset[`${side}Panel`] === name));
  if (side === "right" && name === "json") renderRawJSON();
  if (side === "right") $(".inspector-panel").classList.add("is-mobile-open");
}

function renderAll() {
  renderMetadata();
  renderPages();
  renderCanvas();
  renderInspector();
  renderRawJSON();
  updateHistoryButtons();
}

function renderMetadata() {
  const meta = state.config?.meta || {};
  $("#meta-title").value = meta.title || "";
  $("#meta-lang").value = meta.lang || "en";
  $("#meta-description").value = meta.description || "";
  $("#meta-author").value = meta.author || "";
  $("#meta-favicon").value = meta.favicon || "";
  $("#site-title-summary").textContent = meta.title || "Untitled site";
  $("#site-theme-summary").textContent = meta.theme || "light";
  $("#site-language-summary").textContent = meta.lang || "en";
  renderThemeOptions(meta.theme || "light");
}

function renderThemeOptions(selected) {
  const select = $("#meta-theme");
  select.replaceChildren();
  for (const theme of state.themes) {
    const option = new Option(`${theme.label}${theme.namespace !== "core" ? ` · ${theme.namespace}` : ""}`, theme.name);
    select.add(option);
  }
  if (![...select.options].some((option) => option.value === selected)) {
    select.add(new Option(`${selected} (unavailable)`, selected));
  }
  select.value = selected;
}

function renderPages() {
  const pages = state.config?.pages || [];
  if (state.currentPage >= pages.length) state.currentPage = Math.max(0, pages.length - 1);
  const select = $("#current-page-select");
  const list = $("#pages-list");
  select.replaceChildren();
  list.replaceChildren();
  pages.forEach((page, index) => {
    select.add(new Option(page.path || `Page ${index + 1}`, String(index)));
    const item = document.createElement("button");
    item.type = "button";
    item.className = `page-list-item${index === state.currentPage ? " is-active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = page.path || `Page ${index + 1}`;
    const count = document.createElement("small");
    count.textContent = `${page.components?.length || 0} root component${page.components?.length === 1 ? "" : "s"}`;
    item.append(title, count);
    item.addEventListener("click", () => selectPage(index));
    list.append(item);
  });
  if (!pages.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "No pages. Add one to begin.";
    list.append(empty);
  }
  select.value = String(state.currentPage);
  const page = currentPage();
  $("#current-page-path").value = page?.path || "";
  $("#canvas-title").textContent = page?.path || "No page selected";
  $("#duplicate-page-button").disabled = !page;
  $("#delete-page-button").disabled = pages.length <= 1;
}

function selectPage(index) {
  if (!state.config.pages[index]) return;
  state.currentPage = index;
  state.selection = null;
  renderPages();
  renderCanvas();
  renderInspector();
  if (!$("#preview-drawer").hidden) refreshPreview(false);
}

function renderComponentLibrary() {
  const query = $("#component-search").value.trim().toLowerCase();
  const namespace = $("#namespace-filter").value;
  const list = $("#components-list");
  list.replaceChildren();
  const filtered = state.catalog
    .filter((component) => namespace === "all" || component.namespace === namespace)
    .filter((component) => !query || `${component.type} ${component.description} ${component.variants.map((item) => item.name).join(" ")}`.toLowerCase().includes(query));
  $("#component-count").textContent = String(filtered.length);
  for (const component of filtered) {
    const card = document.createElement("article");
    card.className = "component-card";
    card.draggable = true;
    card.dataset.type = component.type;
    const top = document.createElement("div");
    top.className = "component-card-top";
    const name = document.createElement("strong");
    name.textContent = component.type;
    const tag = document.createElement("span");
    tag.className = "namespace-tag";
    tag.textContent = component.namespace;
    const description = document.createElement("p");
    description.textContent = component.description || "No description";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "add-component-quick";
    add.textContent = "+";
    add.title = `Add ${component.type} to the current page`;
    add.addEventListener("click", (event) => {
      event.stopPropagation();
      quickAddComponent(component.type);
    });
    top.append(name, tag);
    card.append(top, description, add);
    card.addEventListener("dragstart", (event) => {
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("application/x-webuilder-component", component.type);
      card.classList.add("is-dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("is-dragging"));
    list.append(card);
  }
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "No components match this filter.";
    list.append(empty);
  }
}

function renderNamespaceFilter() {
  const select = $("#namespace-filter");
  const current = select.value || "all";
  const namespaces = [...new Set(state.catalog.map((item) => item.namespace))].sort((a, b) => a === "core" ? -1 : b === "core" ? 1 : a.localeCompare(b));
  select.replaceChildren(new Option("All namespaces", "all"));
  namespaces.forEach((namespace) => select.add(new Option(namespace, namespace)));
  select.value = namespaces.includes(current) ? current : "all";
}

function quickAddComponent(type) {
  const page = currentPage();
  if (!page) return showToast("Add a page before adding components.", "error");
  commit(`Add ${type}`, () => {
    const component = createComponent(type);
    page.components.push(component);
    state.selection = [page.components.length - 1];
  });
  switchTab("right", "properties");
}

function renderCanvas() {
  const canvas = $("#canvas");
  canvas.replaceChildren();
  const page = currentPage();
  if (!page) {
    const empty = document.createElement("div");
    empty.className = "canvas-empty";
    empty.textContent = "Add a page to start building.";
    canvas.append(empty);
    return;
  }
  const components = page.components || [];
  if (!components.length) {
    const empty = document.createElement("div");
    empty.className = "canvas-empty";
    const content = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = "Drop your first component here";
    const text = document.createElement("p");
    text.textContent = "Drag from the component library or use a component's + button.";
    content.append(strong, text);
    empty.append(content);
    configureDropTarget(empty, [], 0);
    canvas.append(empty);
    return;
  }
  renderComponentList(canvas, components, [], 0);
  sendPreviewSelection();
}

function renderComponentList(container, components, parentPath, depth) {
  components.forEach((component, index) => {
    container.append(createDropZone(parentPath, index, "Insert here"));
    container.append(renderComponentNode(component, [...parentPath, index], depth));
  });
  container.append(createDropZone(parentPath, components.length, "Append here"));
}

function createDropZone(parentPath, index, label) {
  const zone = document.createElement("div");
  zone.className = "drop-zone";
  zone.textContent = label;
  configureDropTarget(zone, parentPath, index);
  return zone;
}

function configureDropTarget(element, parentPath, index) {
  element.addEventListener("dragover", (event) => {
    if (!event.dataTransfer.types.includes("application/x-webuilder-component")
      && !event.dataTransfer.types.includes("application/x-webuilder-path")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes("application/x-webuilder-path") ? "move" : "copy";
    element.classList.add("is-over");
  });
  element.addEventListener("dragleave", () => element.classList.remove("is-over"));
  element.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    element.classList.remove("is-over");
    const type = event.dataTransfer.getData("application/x-webuilder-component");
    const pathData = event.dataTransfer.getData("application/x-webuilder-path");
    if (type) insertNewComponent(type, parentPath, index);
    else if (pathData) moveComponent(JSON.parse(pathData), parentPath, index);
  });
}

function renderComponentNode(component, path, depth) {
  const key = pathKey(path);
  const definition = getDefinition(component.type);
  const collapsed = state.collapsed.has(key);
  const node = document.createElement("article");
  node.className = `component-node${arraysEqual(state.selection || [], path) ? " is-selected" : ""}`;
  node.style.setProperty("--depth", String(depth));
  node.dataset.path = key;

  const header = document.createElement("div");
  header.className = "component-node-header";
  const handle = document.createElement("span");
  handle.className = "drag-handle";
  handle.textContent = "⠿";
  handle.title = "Drag to move";
  handle.draggable = true;
  handle.addEventListener("dragstart", (event) => {
    event.stopPropagation();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-webuilder-path", JSON.stringify({ page: state.currentPage, path }));
    node.classList.add("is-dragging");
  });
  handle.addEventListener("dragend", () => node.classList.remove("is-dragging"));

  const title = document.createElement("div");
  title.className = "component-node-title";
  const type = document.createElement("strong");
  type.textContent = component.type || "Unknown component";
  const variant = document.createElement("small");
  variant.textContent = `${component.variant || definition?.defaultVariant || "default"}${component.id ? ` · #${component.id}` : ""}`;
  title.append(type, variant);

  const actions = document.createElement("div");
  actions.className = "component-node-actions";
  if (Array.isArray(component.children) && component.children.length) {
    const collapse = document.createElement("button");
    collapse.className = "node-action";
    collapse.type = "button";
    collapse.textContent = collapsed ? "▸" : "▾";
    collapse.title = collapsed ? "Expand children" : "Collapse children";
    collapse.addEventListener("click", (event) => {
      event.stopPropagation();
      if (collapsed) state.collapsed.delete(key); else state.collapsed.add(key);
      renderCanvas();
    });
    actions.append(collapse);
  }
  const duplicate = document.createElement("button");
  duplicate.className = "node-action";
  duplicate.type = "button";
  duplicate.textContent = "⧉";
  duplicate.title = "Duplicate component";
  duplicate.addEventListener("click", (event) => { event.stopPropagation(); duplicateComponent(path); });
  actions.append(duplicate);
  header.append(handle, title, actions);
  header.addEventListener("click", () => selectComponent(path));
  node.append(header);

  const contentValues = Object.entries(component.content || {})
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value) && String(value).trim())
    .slice(0, 3);
  if (contentValues.length) {
    const preview = document.createElement("div");
    preview.className = "node-content-preview";
    contentValues.forEach(([name, value]) => {
      const chip = document.createElement("span");
      chip.className = "preview-chip";
      chip.textContent = `${name}: ${value}`;
      preview.append(chip);
    });
    node.append(preview);
  }

  if (definition?.acceptsChildren !== false) {
    const children = Array.isArray(component.children) ? component.children : [];
    const childContainer = document.createElement("div");
    childContainer.className = "component-children";
    childContainer.hidden = collapsed;
    if (!collapsed && children.length) renderComponentList(childContainer, children, path, depth + 1);
    else if (!collapsed) {
      const childDrop = createDropZone(path, 0, "Drop child component");
      childDrop.classList.add("child-drop");
      childContainer.append(childDrop);
    }
    node.append(childContainer);
  }
  return node;
}

function insertNewComponent(type, parentPath, index) {
  commit(`Add ${type}`, () => {
    const target = getChildrenArray(parentPath);
    if (!target) return;
    target.splice(index, 0, createComponent(type));
    state.selection = [...parentPath, index];
  });
  switchTab("right", "properties");
}

function moveComponent(sourceData, targetParentPath, targetIndex) {
  if (sourceData.page !== state.currentPage || !Array.isArray(sourceData.path)) {
    showToast("Components can only be moved within the current page.", "error");
    return;
  }
  const sourcePath = sourceData.path;
  if (isPrefix(sourcePath, targetParentPath)) {
    showToast("A component cannot be moved inside itself.", "error");
    return;
  }
  commit("Move component", () => {
    const sourceParentPath = sourcePath.slice(0, -1);
    const sourceIndex = sourcePath.at(-1);
    const sourceArray = getChildrenArray(sourceParentPath);
    const targetArray = getChildrenArray(targetParentPath);
    if (!sourceArray || !targetArray || !sourceArray[sourceIndex]) return;
    const [moving] = sourceArray.splice(sourceIndex, 1);
    if (sourceArray === targetArray && sourceIndex < targetIndex) targetIndex -= 1;
    targetIndex = Math.max(0, Math.min(targetIndex, targetArray.length));
    targetArray.splice(targetIndex, 0, moving);
    state.selection = [...targetParentPath, targetIndex];
  });
}

function selectComponent(path) {
  state.selection = [...path];
  renderCanvas();
  renderInspector();
  switchTab("right", "properties");
  sendPreviewSelection();
}

function duplicateComponent(path = state.selection) {
  const component = getComponent(path);
  if (!component) return;
  commit(`Duplicate ${component.type}`, () => {
    const parent = getChildrenArray(path.slice(0, -1));
    const index = path.at(-1) + 1;
    parent.splice(index, 0, clone(component));
    state.selection = [...path.slice(0, -1), index];
  });
}

function deleteComponent(path = state.selection) {
  const component = getComponent(path);
  if (!component || !window.confirm(`Delete ${component.type} and all of its children?`)) return;
  commit(`Delete ${component.type}`, () => {
    const parent = getChildrenArray(path.slice(0, -1));
    parent.splice(path.at(-1), 1);
    state.selection = null;
  });
}

function renderInspector() {
  const component = getComponent();
  $("#empty-inspector").hidden = Boolean(component);
  $("#component-inspector").hidden = !component;
  if (!component) return;
  const definition = getDefinition(component.type);
  $("#inspector-title").textContent = component.type;
  $("#inspector-namespace").textContent = definition?.namespace === "core" ? "Core component" : `${definition?.namespace || "Unknown"} plugin`;
  $("#prop-type").value = component.type;
  $("#prop-id").value = component.id ?? "";
  $("#prop-classes").value = Array.isArray(component.class) ? component.class.join(" ") : component.class || "";
  const variantSelect = $("#prop-variant");
  variantSelect.replaceChildren();
  for (const variant of definition?.variants || [{ name: component.variant || "default" }]) {
    variantSelect.add(new Option(variant.name, variant.name));
  }
  if (![...variantSelect.options].some((option) => option.value === component.variant)) {
    variantSelect.add(new Option(`${component.variant} (unavailable)`, component.variant));
  }
  variantSelect.value = component.variant || definition?.defaultVariant || variantSelect.options[0]?.value || "default";
  renderContentFields(component, variantSelect.value);
  $("#prop-events").value = JSON.stringify(component.events || {}, null, 2);
  $("#properties-error").textContent = "";
}

function renderContentFields(component, variantName) {
  const container = $("#content-fields");
  container.replaceChildren();
  const variant = getVariantDefinition(component.type, variantName);
  const defaults = variant?.defaults?.content || getDefinition(component.type)?.defaults?.content || {};
  const content = component.content && typeof component.content === "object" && !Array.isArray(component.content) ? component.content : {};
  const required = (variant?.required || getDefinition(component.type)?.required || [])
    .filter((path) => path.startsWith("content."))
    .map((path) => path.slice(8));
  const keys = [...new Set([...Object.keys(defaults), ...Object.keys(content), ...required])].sort();
  if (!keys.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "This component has no content fields yet.";
    container.append(empty);
    return;
  }
  for (const key of keys) container.append(createContentField(key, key in content ? content[key] : defaults[key], required.includes(key)));
}

function createContentField(key, value, required = false) {
  const wrapper = document.createElement("div");
  wrapper.className = "content-field";
  wrapper.dataset.contentKey = key;
  const heading = document.createElement("div");
  heading.className = "content-field-heading";
  const label = document.createElement("code");
  label.textContent = `${key}${required ? " *" : ""}`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-field";
  remove.textContent = "×";
  remove.title = `Remove content.${key}`;
  remove.addEventListener("click", () => {
    const component = getComponent();
    if (!component) return;
    commit(`Remove content.${key}`, () => { delete component.content?.[key]; });
  });
  heading.append(label, remove);
  let input;
  if (typeof value === "boolean") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = value;
    input.dataset.kind = "boolean";
    input.style.width = "1rem";
    input.style.minHeight = "1rem";
  } else if (value && typeof value === "object") {
    input = document.createElement("textarea");
    input.rows = Math.min(12, Math.max(4, JSON.stringify(value, null, 2).split("\n").length));
    input.value = JSON.stringify(value, null, 2);
    input.dataset.kind = "json";
    input.className = "code-input";
  } else if (typeof value === "number") {
    input = document.createElement("input");
    input.type = "number";
    input.value = String(value);
    input.dataset.kind = "number";
  } else if (/text|code|description|html|message/i.test(key) && String(value ?? "").length > 60) {
    input = document.createElement("textarea");
    input.rows = 4;
    input.value = value ?? "";
    input.dataset.kind = "string";
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = value ?? "";
    input.dataset.kind = "string";
  }
  input.dataset.contentInput = "";
  input.setAttribute("aria-label", `content.${key}`);
  wrapper.append(heading, input);
  return wrapper;
}

function applyProperties(event) {
  event.preventDefault();
  const component = getComponent();
  if (!component) return;
  try {
    const content = {};
    for (const wrapper of $$(".content-field", $("#content-fields"))) {
      const key = wrapper.dataset.contentKey;
      const input = $("[data-content-input]", wrapper);
      if (input.dataset.kind === "json") content[key] = JSON.parse(input.value || "null");
      else if (input.dataset.kind === "boolean") content[key] = input.checked;
      else if (input.dataset.kind === "number") content[key] = Number(input.value);
      else content[key] = input.value;
    }
    const events = JSON.parse($("#prop-events").value || "{}");
    if (!events || typeof events !== "object" || Array.isArray(events)
      || Object.values(events).some((value) => typeof value !== "string")) {
      throw new Error("Events must be a JSON object containing string values.");
    }
    const id = $("#prop-id").value.trim();
    const classNames = $("#prop-classes").value.trim().split(/\s+/).filter(Boolean);
    commit(`Update ${component.type}`, () => {
      component.variant = $("#prop-variant").value;
      component.content = content;
      component.events = events;
      if (id) component.id = id; else delete component.id;
      if (classNames.length) component.class = classNames; else delete component.class;
      if (!Object.keys(events).length) delete component.events;
    });
    $("#properties-error").textContent = "";
    showToast("Component properties updated", "success");
  } catch (error) {
    $("#properties-error").textContent = error.message;
  }
}

function addContentField() {
  const key = window.prompt("Content field name (for example: subtitle)");
  if (!key?.trim()) return;
  const normalized = key.trim();
  const component = getComponent();
  if (!component) return;
  if (normalized in (component.content || {})) return showToast(`content.${normalized} already exists.`, "error");
  commit(`Add content.${normalized}`, () => {
    component.content ||= {};
    component.content[normalized] = "";
  });
}

function renderPlugins() {
  const list = $("#plugins-list");
  list.replaceChildren();
  for (const plugin of state.plugins) {
    const label = document.createElement("label");
    label.className = `plugin-item${plugin.valid ? "" : " is-invalid"}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = plugin.name;
    checkbox.checked = plugin.enabled;
    checkbox.disabled = !plugin.valid;
    const content = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = plugin.name;
    const details = document.createElement("p");
    details.textContent = plugin.valid
      ? `${plugin.components} components · ${plugin.themes} themes · ${plugin.shortcuts} utilities`
      : plugin.error || "Invalid plugin";
    const origin = document.createElement("small");
    origin.textContent = `${plugin.origin} · v${plugin.version || "?"}`;
    content.append(name, details, origin);
    label.append(checkbox, content);
    list.append(label);
  }
  if (!state.plugins.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "No plugins found in the project plugins directory.";
    list.append(empty);
  }
}

async function applyPlugins() {
  const enabled = $$("#plugins-list input:checked").map((input) => input.value);
  setBusy(true, "Loading plugins…");
  try {
    const payload = await api("/api/plugins", { method: "POST", body: { enabled } });
    state.plugins = payload.plugins;
    state.catalog = payload.components;
    state.catalogByType = new Map(state.catalog.map((item) => [item.type, item]));
    state.themes = payload.themes;
    renderPlugins();
    renderNamespaceFilter();
    renderComponentLibrary();
    renderMetadata();
    renderCanvas();
    renderInspector();
    showToast("Plugin selection updated", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function renderAssets() {
  const list = $("#assets-list");
  list.replaceChildren();
  $("#asset-count").textContent = String(state.assets.length);
  for (const asset of state.assets) {
    const item = document.createElement("article");
    item.className = "asset-item";
    const thumb = document.createElement("div");
    thumb.className = "asset-thumb";
    if (asset.isImage) {
      const image = new Image();
      image.src = asset.url;
      image.alt = "";
      thumb.append(image);
    } else {
      thumb.textContent = asset.path.split(".").at(-1)?.toUpperCase().slice(0, 4) || "FILE";
    }
    const info = document.createElement("div");
    info.className = "asset-info";
    const name = document.createElement("strong");
    name.textContent = asset.path;
    const size = document.createElement("small");
    size.textContent = `${formatBytes(asset.size)}${asset.configured ? " · configured" : ""}`;
    info.append(name, size);
    const actions = document.createElement("div");
    actions.className = "asset-actions";
    const copyButton = document.createElement("button");
    copyButton.className = "node-action";
    copyButton.type = "button";
    copyButton.textContent = "⧉";
    copyButton.title = "Copy asset path";
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(`/assets/${asset.path}`);
      showToast("Asset path copied", "success");
    });
    const removeButton = document.createElement("button");
    removeButton.className = "node-action";
    removeButton.type = "button";
    removeButton.textContent = "×";
    removeButton.title = "Delete asset";
    removeButton.addEventListener("click", () => deleteAsset(asset.path));
    actions.append(copyButton, removeButton);
    item.append(thumb, info, actions);
    list.append(item);
  }
  if (!state.assets.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "No project assets yet.";
    list.append(empty);
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

async function uploadAssets(files) {
  if (!files?.length) return;
  const data = new FormData();
  [...files].forEach((file) => data.append("files", file));
  const directory = $("#asset-directory").value.trim();
  setBusy(true, `Uploading ${files.length} asset${files.length === 1 ? "" : "s"}…`);
  try {
    const before = snapshot();
    const payload = await api(`/api/upload-assets?directory=${encodeURIComponent(directory)}`, { method: "POST", body: data });
    state.assets = payload.assets;
    state.config = normalizeConfig(payload.config);
    state.history.push({ config: before, label: "Upload assets" });
    state.future = [];
    setDirty(false, "Saved");
    renderAssets();
    renderRawJSON();
    updateHistoryButtons();
    showToast(`${payload.uploaded.length} asset${payload.uploaded.length === 1 ? "" : "s"} uploaded`, "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    $("#asset-upload").value = "";
    setBusy(false);
  }
}

async function deleteAsset(path) {
  if (!window.confirm(`Delete assets/${path}?`)) return;
  setBusy(true, "Deleting asset…");
  try {
    const before = snapshot();
    const payload = await api("/api/delete-asset", { method: "POST", body: { path } });
    state.assets = payload.assets;
    state.config = normalizeConfig(payload.config);
    state.history.push({ config: before, label: "Delete asset" });
    state.future = [];
    setDirty(false, "Saved");
    renderAssets();
    renderRawJSON();
    updateHistoryButtons();
    showToast("Asset deleted", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function renderRawJSON() {
  if (!state.config) return;
  $("#raw-json-editor").value = JSON.stringify(state.config, null, 2);
}

function applyRawJSON() {
  try {
    const parsed = normalizeConfig(JSON.parse($("#raw-json-editor").value));
    if (!Array.isArray(parsed.pages)) throw new Error("The root 'pages' field must be an array.");
    commit("Apply raw JSON", () => {
      state.config = parsed;
      state.currentPage = Math.min(state.currentPage, Math.max(0, parsed.pages.length - 1));
      state.selection = null;
    });
    $("#raw-json-error").textContent = "";
    showToast("JSON applied to the in-memory document", "success");
  } catch (error) {
    $("#raw-json-error").textContent = error.message;
  }
}

function exportConfig() {
  const blob = new Blob([`${JSON.stringify(state.config, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "build.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function importConfig(file) {
  if (!file) return;
  try {
    const parsed = normalizeConfig(JSON.parse(await file.text()));
    if (!Array.isArray(parsed.pages)) throw new Error("Imported configuration must contain a pages array.");
    commit("Import configuration", () => {
      state.config = parsed;
      state.currentPage = 0;
      state.selection = null;
    });
    switchTab("right", "json");
    showToast("Configuration imported", "success");
  } catch (error) {
    showToast(`Import failed: ${error.message}`, "error");
  } finally {
    $("#import-input").value = "";
  }
}

function renderLogs(logs = state.lastLogs) {
  state.lastLogs = logs || [];
  const list = $("#logs-list");
  list.replaceChildren();
  for (const log of state.lastLogs) {
    const entry = document.createElement("div");
    entry.className = `log-entry ${log.level || "info"}`;
    const level = document.createElement("span");
    level.className = "log-level";
    level.textContent = log.level || "info";
    const message = document.createElement("span");
    message.className = "log-message";
    message.textContent = log.message || JSON.stringify(log);
    entry.append(level, message);
    list.append(entry);
  }
  const errors = state.lastLogs.filter((log) => log.level === "error").length;
  $("#log-summary").textContent = state.lastLogs.length
    ? `${state.lastLogs.length} entries${errors ? ` · ${errors} errors` : ""}`
    : "No log entries";
  if (!state.lastLogs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = "No build log entries.";
    list.append(empty);
  }
  if (errors) toggleLogs(true);
}

function toggleLogs(force) {
  const content = $("#logs-content");
  const expanded = typeof force === "boolean" ? force : content.hidden;
  content.hidden = !expanded;
  $("#logs-toggle").setAttribute("aria-expanded", String(expanded));
}

async function runBuild({ quiet = false } = {}) {
  if (state.building) return false;
  state.building = true;
  if (!quiet) setBusy(true, "Building website…");
  try {
    await saveNow(true);
    const payload = await api("/api/build", { method: "POST" });
    state.revision = payload.revision;
    state.lastLogs = payload.logs || [];
    renderLogs();
    if (payload.success) {
      if (!quiet) showToast(`Build completed in ${payload.durationMs} ms`, "success");
      if (!$("#preview-drawer").hidden) refreshPreview(false);
      return true;
    }
    showToast("Build failed. Review the build logs.", "error");
    toggleLogs(true);
    return false;
  } catch (error) {
    showToast(error.message, "error");
    return false;
  } finally {
    state.building = false;
    if (!quiet) setBusy(false);
  }
}

function previewPath() {
  const page = currentPage()?.path || "index.html";
  return `/preview/${page.split("/").map(encodeURIComponent).join("/")}?revision=${state.revision}`;
}

async function openPreview() {
  const success = await runBuild();
  if (!success) return;
  $("#preview-drawer").hidden = false;
  $("#preview-title").textContent = `Preview · ${currentPage()?.path || "index.html"}`;
  refreshPreview(true);
}

function refreshPreview(forceReload = true) {
  const iframe = $("#preview-iframe");
  const url = previewPath();
  $("#preview-title").textContent = `Preview · ${currentPage()?.path || "index.html"}`;
  if (forceReload || iframe.getAttribute("src") !== url) iframe.src = url;
  setTimeout(sendPreviewSelection, 250);
}

function previewInstanceId() {
  const component = getComponent();
  const page = currentPage();
  if (!component || !page || !state.selection) return null;
  const pageSlug = String(page.path).replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  return `${pageSlug}--${state.selection.join("-")}--${component.id || "component"}`;
}

function sendPreviewSelection() {
  const iframe = $("#preview-iframe");
  if (iframe.hidden || !iframe.contentWindow || $("#preview-drawer").hidden) return;
  iframe.contentWindow.postMessage({ type: "webuilder:select", instance: previewInstanceId() }, location.origin);
}

function addPageFromDialog(event) {
  event.preventDefault();
  const path = $("#new-page-path").value.trim();
  const title = $("#new-page-title").value.trim();
  if (!path || !/\.html?$/i.test(path) || path.startsWith("/") || path.split(/[\\/]/).includes("..")) {
    $("#page-dialog-error").textContent = "Enter a safe relative .html or .htm path.";
    return;
  }
  if (state.config.pages.some((page) => page.path === path)) {
    $("#page-dialog-error").textContent = "A page with this path already exists.";
    return;
  }
  commit(`Add page ${path}`, () => {
    const page = { path, components: [] };
    if (title) page.meta = { title };
    state.config.pages.push(page);
    state.currentPage = state.config.pages.length - 1;
    state.selection = null;
  });
  $("#page-dialog").close();
}

function duplicatePage() {
  const page = currentPage();
  if (!page) return;
  let counter = 2;
  const path = page.path || "page.html";
  const dot = path.lastIndexOf(".");
  const base = dot >= 0 ? path.slice(0, dot) : path;
  const extension = dot >= 0 ? path.slice(dot) : ".html";
  let candidate = `${base}-copy${extension}`;
  while (state.config.pages.some((item) => item.path === candidate)) candidate = `${base}-copy-${counter++}${extension}`;
  commit(`Duplicate page ${path}`, () => {
    const duplicate = clone(page);
    duplicate.path = candidate;
    state.config.pages.splice(state.currentPage + 1, 0, duplicate);
    state.currentPage += 1;
    state.selection = null;
  });
}

function deletePage() {
  const page = currentPage();
  if (!page || state.config.pages.length <= 1) return;
  if (!window.confirm(`Delete ${page.path} and all of its components?`)) return;
  commit(`Delete page ${page.path}`, () => {
    state.config.pages.splice(state.currentPage, 1);
    state.currentPage = Math.min(state.currentPage, state.config.pages.length - 1);
    state.selection = null;
  });
}

function collapseAll() {
  const allPaths = [];
  const visit = (items, parent = []) => items.forEach((component, index) => {
    const path = [...parent, index];
    if (component.children?.length) allPaths.push(pathKey(path));
    visit(component.children || [], path);
  });
  visit(currentPage()?.components || []);
  const shouldCollapse = allPaths.some((key) => !state.collapsed.has(key));
  state.collapsed = shouldCollapse ? new Set(allPaths) : new Set();
  $("#collapse-all-button").textContent = shouldCollapse ? "Expand all" : "Collapse all";
  renderCanvas();
}

function setupEvents() {
  $$('[data-left-tab]').forEach((button) => button.addEventListener("click", () => switchTab("left", button.dataset.leftTab)));
  $$('[data-right-tab]').forEach((button) => button.addEventListener("click", () => switchTab("right", button.dataset.rightTab)));
  $("#component-search").addEventListener("input", renderComponentLibrary);
  $("#namespace-filter").addEventListener("change", renderComponentLibrary);
  $("#apply-plugins-button").addEventListener("click", applyPlugins);

  $("#meta-toggle").addEventListener("click", () => {
    const form = $("#meta-form");
    form.hidden = !form.hidden;
    $("#meta-toggle").setAttribute("aria-expanded", String(!form.hidden));
  });
  $("#meta-form").addEventListener("change", (event) => {
    const fields = {
      "meta-title": "title", "meta-theme": "theme", "meta-lang": "lang",
      "meta-description": "description", "meta-author": "author", "meta-favicon": "favicon",
    };
    const key = fields[event.target.id];
    if (!key) return;
    commit(`Update site ${key}`, () => {
      const value = event.target.value.trim();
      if (value) state.config.meta[key] = value; else delete state.config.meta[key];
    });
  });

  $("#current-page-select").addEventListener("change", (event) => selectPage(Number(event.target.value)));
  $("#current-page-path").addEventListener("change", (event) => {
    const page = currentPage();
    if (!page) return;
    const value = event.target.value.trim();
    commit("Update page path", () => { page.path = value; });
  });
  $("#add-page-button").addEventListener("click", () => {
    $("#page-dialog-error").textContent = "";
    $("#new-page-path").value = `page-${state.config.pages.length + 1}.html`;
    $("#new-page-title").value = "";
    $("#page-dialog").showModal();
    $("#new-page-path").focus();
  });
  $("#page-dialog-form").addEventListener("submit", addPageFromDialog);
  $("#cancel-page-button").addEventListener("click", () => $("#page-dialog").close());
  $("#close-page-dialog-button").addEventListener("click", () => $("#page-dialog").close());
  $("#duplicate-page-button").addEventListener("click", duplicatePage);
  $("#delete-page-button").addEventListener("click", deletePage);
  $("#collapse-all-button").addEventListener("click", collapseAll);

  $("#properties-form").addEventListener("submit", applyProperties);
  $("#prop-variant").addEventListener("change", (event) => {
    const component = getComponent();
    if (component) renderContentFields(component, event.target.value);
  });
  $("#add-content-field-button").addEventListener("click", addContentField);
  $("#duplicate-component-button").addEventListener("click", () => duplicateComponent());
  $("#delete-component-button").addEventListener("click", () => deleteComponent());
  $("#close-inspector-button").addEventListener("click", () => {
    state.selection = null;
    renderCanvas();
    renderInspector();
    $(".inspector-panel").classList.remove("is-mobile-open");
  });

  $("#asset-upload").addEventListener("change", (event) => uploadAssets(event.target.files));
  const uploadZone = $("#upload-zone");
  uploadZone.addEventListener("dragover", (event) => { event.preventDefault(); uploadZone.classList.add("is-over"); });
  uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("is-over"));
  uploadZone.addEventListener("drop", (event) => {
    event.preventDefault(); uploadZone.classList.remove("is-over"); uploadAssets(event.dataTransfer.files);
  });

  $("#apply-json-button").addEventListener("click", applyRawJSON);
  $("#export-button").addEventListener("click", exportConfig);
  $("#import-input").addEventListener("change", (event) => importConfig(event.target.files[0]));

  $("#undo-button").addEventListener("click", undo);
  $("#redo-button").addEventListener("click", redo);
  $("#save-button").addEventListener("click", () => saveNow());
  $("#build-button").addEventListener("click", () => runBuild());
  $("#preview-button").addEventListener("click", openPreview);
  $("#refresh-preview-button").addEventListener("click", () => refreshPreview(true));
  $("#open-preview-button").addEventListener("click", () => window.open(previewPath(), "_blank", "noopener"));
  $("#close-preview-button").addEventListener("click", () => { $("#preview-drawer").hidden = true; });
  $("#preview-iframe").addEventListener("load", sendPreviewSelection);

  $("#logs-toggle").addEventListener("click", () => toggleLogs());
  $("#clear-logs-button").addEventListener("click", () => { state.lastLogs = []; renderLogs(); });

  document.addEventListener("keydown", (event) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (!modifier) return;
    if (event.key.toLowerCase() === "s") { event.preventDefault(); saveNow(); }
    else if (event.key.toLowerCase() === "b") { event.preventDefault(); runBuild(); }
    else if (event.key.toLowerCase() === "z" && event.shiftKey) { event.preventDefault(); redo(); }
    else if (event.key.toLowerCase() === "z") { event.preventDefault(); undo(); }
    else if (event.key.toLowerCase() === "y") { event.preventDefault(); redo(); }
  });
}

async function initialize() {
  setBusy(true, "Loading project…");
  setupEvents();
  try {
    const [statusPayload, configPayload, componentPayload, themePayload, pluginPayload, assetPayload, logPayload] = await Promise.all([
      api("/api/status"), api("/api/load-build"), api("/api/components"), api("/api/themes"),
      api("/api/plugins"), api("/api/assets"), api("/api/logs"),
    ]);
    state.status = statusPayload.status;
    state.config = normalizeConfig(configPayload.config);
    state.catalog = componentPayload.components;
    state.catalogByType = new Map(state.catalog.map((item) => [item.type, item]));
    state.themes = themePayload.themes;
    state.plugins = pluginPayload.plugins;
    state.assets = assetPayload.assets;
    state.lastLogs = logPayload.logs;
    state.revision = configPayload.revision || 0;
    $("#project-path").textContent = state.status.project;
    $("#project-path").title = state.status.project;
    setDirty(false, "Loaded");
    renderNamespaceFilter();
    renderComponentLibrary();
    renderPlugins();
    renderAssets();
    renderLogs();
    renderAll();
  } catch (error) {
    setDirty(false, "Load failed");
    $("#document-status-dot").className = "status-dot is-error";
    showToast(error.message, "error");
    toggleLogs(true);
  } finally {
    setBusy(false);
  }
}

initialize();
