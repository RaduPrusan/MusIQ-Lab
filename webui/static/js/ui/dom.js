export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "data") for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = dv;
    else if (k === "style") Object.assign(node.style, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "attrs") for (const [ak, av] of Object.entries(v)) node.setAttribute(ak, av);
    else node[k] = v;
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

// Make a horizontal bar draggable. onUpdate(frac, ev) fires on pointerdown
// and every pointermove until release, with frac clamped to [0,1]. Optional
// onEnd(frac, ev) fires once on pointerup/cancel — useful when commit is
// expensive (e.g. audio seek) and only the final position matters.
export function attachDrag(target, onUpdate, { onEnd } = {}) {
  target.style.touchAction = "none";
  const fracAt = (ev) => {
    const rect = target.getBoundingClientRect();
    return Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
  };
  target.addEventListener("pointerdown", (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    target.setPointerCapture(e.pointerId);
    let lastFrac = fracAt(e);
    onUpdate(lastFrac, e);
    const move = (ev) => { lastFrac = fracAt(ev); onUpdate(lastFrac, ev); };
    const up = (ev) => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      try { target.releasePointerCapture(e.pointerId); } catch {}
      if (onEnd) onEnd(lastFrac, ev);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  });
  target.addEventListener("click", (e) => e.stopPropagation());
}
