// Minimal toast notification surface.
// Toasts append to a container at #toast-stack, auto-dismiss after 5s,
// or on click. Multiple toasts stack; max 4 visible (older drop).
//
// Wired from api.js (central fetch wrapper) so 4xx/5xx responses surface
// as user-visible red toasts. Can also be called directly from any UI
// site that needs to surface a transient message.

const MAX_TOASTS = 4;
const DISMISS_MS = 5000;

let stack = null;

function ensureStack() {
  if (stack && stack.isConnected) return stack;
  stack = document.createElement("div");
  stack.id = "toast-stack";
  document.body.appendChild(stack);
  return stack;
}

export function showToast(level, message) {
  const el = document.createElement("div");
  el.className = `toast toast-${level}`;
  el.textContent = message; // textContent, not innerHTML
  el.addEventListener("click", () => el.remove());
  const root = ensureStack();
  root.appendChild(el);
  while (root.children.length > MAX_TOASTS) root.firstElementChild.remove();
  setTimeout(() => el.remove(), DISMISS_MS);
  return el;
}
