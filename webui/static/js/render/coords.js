export function timeToX(t, viewState) {
  return (t - viewState.scrollSec) * viewState.zoomH;
}

export function xToTime(x, viewState) {
  return x / viewState.zoomH + viewState.scrollSec;
}

export function midiToY(midi, viewState, viewportHeight) {
  return viewportHeight / 2 - (midi - viewState.midiCenter) * viewState.zoomV;
}

export function yToMidi(y, viewState, viewportHeight) {
  return viewState.midiCenter + (viewportHeight / 2 - y) / viewState.zoomV;
}

export function viewportSec(viewState, viewportWidth) {
  return viewportWidth / viewState.zoomH;
}

export function clampScroll(scrollSec, durationSec, viewState, viewportWidth) {
  const vpSec = viewportSec(viewState, viewportWidth);
  const maxScroll = Math.max(0, durationSec - vpSec);
  return Math.max(0, Math.min(maxScroll, scrollSec));
}

// Edge-trigger thresholds: when the playhead drifts past the right edge
// or before the left edge, scroll to pin it back inside the band.
const EDGE_TRIGGER_RIGHT = 0.70;
const EDGE_TRIGGER_LEFT  = 0.30;

export function autoScrollFor(currentTime, viewState, viewportWidth, durationSec) {
  const vpSec = viewportSec(viewState, viewportWidth);
  if (viewState.scrollAnchor === "center") {
    return clampScroll(currentTime - vpSec / 2, durationSec, viewState, viewportWidth);
  }
  // "edge" mode: pin the playhead inside [20%, 80%] of the viewport.
  // No scroll while the playhead drifts inside this band; snap back to the
  // matching edge when it crosses out.
  const cursorFrac = (currentTime - viewState.scrollSec) / Math.max(1e-6, vpSec);
  let target = viewState.scrollSec;
  if (cursorFrac > EDGE_TRIGGER_RIGHT) {
    target = currentTime - vpSec * EDGE_TRIGGER_RIGHT;
  } else if (cursorFrac < EDGE_TRIGGER_LEFT) {
    target = currentTime - vpSec * EDGE_TRIGGER_LEFT;
  }
  return clampScroll(target, durationSec, viewState, viewportWidth);
}
