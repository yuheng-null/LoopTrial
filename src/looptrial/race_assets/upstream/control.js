import { CTRL } from './params.js?v=20260903-opamp-v6';
import { clamp, decoupledControlLaw, nonlinearP2Term } from './dualpath.js?v=20260903-opamp-v6';

export function filteredDerivative(ctrl, error, dt = CTRL.OMEGA_DT) {
  const safeDt = Number.isFinite(dt) && dt > 0 ? dt : CTRL.OMEGA_DT;
  const diff = (error - (ctrl.last_error ?? 0)) / safeDt;
  const cutoffHz = Number.isFinite(ctrl.dFilterHz) ? ctrl.dFilterHz : CTRL.D_FILTER_HZ;
  if (cutoffHz <= 0) {
    ctrl.d_filt = diff;
    return diff;
  }
  const omegaF = 2 * Math.PI * cutoffHz;
  const alpha = 1 / (1 + omegaF * safeDt);
  const previous = Number.isFinite(ctrl.d_filt) ? ctrl.d_filt : 0;
  ctrl.d_filt = alpha * previous + (1 - alpha) * diff;
  return ctrl.d_filt;
}

export function calcDirectionOuterLoop(ctrl, camError, feedForward = 0, dt = CTRL.OMEGA_DT) {
  const p = camError * (ctrl.kp ?? ctrl.nearKp ?? 0);
  const p2 = nonlinearP2Term(ctrl.kp2, camError);
  const d = filteredDerivative(ctrl, camError, dt) * (ctrl.kd ?? 0);
  ctrl.last_error = camError;
  return p + p2 + d + feedForward;
}

export function calcOmegaInnerLoop(pid, targetW, omegaMeas, dt = CTRL.OMEGA_DT) {
  const err = targetW - omegaMeas;
  const integralTry = pid.integral + err * dt;
  const outTry = pid.kp * err + pid.ki * integralTry;
  if (!((outTry > pid.max_out && err > 0) || (outTry < pid.min_out && err < 0))) pid.integral = integralTry;
  const out = clamp(pid.kp * err + pid.ki * pid.integral, pid.min_out, pid.max_out);
  pid.last_err = err;
  pid.out_pwm = out;
  return out;
}

export function calcMotorInnerLoop(pid, targetSpeed, currentSpeed, targetAcceleration = 0, accelerationFeedForward = 0) {
  if (Math.abs(targetSpeed) < 1 && Math.abs(currentSpeed) < 1) {
    pid.out_pwm = 0;
    pid.err0 = pid.err1 = pid.err2 = 0;
    return 0;
  }
  pid.err2 = pid.err1;
  pid.err1 = pid.err0;
  pid.err0 = targetSpeed - currentSpeed;
  const delta = pid.kp * (pid.err0 - pid.err1) + pid.ki * pid.err0;
  const candidatePid = clamp(pid.out_pwm + delta, pid.min_out, pid.max_out);
  const ka = typeof accelerationFeedForward === 'number' ? accelerationFeedForward : (accelerationFeedForward.acc_ff ?? 0);
  const ff = ka * targetAcceleration;
  const candidateTotal = candidatePid + ff;
  const currentTotal = pid.out_pwm + ff;
  const drivesFurtherIntoSaturation = (candidateTotal > pid.max_out && delta > 0 && currentTotal >= pid.max_out)
    || (candidateTotal < pid.min_out && delta < 0 && currentTotal <= pid.min_out);
  if (!drivesFurtherIntoSaturation) pid.out_pwm = candidatePid;
  // 前馈与 PI 合成后再限幅；当 Ka 触碰边界时，反向误差仍可让 PI 退出饱和。
  return clamp(pid.out_pwm + ff, pid.min_out, pid.max_out);
}

