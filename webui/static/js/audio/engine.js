/**
 * Audio engine contract. v1 ships WebAudioEngine. Future revisions add
 * AsioEngine (WebSocket → Python audio_backend/) without UI changes.
 *
 * Implementations MUST:
 *   - Own all per-stem mute/solo/volume state (UI re-reads, never duplicates).
 *   - Emit 'time' on requestAnimationFrame cadence while playing.
 *   - Resolve load() only when the source is decodable (stems may still be loading).
 *   - Expose currentTime as the seconds-offset that maps directly to playhead position.
 */
export class AudioEngine {
  async load(_options) { throw new Error("abstract"); }
  play()  { throw new Error("abstract"); }
  pause() { throw new Error("abstract"); }
  seek(_timeSec) { throw new Error("abstract"); }
  setStemVolume(_name, _vol01) { throw new Error("abstract"); }
  setStemMute(_name, _bool) { throw new Error("abstract"); }
  setStemSolo(_name, _bool) { throw new Error("abstract"); }
  get currentTime() { throw new Error("abstract"); }
  get isPlaying()   { throw new Error("abstract"); }
  on(_event, _fn)   { throw new Error("abstract"); }
  off(_event, _fn)  { throw new Error("abstract"); }
}

// Canonical stem order across the app: vocals → piano → other → guitar →
// bass → drums. Drums always sits last because the canvas pins it to its
// own lane regardless of melodic order. Mirrored exactly in pianoroll's
// STEM_ORDER (drums-stripped), track-data packing, sidebar rendering, the
// stem-color picker grid, and the play-engine mixer routing.
export const STEM_NAMES = ["vocals", "piano", "other", "guitar", "bass", "drums"];
