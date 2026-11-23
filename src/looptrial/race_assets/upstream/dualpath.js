import { CTRL } from './params.js?v=20260903-opamp-v6';

export function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

export function regionStat(cx, valid, y0, y1) {
  let count = 0;
  let sum = 0;
  let first = 0;
  let last = 0;

  for (let y = y0; y <= y1; y++) {
    if (!valid[y]) continue;
    const value = cx[y];
    if (count === 0) first = value;
    last = value;
    sum += value;
    count++;
  }

  return {
    count,
    mean: count > 0 ? sum / count : 0,
    lean: count >= 2 ? last - first : 0,
  };
}

export function regionClean(count, height) {
  return count >= height - 2;
}

export function cornerFeedForward(direction, maxW) {
  return direction * maxW;
}

export function nonlinearP2Term(kp2, error) {
  const gain = Number.isFinite(kp2) ? kp2 : 0;
  const e = Number.isFinite(error) ? error : 0;
  return Math.abs(e) > CTRL.KP2_ERR_THRESHOLD ? gain * e * Math.abs(e) : 0;
}

export function resolveWindow(centerY, rows, minY = 10, maxY = 59) {
  const count = Math.max(1, Math.trunc(rows));
  const y0 = Math.round(centerY - (count - 1) / 2);
  const y1 = y0 + count - 1;
  return { centerY, rows: count, y0, y1, valid: y0 >= minY && y1 <= maxY };
}

export function resolveDualPathWindows(params) {
  const near = resolveWindow(params.nearCenterY, params.nearRows);
  const far = resolveWindow(params.farCenterY, params.farRows);
  const separationRows = params.nearCenterY - params.farCenterY;
  let reason = '';
  if (!far.valid) reason = 'far-out-of-range';
  else if (!near.valid) reason = 'near-out-of-range';
  else if (far.y1 + 4 >= near.y0) reason = 'overlap';
  else if (!(separationRows > 0)) reason = 'reversed';
  return { near, far, farUsable: reason === '', reason, separationRows };
}

export function normalizeHeadingError(errNear, errFar, separationRows, referenceRows = 40) {
  if (!(separationRows > 0)) return 0;
  return (errFar - errNear) * referenceRows / separationRows;
}

const STRAIGHT_INTERNAL = Symbol('straightSelectorInternal');

function straightInternal(state) {
  if (!state[STRAIGHT_INTERNAL]) {
    Object.defineProperty(state, STRAIGHT_INTERNAL, {
      value: { gliding: false, glideStartEncoderCm: 0 },
      enumerable: false,
    });
  }
  return state[STRAIGHT_INTERNAL];
}

export function createStraightSelector() {
  const state = {
    dirtyFrames: 0,
    holdFrames: 0,
    lastError: 0,
  };
  straightInternal(state);
  return state;
}

export function resetStraightSelector(state) {
  const internal = straightInternal(state);
  state.dirtyFrames = 0;
  state.holdFrames = 0;
  state.lastError = 0;
  internal.gliding = false;
  internal.glideStartEncoderCm = 0;
}

export function selectStraightError(state, near, far, options = {}) {
  const internal = straightInternal(state);
  const encoderCm = options.encoderCm ?? 0;
  const glideCm = options.glideCm ?? 0;
  const holdLimit = options.holdFrames ?? 5;
  const exitLimit = options.exitFrames ?? 20;

  if (internal.gliding) {
    if (encoderCm - internal.glideStartEncoderCm < glideCm) {
      state.dirtyFrames = 0;
      state.holdFrames = 0;
      return { kind: 'glide', error: 0, exitRequested: false };
    }
    internal.gliding = false;
  }

  if (near.clean && far.clean) {
    internal.gliding = true;
    internal.glideStartEncoderCm = encoderCm;
    state.dirtyFrames = 0;
    state.holdFrames = 0;
    state.lastError = 0;
    return { kind: 'glide', error: 0, exitRequested: false };
  }

  if (near.clean) {
    state.dirtyFrames = 0;
    state.holdFrames = 0;
    state.lastError = near.error;
    return { kind: 'near', error: near.error, exitRequested: false };
  }

  if (far.clean) {
    state.dirtyFrames = 0;
    state.holdFrames = 0;
    state.lastError = far.error;
    return { kind: 'far', error: far.error, exitRequested: false };
  }

  state.dirtyFrames++;
  state.holdFrames = state.dirtyFrames;
  if (state.dirtyFrames <= holdLimit) {
    return { kind: 'hold', error: state.lastError, exitRequested: false };
  }
  if (state.dirtyFrames <= exitLimit) {
    return { kind: 'coast', error: 0, exitRequested: false };
  }
  return { kind: 'exit', error: 0, exitRequested: true };
}

export function decoupledControlLaw(g, s) {
  const error = s.error ?? s.nearError ?? 0;
  const derivative = s.dFiltered ?? s.deltaError ?? 0;
  const kp = g.kp ?? g.nearKp ?? 0;
  const kp2 = g.kp2 ?? 0;
  const kd = g.kd ?? 0;
  return kp * error + nonlinearP2Term(kp2, error) + kd * derivative + (s.ffW ?? 0);
}