function normalizeInput(args) {
  if (args.length === 1 && args[0] && typeof args[0] === 'object') return args[0];
  const [steerError = 0, junc = 0, speedL = 0, speedR = 0, gyro = 0, targetBaseV = 1] = args;
  return { error: steerError, lateralError: steerError, farError: 0, ffW: 0,
    gyro, speedL, speedR, junc, targetBaseV };
}

export function createController(params) {
  const maxPwm = params.MAX_PWM_DUTY;
  const c = {
    params,
    steering: { ...params.steer, last_error: 0, d_filt: 0 },
    omega: { ...params.omega, integral: 0, last_err: 0, out_pwm: 0,
      max_out: CTRL.OMEGA_V_DIFF_MAX, min_out: -CTRL.OMEGA_V_DIFF_MAX },
    motorL: { ...params.motorL, err0: 0, err1: 0, err2: 0, out_pwm: 0, max_out: maxPwm, min_out: -maxPwm },
    motorR: { ...params.motorR, err0: 0, err1: 0, err2: 0, out_pwm: 0, max_out: maxPwm, min_out: -maxPwm },
    target_w: 0,
    base_pwm_l: 0, base_pwm_r: 0,
    ctrl_target_l: 0, ctrl_target_r: 0,
    debug_ctrl_mode: 4,
    vofa_target_speed_l: 0, vofa_target_speed_r: 0,
    vofa_target_w: CTRL.OMEGA_TEST_W,
    vofa_target_w_wave_active: false,
    map_blind_active: 0, map_blind_steer: 0,
    _v_diff: 0, _omega_tick: 0, _omega_sign: 1, _openloop_tick: 0,
    _speed_ref_l: 0, _speed_ref_r: 0,
  };
  c.state = c;

  function outputPwm() {
    const diff = params.diff;
    let pwmL = c.base_pwm_l; let pwmR = c.base_pwm_r;
    if (c.debug_ctrl_mode !== 1 && c.debug_ctrl_mode !== 5) {
      if (pwmL > 0) pwmL += diff.deadzone_l; else if (pwmL < 0) pwmL -= diff.deadzone_l;
      if (pwmR > 0) pwmR += diff.deadzone_r; else if (pwmR < 0) pwmR -= diff.deadzone_r;
    }
    return { pwmL: clamp(pwmL, -maxPwm, maxPwm), pwmR: clamp(pwmR, -maxPwm, maxPwm) };
  }
  function telemetry() {
    return { ...outputPwm(), targetW: c.target_w,
      targetVL: c.ctrl_target_l, targetVR: c.ctrl_target_r,
      basePwmL: c.base_pwm_l, basePwmR: c.base_pwm_r };
  }
  function setMotorTargets(left, right, input) {
    const dt = params.controlPeriodMs / 1000;
    const maxAccel = Math.max(0, Number.isFinite(params.diff.ref_accel_limit) ? params.diff.ref_accel_limit : 2000);
    const maxDelta = maxAccel * dt;
    const nextL = c._speed_ref_l + clamp(left - c._speed_ref_l, -maxDelta, maxDelta);
    const nextR = c._speed_ref_r + clamp(right - c._speed_ref_r, -maxDelta, maxDelta);
    const accelL = (nextL - c._speed_ref_l) / dt;
    const accelR = (nextR - c._speed_ref_r) / dt;
    c._speed_ref_l = nextL; c._speed_ref_r = nextR;
    c.ctrl_target_l = nextL; c.ctrl_target_r = nextR;
    c.base_pwm_l = calcMotorInnerLoop(c.motorL, nextL, input.speedL ?? 0, accelL, params.diff.acc_ff_l);
    c.base_pwm_r = calcMotorInnerLoop(c.motorR, nextR, input.speedR ?? 0, accelR, params.diff.acc_ff_r);
  }
  function updateCore(input) {
    const mode = c.debug_ctrl_mode;
    if (mode !== 1) c._openloop_tick = 0;
    if (mode === 1) {
      c.target_w = 0; c.ctrl_target_l = c.ctrl_target_r = 0;
      c._speed_ref_l = c._speed_ref_r = 0;
      c.base_pwm_l = CTRL.OPENLOOP_DUTY;
      c.base_pwm_r = c._openloop_tick < CTRL.OPENLOOP_R_STOP_TICKS ? CTRL.OPENLOOP_DUTY : 0;
      if (c._openloop_tick < CTRL.OPENLOOP_R_STOP_TICKS) c._openloop_tick++;
      return telemetry();
    }
    if (mode === 2) {
      c.target_w = 0;
      setMotorTargets(c.vofa_target_speed_l, c.vofa_target_speed_r, input);
      return telemetry();
    }
    if (mode === 5) {
      c.target_w = 0; c.ctrl_target_l = c.ctrl_target_r = 0;
      c._speed_ref_l = c._speed_ref_r = 0;
      c.base_pwm_l = params.diff.deadzone_l; c.base_pwm_r = params.diff.deadzone_r;
      return telemetry();
    }
    const vofaSpeed = (c.vofa_target_speed_l + c.vofa_target_speed_r) * 0.5;
    const baseSpeed = (vofaSpeed || params.diff.base_speed) * (input.targetBaseV ?? input.camTargetBaseV ?? 1);
    let requestedTargetW;
    if (mode === 3) {
      if (c.vofa_target_w_wave_active) {
        requestedTargetW = Number.isFinite(c.vofa_target_w) ? c.vofa_target_w : 0;
      } else {
        const omegaTarget = Number.isFinite(c.vofa_target_w) ? Math.abs(c.vofa_target_w) : CTRL.OMEGA_TEST_W;
        requestedTargetW = omegaTarget;
      }
    } else {
      const fusedError = input.error ?? input.currentError
        ?? input.steerError ?? input.lateralError ?? input.errNear ?? 0;
      const dFiltered = filteredDerivative(c.steering, fusedError, params.controlPeriodMs / 1000);
      const requested = decoupledControlLaw(c.steering, {
        error: fusedError,
        dFiltered,
        ffW: input.ffW ?? 0,
      });
      c.steering.last_error = fusedError;
      requestedTargetW = requested;
    }
    // 角速度目标参考斜坡: 无论来自外环还是角速度环的测试目标，均先限角加速度后送入 PI。
    const maxDelta = params.maxDeltaWPerMs * params.controlPeriodMs;
    c.target_w += clamp(requestedTargetW - c.target_w, -maxDelta, maxDelta);
    const omegaFb = calcOmegaInnerLoop(c.omega, c.target_w, input.gyro ?? 0, params.controlPeriodMs / 1000);
    c._v_diff = params.diff.kw_ff * c.target_w + omegaFb;
    const reduce = Math.min(Math.abs(c._v_diff), baseSpeed * params.diff.diff_reduce_max);
    const boost = reduce * 0.2;
    const left = c._v_diff > 0 ? baseSpeed + boost : baseSpeed - reduce;
    const right = c._v_diff > 0 ? baseSpeed - reduce : baseSpeed + boost;
    setMotorTargets(left, right, input);
    return telemetry();
  }
  c.update10ms = (...args) => updateCore(normalizeInput(args));
  c.outputPwm = outputPwm;
  c.stop = () => {
    for (const pid of [c.motorL, c.motorR]) pid.out_pwm = pid.err0 = pid.err1 = pid.err2 = 0;
    c.omega.integral = c.omega.last_err = c.omega.out_pwm = 0;
    c.steering.last_error = c.steering.d_filt = 0;
    c.target_w = c.base_pwm_l = c.base_pwm_r = 0;
    c.ctrl_target_l = c.ctrl_target_r = c._v_diff = 0;
    c._speed_ref_l = c._speed_ref_r = 0;
    c._omega_tick = c._openloop_tick = 0; c._omega_sign = 1;
  };
  return c;
}
