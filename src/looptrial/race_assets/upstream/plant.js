import { gaussian } from './noise.js?v=20260903-opamp-v6';

const MAX_PWM = 10000;
// 原速度环增益以 ±5000 标定；允许到 ±10000 时继续线性增加驱动力，避免旧调参整体变软。
const PWM_NOMINAL = 5000;

function finiteOr(value, fallback) {
  return Number.isFinite(value) ? value : fallback;
}

function effectiveDrive(pwm, deadzone) {
  const mag = Math.abs(pwm);
  if (mag <= deadzone) return 0;
  const span = Math.max(1, PWM_NOMINAL - deadzone);
  const eff = Math.min(mag, MAX_PWM) - deadzone;
  return Math.sign(pwm) * (eff / span);
}

export function createPlant(opts = {}) {
  const o = {
    deadzoneL: 0,
    deadzoneR: 0,
    vMaxEnc: 120,
    tau: 0.12,
    encLpfAlpha: 0.35,
    trackWidth: 1.2,
    enc2World: 0.06,
    tauYaw: 0.10,
    alphaMax: 100,

    // Motor body: inertia * dv/dt = torque - damping * v - friction - load.
    inertia: 1,
    damping: null,
    torqueGain: null,
    coulombFriction: 0,
    staticFriction: 0,
    loadTorque: 0,
    smallSpeed: 0.02,
    motorDt: 0.01,
    pwmDelaySteps: 0,

    gyroNoiseSigma: 0,
    gyroBias: 0,
    encNoiseSigma: 0,
    encQuant: 0,
    rollDrag: 0,
    motorGainL: 1,
    motorGainR: 1,
    ...opts,
  };

  if (opts.trackWidth === undefined && opts.wheelBase !== undefined) o.trackWidth = opts.wheelBase;
  o.inertia = Math.max(1e-9, finiteOr(o.inertia, 1));
  o.tau = Math.max(1e-9, finiteOr(o.tau, 0.12));
  o.damping = finiteOr(o.damping, o.inertia / o.tau);
  o.torqueGain = finiteOr(o.torqueGain, o.damping * o.vMaxEnc);
  o.motorDt = Math.max(1e-5, finiteOr(o.motorDt, 0.01));
  o.trackWidth = Math.max(1e-9, finiteOr(o.trackWidth, 1.2));
  o.tauYaw = Math.max(1e-5, finiteOr(o.tauYaw, 0.10));
  o.alphaMax = Math.max(0, finiteOr(o.alphaMax, 100));

  const p = {
    opts: o,
    rng: Math.random,
    vL: 0,
    vR: 0,
    encL: 0,
    encR: 0,
    gyroDeg: 0,
    gyroDegTrue: 0,
    omegaRad: 0,
    yawRad: 0,
    vWorld: 0,
    _pwmQueueL: [],
    _pwmQueueR: [],
  };

  function delayedPwm(queue, pwm) {
    const steps = Math.max(0, Math.trunc(finiteOr(o.pwmDelaySteps, 0)));
    if (steps <= 0) {
      queue.length = 0;
      return pwm;
    }
    while (queue.length < steps) queue.push(0);
    const applied = queue.shift() ?? 0;
    queue.push(pwm);
    return applied;
  }

  function wheelStep(speed, pwm, deadzone, motorGain, dt) {
    const drive = effectiveDrive(pwm, deadzone);
    const motorTorque = o.torqueGain * motorGain * drive;
    const moving = Math.abs(speed) > o.smallSpeed;

    if (!moving && Math.abs(motorTorque) <= o.staticFriction + o.loadTorque) {
      return 0;
    }

    const direction = moving ? Math.sign(speed) : Math.sign(motorTorque);
    const coulomb = direction * o.coulombFriction;
    const load = direction * o.loadTorque;
    const acceleration = (motorTorque - o.damping * speed - coulomb - load) / o.inertia;
    let next = speed + acceleration * dt;

    if (drive === 0 && speed !== 0 && Math.sign(next) !== Math.sign(speed)) {
      next = 0;
    }
    if (Math.abs(next) < o.smallSpeed && Math.abs(motorTorque) <= o.staticFriction) {
      next = 0;
    }
    return next;
  }

  function integrateWheel(speed, pwm, deadzone, motorGain, dt) {
    let v = speed;
    let remaining = Math.max(0, dt);
    while (remaining > 1e-12) {
      const h = Math.min(o.motorDt, remaining);
      v = wheelStep(v, pwm, deadzone, motorGain, h);
      remaining -= h;
    }
    return v;
  }

  p.step = function (pwmL, pwmR, dt) {
    const appliedL = delayedPwm(p._pwmQueueL, pwmL);
    const appliedR = delayedPwm(p._pwmQueueR, pwmR);

    p.vL = integrateWheel(p.vL, appliedL, o.deadzoneL, o.motorGainL, dt);
    p.vR = integrateWheel(p.vR, appliedR, o.deadzoneR, o.motorGainR, dt);

    if (o.rollDrag > 0) {
      const f = Math.max(0, 1 - o.rollDrag * dt);
      p.vL *= f;
      p.vR *= f;
    }

    let rawL = p.vL;
    let rawR = p.vR;
    if (o.encNoiseSigma > 0) {
      rawL += gaussian(p.rng) * o.encNoiseSigma;
      rawR += gaussian(p.rng) * o.encNoiseSigma;
    }
    if (o.encQuant > 0) {
      rawL = Math.round(rawL / o.encQuant) * o.encQuant;
      rawR = Math.round(rawR / o.encQuant) * o.encQuant;
    }
    p.encL = p.encL * (1 - o.encLpfAlpha) + rawL * o.encLpfAlpha;
    p.encR = p.encR * (1 - o.encLpfAlpha) + rawR * o.encLpfAlpha;

    p.vWorld = (p.vL + p.vR) / 2 * o.enc2World;
    const omegaKinRad = (p.vL - p.vR) * o.enc2World / o.trackWidth;
    const alphaYawUnclamped = (omegaKinRad - p.omegaRad) / o.tauYaw;
    const alphaYaw = Math.max(-o.alphaMax, Math.min(o.alphaMax, alphaYawUnclamped));
    p.omegaRad += alphaYaw * dt;
    p.yawRad += p.omegaRad * dt;
    p.gyroDegTrue = p.omegaRad * 57.29577951308232;
    p.gyroDeg = p.gyroDegTrue + o.gyroBias;
    if (o.gyroNoiseSigma > 0) p.gyroDeg += gaussian(p.rng) * o.gyroNoiseSigma;

    return {
      encL: p.encL,
      encR: p.encR,
      gyroDeg: p.gyroDeg,
      gyroDegTrue: p.gyroDegTrue,
      omegaRad: p.omegaRad,
      yawRad: p.yawRad,
      vWorld: p.vWorld,
    };
  };

  p.reset = function () {
    p.vL = 0;
    p.vR = 0;
    p.encL = 0;
    p.encR = 0;
    p.gyroDeg = 0;
    p.gyroDegTrue = 0;
    p.omegaRad = 0;
    p.yawRad = 0;
    p.vWorld = 0;
    p._pwmQueueL.length = 0;
    p._pwmQueueR.length = 0;
  };

  return p;
}

export function manualDrivePwm(throttle, steer, opts = {}) {
  const o = { deadzoneL: 1700, deadzoneR: 2000, maxPwm: PWM_NOMINAL, turnGain: 0.35, pivotDrive: 0.08, ...opts };
  const fwd = Math.max(-1, Math.min(1, throttle));
  const turn = Math.max(-1, Math.min(1, steer));
  let dL;
  let dR;
  if (fwd !== 0) {
    const reduce = Math.abs(turn) * o.turnGain;
    dL = fwd * (turn > 0 ? 1 : 1 - reduce);
    dR = fwd * (turn < 0 ? 1 : 1 - reduce);
  } else {
    dL = turn * o.pivotDrive;
    dR = -turn * o.pivotDrive;
  }
  const toPwm = (d, dz) => d === 0 ? 0 : Math.sign(d) * (dz + Math.abs(d) * (o.maxPwm - dz));
  return { pwmL: Math.round(toPwm(dL, o.deadzoneL)), pwmR: Math.round(toPwm(dR, o.deadzoneR)) };
}
