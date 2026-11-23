// 视觉流水线 — 对照固件 camera_process.c 的实现移植
// 阶段: 预处理(2x2下采样 94×60) → 二值化(Bradley-Roth) → 扫线(line_extract)
//        → 拐点/路口/偏置(corner_detect) → 误差融合(error_fusion)
//
// 进度: [M1] 二值化 ✅  预处理/扫线/误差融合 进行中   [M3] 拐点/路口/偏置
//
// 纯函数层: 不依赖 DOM / Three.js, 可 Node 单测。
// bin/gray 均为行主序 Uint8Array, 长度 IMG_W*IMG_H (94×60), 索引 r*IMG_W+c。

import {
  IMG_W, IMG_H, IMG_PROC_START, IMG_PROC_H, TRACK_MIN_WIDTH,
  IMG_CROP_LEFT, IMG_CROP_RIGHT, MT9V03X_W, MT9V03X_H, JuncType, OpAmpStage, CORNER,
} from './constants.js?v=20260903-opamp-v6';
import {
  cornerFeedForward,
  createStraightSelector,
  normalizeHeadingError,
  regionClean,
  regionStat,
  resolveDualPathWindows,
  resetStraightSelector,
  selectStraightError,
} from './dualpath.js?v=20260903-opamp-v6';
import { sanitizeDualPathParams } from './params.js?v=20260903-opamp-v6';

/* ==================== 阶段1: 二值化 (Bradley-Roth 自适应) ==================== */

// 积分图缓冲 (对应 C 的 static g_integral[IMG_H][IMG_W])
const _integral = new Uint32Array(IMG_W * IMG_H);
// 滤波临时缓冲 (对应 C 的 static temp / temp_row)
const _tempRow = new Uint8Array(IMG_W);
const _tempCross = new Uint8Array(IMG_W * IMG_H);

// 3像素水平多数投票 (≥2白则白); 首尾列原样保留。就地修改 bin。
export function filterMajority3h(bin, w, h) {
  for (let r = 0; r < h; r++) {
    const base = r * IMG_W;
    let prev = bin[base];
    _tempRow[0] = prev;
    _tempRow[w - 1] = bin[base + w - 1];
    for (let c = 1; c < w - 1; c++) {
      const cur = bin[base + c];
      const nxt = bin[base + c + 1];
      const votes = (prev === 255 ? 1 : 0) + (cur === 255 ? 1 : 0) + (nxt === 255 ? 1 : 0);
      _tempRow[c] = votes >= 2 ? 255 : 0;
      prev = cur;
    }
    for (let c = 0; c < w; c++) bin[base + c] = _tempRow[c];
  }
}

// 十字邻域去噪: 白点若上下左右4邻域全黑则滤除, 至少1白则保留。就地修改 bin。
export function filterCrossNoise(bin, w, h) {
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const i = r * IMG_W + c;
      if (bin[i] === 0) { _tempCross[i] = 0; continue; }
      const up = (r > 0) ? bin[i - IMG_W] : 0;
      const down = (r < h - 1) ? bin[i + IMG_W] : 0;
      const left = (c > 0) ? bin[i - 1] : 0;
      const right = (c < w - 1) ? bin[i + 1] : 0;
      _tempCross[i] = ((up | down | left | right) === 255) ? 255 : 0;
    }
  }
  const n = w * h;
  for (let i = 0; i < n; i++) bin[i] = _tempCross[i];
}

// 主入口: gray → bin。忠实移植 binarize_run。
// 【忠实细节】s2 取自"钳位前"的 S; S 的钳位是死代码(算完 s2 后 S 不再使用), 仅 T 钳位生效。
export function binarizeRun(bin, gray, params) {
  let S = params.bradleyS;
  let T = params.bradleyT;
  const s2 = (S / 2) | 0;
  if (S < 1) S = 1;
  if (S > 50) S = 50;   // 死代码, 保留以忠实
  if (T < 85) T = 85;
  if (T > 155) T = 155;
  const minWhite = params.minWhite;

  // 第一步: 构建积分图 (单趟扫描, 行累加器)
  for (let r = 0; r < IMG_H; r++) {
    let rowSum = 0;
    for (let c = 0; c < IMG_W; c++) {
      rowSum += gray[r * IMG_W + c];
      if (r === 0) _integral[c] = rowSum;
      else _integral[r * IMG_W + c] = _integral[(r - 1) * IMG_W + c] + rowSum;
    }
  }

  // 第二步: 逐像素二值化 (积分图 O(1) 查窗口和)
  for (let r = 0; r < IMG_H; r++) {
    for (let c = 0; c < IMG_W; c++) {
      const x1 = (c - s2 > 0) ? (c - s2) : 0;
      const y1 = (r - s2 > 0) ? (r - s2) : 0;
      const x2 = (c + s2 < IMG_W) ? (c + s2) : (IMG_W - 1);
      const y2 = (r + s2 < IMG_H) ? (r + s2) : (IMG_H - 1);
      const count = (x2 - x1 + 1) * (y2 - y1 + 1);

      let localSum = _integral[y2 * IMG_W + x2];
      if (y1 > 0) localSum -= _integral[(y1 - 1) * IMG_W + x2];
      if (x1 > 0) localSum -= _integral[y2 * IMG_W + (x1 - 1)];
      if (y1 > 0 && x1 > 0) localSum += _integral[(y1 - 1) * IMG_W + (x1 - 1)];

      const g = gray[r * IMG_W + c];
      bin[r * IMG_W + c] = (g > minWhite && g * count * 100 >= localSum * T) ? 255 : 0;
    }
  }

  // 后处理去噪
  filterMajority3h(bin, IMG_W, IMG_H);
  filterCrossNoise(bin, IMG_W, IMG_H);
}

/* ==================== 算法状态 (对应 C 的 AlgoState / CenterPoint_t) ==================== */

export function createCenterPoint() {
  return { cx: 0, leftX: 0, rightX: 0, width: 0, raw_width: 0, raw_cx: 0, valid: 0, border_white: 0 };
}

export function createVisionState() {
  const ca = new Array(IMG_H);
  for (let i = 0; i < IMG_H; i++) ca[i] = createCenterPoint();
  return {
    w: IMG_W, h: IMG_H,
    gray: new Uint8Array(IMG_W * IMG_H),   // 下采样后灰度图 (对应 C 的 g_small_gray)
    bin: new Uint8Array(IMG_W * IMG_H),
    ca,
    valid_rows_count: 0,
    max_width: 0, max_width_y: 0, raw_max_width: 0, raw_max_width_y: -1,
    // 误差融合输出 (M1 后段填充)
    current_error: 0, last_error: 0, weighted_avg_cx: (IMG_W / 2) | 0, target_base_v: 1.0,
    last_valid_rows: 0,
    // 拐点/路口/偏置 (M3)
    corner_y: -1, corner_dir: 0, corner_is_junction: 0, corner_junc_type: JuncType.NONE,
    bias_active: 0, bias_dir: 0, bias_corner_y: 0,
    bias_start_yaw: 0, bias_start_encoder: 0,
    corner_guard_active: 0, corner_guard_start_yaw: 0,
    bias_is_mos: 0, mos_bottom_seen: 0, mos_top_seen: 0,
    straight_double: 0, vote_history: 0,
    current_queue_idx: 0, queue_matched: 0, queue_wrap_wait_clear: 0,
    // 超级大号运放（队列专用）独立状态机
    opamp_active: 0, opamp_stage: OpAmpStage.IDLE, opamp_queue_idx: -1,
    opamp_right_armed: 0, opamp_exit_wait_clear: 0,
    opamp_turn_accum_rad: 0, opamp_prev_yaw: 0,
    // 外部输入 (CPU0→CPU1)
    current_gyro_y: 0, yaw_accum: 0, encoder_dist_delta: 0,
    // 调试
    dbg_recovery_active: 0, dbg_score_pct: 0,
    dbg_corner_y: -1, dbg_corner_cx: 0, dbg_corner_dir: 0, dbg_control_corner_y: -1,
    dbg_corner_reached_activation: 0,
    dbg_corner_guard_active: 0,
    dbg_mos_corner_valid: 0,
    dbg_dcx: 0, dbg_dcx_valid: 0,
    dbg_box_w: 0, dbg_box_h: 0, dbg_box_y: -1, dbg_box_sample_hits: 0, dbg_box_sample_veto: 0,
    dbg_has_top: 0, dbg_has_bottom: 0, dbg_has_left: 0, dbg_has_right: 0,
    dbg_left_intersection_y: -1, dbg_right_intersection_y: -1, dbg_intersection_avg_y: -1,
    dbg_interference_votes: 0,
    // 双路视觉输出（对应 camera_process.c 的 s_dp_* 跨帧状态）
    lateralError: 0, headingError: 0, headingErrorRaw: 0,
    nearValid: false, farValid: false, windowConflict: '',
    nearWindow: null, farWindow: null,
    errNear: 0, errFar: 0, curvature: 0, ffW: 0,
    trackStraight: false, dpSel: 'none', dpStraightExitRequested: false,
    straightSelector: createStraightSelector(),
    prevBiasActive: 0, prevBiasDir: 0,
    recoveryActive: false, recoveryFrames: 0, recoveryHold: 0,
    recoveryLastDeltaCx: 0, carrySign: 0, biasExitAdjustRad: 0,
  };
}

/* ==================== 阶段2: 从外向内扫线 (line_extract) ==================== */

const EXPAND_MARGIN = 4;                          // 向外扩张像素 (原8, 等比缩放)
const SCAN_X_MIN = IMG_CROP_LEFT;                 // =3
const SCAN_X_MAX = IMG_W - 1 - IMG_CROP_RIGHT;    // =90
const TRACK_MAX_WIDTH = 30;   // 赛道有效宽度上限 (用户标定: 赛道宽不能大于30px; 超宽视为路口白块)

// 从 startX 向右扫, 找第一个连续3白点, 返回起点 x 或 -1
export function scanRightForWhite(row, startX, endX) {
  if (startX < 0) startX = 0;
  if (endX >= IMG_W) endX = IMG_W - 1;
  for (let x = startX; x <= endX - 3; x++) {
    if (x < 0 || x + 2 >= IMG_W) continue;
    if (row[x] > 128 && row[x + 1] > 128 && row[x + 2] > 128) return x;
  }
  return -1;
}

// 从 startX 向左扫, 找第一个连续3白点, 返回起点 x 或 -1
export function scanLeftForWhite(row, startX, endX) {
  if (startX >= IMG_W) startX = IMG_W - 1;
  if (endX < 0) endX = 0;
  for (let x = startX; x >= endX + 3; x--) {
    if (x >= IMG_W || x - 2 < 0) continue;
    if (row[x] > 128 && row[x - 1] > 128 && row[x - 2] > 128) return x;
  }
  return -1;
}

// 从 whiteX 向左找白→黑边界, 返回边界内白点 x
export function findLeftBoundary(row, whiteX) {
  if (whiteX >= IMG_W) whiteX = IMG_W - 1;
  for (let x = whiteX; x >= 0; x--) {
    if (row[x] <= 128) return x + 1;
  }
  return 0;
}

// 从 whiteX 向右找白→黑边界
export function findRightBoundary(row, whiteX) {
  if (whiteX < 0) whiteX = 0;
  for (let x = whiteX; x < IMG_W; x++) {
    if (row[x] <= 128) return x - 1;
  }
  return IMG_W - 1;
}

function findBoundedTrackSegmentNear(row, targetX) {
  let best = null;
  let searchX = SCAN_X_MIN;
  while (searchX <= SCAN_X_MAX - 2) {
    const whiteX = scanRightForWhite(row, searchX, SCAN_X_MAX);
    if (whiteX < 0) break;
    const leftX = findLeftBoundary(row, whiteX);
    const rightX = findRightBoundary(row, whiteX);
    const width = rightX - leftX;
    if (width >= TRACK_MIN_WIDTH && width <= TRACK_MAX_WIDTH) {
      const cx = ((leftX + rightX) / 2) | 0;
      const score = Math.abs(cx - targetX);
      if (!best || score < best.score) best = { leftX, rightX, width, cx, score };
    }
    searchX = Math.max(rightX + 1, whiteX + 1);
  }
  return best;
}

// 主入口: 读 s.bin, 写 s.ca[] 与 valid_rows_count / max_width(_y)。忠实移植 line_extract_run。
export function lineExtractRun(s, params) {
  void params;
  let last_valid_cx = -1;
  let last_valid_width = 0;
  let consecutive_invalid = 0;

  s.valid_rows_count = 0;
  s.max_width = 0; s.max_width_y = 0;
  s.raw_max_width = 0; s.raw_max_width_y = -1;

  for (let y = IMG_H - 1; y >= IMG_PROC_START; y--) {
    const row = s.bin.subarray(y * IMG_W, y * IMG_W + IMG_W);
    let finalLeft = -1;
    let finalRight = -1;
    let isRowValid = 0;
    let currentWidth = 0;
    let currentCx;

    if (last_valid_cx < 0) {
      // 起步: 全宽独立搜索
      finalLeft = scanRightForWhite(row, SCAN_X_MIN, SCAN_X_MAX);
      finalRight = scanLeftForWhite(row, SCAN_X_MAX, SCAN_X_MIN);

      if (finalLeft < 0 || finalRight < 0 || finalRight - finalLeft <= 3) {
        if (finalLeft >= 0 && finalRight < 0) {
          const estW = last_valid_width > 0 ? last_valid_width : 30;
          finalRight = finalLeft + estW;
          if (finalRight > SCAN_X_MAX) finalRight = SCAN_X_MAX;
        } else if (finalRight >= 0 && finalLeft < 0) {
          const estW = last_valid_width > 0 ? last_valid_width : 30;
          finalLeft = finalRight - estW;
          if (finalLeft < SCAN_X_MIN) finalLeft = SCAN_X_MIN;
        } else {
          // 两边都没有 (含双边但宽度≤3): 跳过
          currentCx = (IMG_W / 2) | 0;
          const p0 = s.ca[y];
          p0.cx = currentCx; p0.leftX = -1; p0.rightX = -1; p0.width = 0; p0.valid = 0;
          if (y <= IMG_PROC_START) return;   // 扫到顶还没起步 → 丢弃整帧
          continue;
        }
      }
    } else {
      // 追踪: 从上一行中点向外扩张再向内扫
      const expand = ((last_valid_width / 2) | 0) + EXPAND_MARGIN;
      let searchL = last_valid_cx - expand; if (searchL < SCAN_X_MIN) searchL = SCAN_X_MIN;
      let searchR = last_valid_cx + expand; if (searchR > SCAN_X_MAX) searchR = SCAN_X_MAX;

      let nearLeft = scanRightForWhite(row, searchL, last_valid_cx + 5);
      let nearRight = scanLeftForWhite(row, searchR, last_valid_cx - 5);

      if (nearLeft < 0 && nearRight < 0) {
        nearLeft = scanRightForWhite(row, SCAN_X_MIN, last_valid_cx);
        nearRight = scanLeftForWhite(row, SCAN_X_MAX, last_valid_cx);
      }

      if (nearLeft >= 0) finalLeft = findLeftBoundary(row, nearLeft);
      if (nearRight >= 0) finalRight = findRightBoundary(row, nearRight);

      if (finalLeft === -1 && finalRight === -1) {
        // 断路: 边线放裁剪后边界, 中线居中
        currentCx = (IMG_W / 2) | 0;
        const p1 = s.ca[y];
        p1.cx = currentCx; p1.leftX = SCAN_X_MIN; p1.rightX = SCAN_X_MAX;
        p1.width = SCAN_X_MAX - SCAN_X_MIN; p1.valid = 0;
        consecutive_invalid++;
        if (consecutive_invalid >= 5) last_valid_cx = -1;
        continue;
      }
    }

    // 推算当前行中点 (只找到一边则滑动窗口搜另一边)
    if (finalLeft < 0 && finalRight >= 0) {
      const win_w = last_valid_width > 0 ? last_valid_width + 10 : 40;
      let win_r = finalRight - TRACK_MIN_WIDTH;
      let found = 0;
      while (win_r > SCAN_X_MIN) {
        let win_l = win_r - win_w; if (win_l < SCAN_X_MIN) win_l = SCAN_X_MIN;
        const white_x = scanLeftForWhite(row, win_r, win_l);
        if (white_x >= 0) { finalLeft = findLeftBoundary(row, white_x); found = 1; break; }
        win_r -= (win_w / 2) | 0;
      }
      if (!found) finalLeft = SCAN_X_MIN;
      currentCx = ((finalLeft + finalRight) / 2) | 0;
    } else if (finalRight < 0 && finalLeft >= 0) {
      const win_w = last_valid_width > 0 ? last_valid_width + 10 : 40;
      let win_l = finalLeft + TRACK_MIN_WIDTH;
      let found = 0;
      while (win_l < SCAN_X_MAX) {
        let win_r = win_l + win_w; if (win_r > SCAN_X_MAX) win_r = SCAN_X_MAX;
        const white_x = scanRightForWhite(row, win_l, win_r);
        if (white_x >= 0) { finalRight = findRightBoundary(row, white_x); found = 1; break; }
        win_l += (win_w / 2) | 0;
      }
      if (!found) finalRight = SCAN_X_MAX;
      currentCx = ((finalLeft + finalRight) / 2) | 0;
    } else if (finalLeft >= 0 && finalRight >= 0) {
      currentCx = ((finalLeft + finalRight) / 2) | 0;
    } else {
      currentCx = (IMG_W / 2) | 0;
    }

    let rawWidth = 0;
    let rawCx = 0;
    if (finalLeft >= 0 && finalRight >= 0 && finalLeft <= finalRight) {
      rawWidth = finalRight - finalLeft;
      rawCx = ((finalLeft + finalRight) / 2) | 0;
      // 起步校验: 最外两侧之间若还夹着其他白线 (多段) → 按离图像中心最近取段, 防止误连成一大段
      let interiorSegs = 0;
      if (last_valid_cx < 0) {
        let sx = finalLeft;
        while (sx <= finalRight) {
          const wx = scanRightForWhite(row, sx, finalRight + 1);   // +1: 覆盖右边界处起步的三白点
          if (wx < 0) break;
          const lx = findLeftBoundary(row, wx);
          const rx = findRightBoundary(row, wx);
          if (rx - lx >= TRACK_MIN_WIDTH) interiorSegs++;
          sx = rx + 1;
        }
      }
      if (rawWidth > TRACK_MAX_WIDTH || interiorSegs >= 2) {
        // 按离图像中心最近选段 (用户标定: 邻近中心取胜, 非按最窄/非按上一行锚定)
        const bounded = findBoundedTrackSegmentNear(row, (IMG_W / 2) | 0);
        if (bounded) {
          finalLeft = bounded.leftX;
          finalRight = bounded.rightX;
          currentCx = bounded.cx;
        } else {
          finalLeft = -1;
          finalRight = -1;
          currentCx = (IMG_W / 2) | 0;
        }
      }
    }

    if (currentCx < SCAN_X_MIN) currentCx = SCAN_X_MIN;
    if (currentCx > SCAN_X_MAX) currentCx = SCAN_X_MAX;

    // 写入本行
    if (finalLeft >= 0 && finalRight >= 0 && finalLeft <= finalRight) {
      currentWidth = finalRight - finalLeft;
      if (currentWidth >= TRACK_MIN_WIDTH && currentWidth <= TRACK_MAX_WIDTH) {
        isRowValid = 1;
        s.valid_rows_count++;
        if (currentWidth > s.max_width) { s.max_width = currentWidth; s.max_width_y = y; }
        last_valid_cx = currentCx;
        last_valid_width = currentWidth;
        consecutive_invalid = 0;
      }
    }
    if (rawWidth > s.raw_max_width) { s.raw_max_width = rawWidth; s.raw_max_width_y = y; }

    if (!isRowValid) {
      consecutive_invalid++;
      if (consecutive_invalid >= 5) last_valid_cx = -1;
    }

    const p = s.ca[y];
    p.cx = currentCx; p.valid = isRowValid; p.width = isRowValid ? currentWidth : 0;
    p.leftX = finalLeft; p.rightX = finalRight;
    p.raw_width = rawWidth || (isRowValid ? currentWidth : 0);
    p.raw_cx = rawCx || (isRowValid ? currentCx : 0);
    p.border_white = 0;
  }

  // 第 0..(IMG_PROC_START-1) 行: 远端不可靠, 全部作废
  for (let y = IMG_PROC_START - 1; y >= 0; y--) {
    const p = s.ca[y];
    p.valid = 0; p.width = 0; p.cx = (IMG_W / 2) | 0; p.leftX = -1; p.rightX = -1;
  }
}

/* ==================== 阶段4: 全行加权误差融合 (error_fusion) ==================== */

const MAX_FLIPS = 10;          // 符号翻转计数上限
const OUTLIER_THRESH = 10.0;   // 偏离均值超过10像素剔除
const FRONT_FUSION_ROWS = 10;

// 跨帧静态 (对应 C 的 static; 恢复模式/调速相关的 static 在 #if 0 内, 此处省略)
let _s_score = 0.5;
let _s_prev_bias_active = 0;
let _s_prev_bias_dir = 0;

export function errorFusionReset() {
  _s_score = 0.5;
  _s_prev_bias_active = 0;
  _s_prev_bias_dir = 0;
}

function resetDualPathState(s) {
  s.lateralError = 0;
  s.headingError = 0;
  s.headingErrorRaw = 0;
  s.nearValid = false;
  s.farValid = false;
  s.windowConflict = '';
  s.nearWindow = null;
  s.farWindow = null;
  s.dbg_dcx = 0;
  s.dbg_dcx_valid = 0;
  s.errNear = 0;
  s.errFar = 0;
  s.curvature = 0;
  s.ffW = 0;
  s.trackStraight = false;
  s.dpSel = 'none';
  s.dpStraightExitRequested = false;
  resetStraightSelector(s.straightSelector);
  s.prevBiasActive = 0; s.prevBiasDir = 0;
  s.recoveryActive = false; s.recoveryFrames = 0; s.recoveryHold = 0;
  s.recoveryLastDeltaCx = 0; s.carrySign = 0; s.biasExitAdjustRad = 0;
}

// 候选拐点仅用于元素判定和偏置决策，不再屏蔽其上方的有效中线；这样候选出现
// 后，远端预瞄、融合误差和质量分仍连续使用完整赛道信息。偏置确认激活时，
// 上方中线已由状态机改写，继续使用即可形成实际转向误差。
function isControlCenterlineRow(s, y) {
  return Boolean(s.ca[y]?.valid);
}

export function resetVisionState(s) {
  errorFusionReset();
  s.current_error = 0;
  s.last_error = 0;
  s.last_valid_rows = 0;
  s.target_base_v = 1.0;
  s.weighted_avg_cx = (IMG_W / 2) | 0;
  s.dbg_recovery_active = 0;
  s.dbg_score_pct = 50;
  s.corner_guard_active = 0; s.corner_guard_start_yaw = 0;
  s.dbg_corner_guard_active = 0;
  resetDualPathState(s);
}

export function updateDualPathOutputs(s, params) {
  const p = sanitizeDualPathParams(params);
  const cx = s.ca.map(point => point.cx);
  const valid = s.ca.map((_, y) => isControlCenterlineRow(s, y) ? 1 : 0);
  const windows = resolveDualPathWindows(p);
  const { y0: nearY0, y1: nearY1, rows: nearHeight } = windows.near;
  const { y0: farY0, y1: farY1, rows: farHeight } = windows.far;
  s.nearWindow = windows.near;
  s.farWindow = windows.far;
  s.windowConflict = windows.reason;
  const near = regionStat(cx, valid, nearY0, nearY1);
  const far = regionStat(cx, valid, farY0, farY1);
  const nearClean = windows.near.valid && regionClean(near.count, nearHeight);
  const farClean = windows.farUsable && regionClean(far.count, farHeight);
  s.nearValid = windows.near.valid && near.count >= 3;
  s.farValid = false;

  // 与固件一致：不足三行时以当前 EMA 输出为 raw，因而本帧保持不变。
  let rawNear = s.lateralError;
  const previousHeading = s.headingError;
  s.errFar = 0;
  s.headingErrorRaw = 0;
  s.headingError = 0;
  s.ffW = 0;
  s.trackStraight = false;
  s.dpSel = 'none';

  if (!s.bias_active) {
    if (s.nearValid) rawNear = near.mean - IMG_W / 2;
    if (s.nearValid && farClean && far.count >= 3) {
      s.errFar = far.mean - IMG_W / 2;
      s.headingErrorRaw = normalizeHeadingError(
        rawNear, s.errFar, windows.separationRows,
      );
      s.headingError = p.headingAlpha * s.headingErrorRaw
        + (1 - p.headingAlpha) * previousHeading;
      s.farValid = true;
    }
    resetStraightSelector(s.straightSelector);
  } else if (s.bias_dir !== 0) {
    if (s.nearValid) rawNear = near.mean - IMG_W / 2;
    s.ffW = cornerFeedForward(s.bias_dir, p.ffMaxW);
    resetStraightSelector(s.straightSelector);
  } else {
    const selected = selectStraightError(
      s.straightSelector,
      { error: near.mean - IMG_W / 2, clean: nearClean },
      { error: far.mean - IMG_W / 2, clean: farClean },
      { encoderCm: s.bias_start_encoder, glideCm: p.glideDistCm },
    );
    rawNear = selected.error;
    s.dpSel = selected.kind;
    if (selected.exitRequested) s.dpStraightExitRequested = true;
  }

  s.lateralError = p.lateralAlpha * rawNear
    + (1 - p.lateralAlpha) * s.lateralError;
  s.errNear = s.lateralError;
  s.curvature = s.headingError;
  s.dbg_dcx = s.headingErrorRaw;
  s.dbg_dcx_valid = s.nearValid && s.farValid ? 1 : 0;
  if (!s.bias_active) {
    s.trackStraight = Boolean(
      s.dbg_dcx_valid && Math.abs(s.headingErrorRaw) < p.slopeGyroResetPx,
    );
  }
}

// 主入口: 读 s.ca[], 写 s.current_error / weighted_avg_cx / target_base_v。忠实移植 error_fusion_run。
// 注: 固件里"偏置退出恢复模式"与"score 四档调速"均为 #if 0 关闭 → 忠实还原=不实现, 匀速 target_base_v=1.0。
export function errorFusionRun(s, params) {
  if (s.prevBiasActive && !s.bias_active && s.prevBiasDir !== 0) {
    s.recoveryActive = true;
    s.recoveryFrames = 0;
    s.recoveryHold = 0;
    s.recoveryLastDeltaCx = 0;
  }
  if (s.bias_active) {
    if (s.recoveryActive) {
      s.carrySign = Math.abs(s.recoveryLastDeltaCx) >= params.recoverAlignPx
        ? Math.sign(s.recoveryLastDeltaCx) : 0;
    }
    if (!s.prevBiasActive && s.bias_dir !== 0 && s.carrySign !== 0) {
      s.biasExitAdjustRad = s.bias_dir * s.carrySign
        * params.recoverCarryDeg * Math.PI / 180;
      s.carrySign = 0;
    }
    s.prevBiasDir = s.bias_dir;
    s.recoveryActive = false;
  }
  s.prevBiasActive = s.bias_active ? 1 : 0;

  // 信号①: 有效行占比
  const valid_ratio = s.valid_rows_count / IMG_PROC_H;

  // 信号②: 符号翻转计数
  let flips = 0, prev_sign = 0, valid_pairs = 0;
  for (let y = IMG_H - 1; y > IMG_PROC_START; y--) {
    if (!isControlCenterlineRow(s, y) || !isControlCenterlineRow(s, y - 1)) continue;
    valid_pairs++;
    const delta = s.ca[y].cx - s.ca[y - 1].cx;
    const sign = (delta > 1) ? 1 : ((delta < -1) ? -1 : prev_sign);
    if (prev_sign !== 0 && sign !== prev_sign) flips++;
    prev_sign = sign;
  }
  let flip_score;
  if (valid_pairs < 5) flip_score = 0.5;
  else { flip_score = 1.0 - flips / MAX_FLIPS; if (flip_score < 0.0) flip_score = 0.0; }

  // 信号③: 路口惩罚 (M1: bias_active=0 且 corner_y=-1 → 恒为0)
  let corner_penalty = 0.0;
  if (s.bias_active) {
    corner_penalty = (s.corner_y - IMG_PROC_START) / 40.0;
    if (corner_penalty > 0.6) corner_penalty = 0.6;
    if (corner_penalty < 0.0) corner_penalty = 0.0;
  } else if (s.corner_y >= 0) {
    corner_penalty = 0.15;
  }

  // score 合成 + EMA
  let raw_score;
  if (s.bias_active || s.corner_y >= 0) {
    raw_score = (1.0 * valid_ratio + 2.0 * flip_score + 5.0 * (1.0 - corner_penalty)) / 8.0;
  } else {
    raw_score = (1.0 * valid_ratio + 2.0 * flip_score) / 3.0;
  }
  _s_score = _s_score * 0.3 + raw_score * 0.7;

  // 等权平均 + 野点剔除
  let mean_cx = 0.0, mean_cnt = 0;
  for (let y = IMG_PROC_START; y < IMG_H; y++) {
    if (isControlCenterlineRow(s, y)) { mean_cx += s.ca[y].cx; mean_cnt++; }
  }
  if (mean_cnt > 0) mean_cx /= mean_cnt;

  let sum_cx = 0.0, sum_w = 0.0;
  for (let y = IMG_PROC_START; y < IMG_H; y++) {
    if (!isControlCenterlineRow(s, y)) continue;
    // 野点剔除跳过转弯偏置 (偏置行cx极端会拉偏均值)
    if (!s.bias_active || s.bias_dir === 0) {
      if (mean_cnt > 0 && Math.abs(s.ca[y].cx - mean_cx) > OUTLIER_THRESH) continue;
    }
    let w;
    if (s.bias_active && s.bias_dir === 0) {
      w = (y >= IMG_H - 5) ? 2.0 : 1.0;   // 直行偏置: 底部5行×2锚定中心
    } else if (s.recoveryActive) {
      const y_norm = (IMG_H - 1 - y) / IMG_PROC_H;
      w = Math.pow(1.0 - y_norm, params.recoverMagnet);
      if (w < 0.01) w = 0.01;
    } else {
      w = y < IMG_PROC_START + FRONT_FUSION_ROWS ? 2.0 : 1.0;
    }
    sum_cx += s.ca[y].cx * w;
    sum_w += w;
  }

  if (sum_w > 0.0) {
    const wcx = sum_cx / sum_w;
    s.weighted_avg_cx = wcx;
    const raw_error = wcx - ((IMG_W / 2) | 0);
    s.current_error = s.last_error + (raw_error - s.last_error) * 0.7;  // EMA α=0.7
    s.last_error = s.current_error;
  } else {
    s.current_error = s.last_error;          // 全无效: 保持上一帧误差, 不衰减
    s.weighted_avg_cx = (IMG_W / 2) | 0;
  }

  if (s.recoveryActive) {
    s.recoveryFrames++;
    if (s.nearValid && s.farValid) {
      s.recoveryLastDeltaCx = s.headingErrorRaw;
      s.recoveryHold = Math.abs(s.headingErrorRaw) < params.recoverAlignPx
        ? s.recoveryHold + 1 : 0;
    } else {
      s.recoveryHold = 0;
    }
    if (s.recoveryHold >= 3) {
      s.recoveryActive = false;
      s.carrySign = 0;
    } else if (s.recoveryFrames >= params.recoverMaxFrames) {
      s.recoveryActive = false;
      s.carrySign = Math.abs(s.recoveryLastDeltaCx) >= params.recoverAlignPx
        ? Math.sign(s.recoveryLastDeltaCx) : 0;
    }
  }
  s.dbg_recovery_active = s.recoveryActive ? 1 : 0;

  // 速度: #if 0 四档调速已关 → 匀速
  s.target_base_v = 1.0;
  s.last_valid_rows = s.valid_rows_count;
  s.dbg_score_pct = (_s_score * 100.0) | 0;
}

/* ==================== 阶段3: 拐点检测 + 路口 + 偏置状态机 (corner_detect) ==================== */


// 跨帧静态 (对应 C 的 static s_straight_frames / s_straight_next_seen / s_bias_start_corner_y)
let _cs_straight_frames = 0;
let _cs_straight_next_seen = 0;
let _cs_bias_start_corner_y = 0;

// 发车重置 (对应 camera_reset_queue): 清队列/偏置/跨帧状态
export function resetQueue(s) {
  s.current_queue_idx = 0; s.queue_matched = 0; s.queue_wrap_wait_clear = 0;
  s.bias_active = 0; s.bias_dir = 0; s.bias_is_mos = 0;
  s.corner_guard_active = 0; s.corner_guard_start_yaw = 0;
  s.dbg_corner_guard_active = 0;
  s.mos_bottom_seen = 0; s.mos_top_seen = 0; s.vote_history = 0;
  s.opamp_active = 0; s.opamp_stage = OpAmpStage.IDLE; s.opamp_queue_idx = -1;
  s.opamp_right_armed = 0; s.opamp_exit_wait_clear = 0;
  s.opamp_turn_accum_rad = 0; s.opamp_prev_yaw = s.yaw_accum;
  s.target_base_v = 1.0; s.current_error = 0; s.last_error = 0;
  s.weighted_avg_cx = (IMG_W / 2) | 0;
  _cs_straight_frames = 0; _cs_straight_next_seen = 0;
  _cs_bias_start_corner_y = 0;
  errorFusionReset();
  resetDualPathState(s);
}

// 消费一个队列节点；到达末项后立即从第 0 项开始下一轮。
function consumeQueueNode(s, queueLength) {
  const length = Math.max(0, Math.trunc(Number(queueLength) || 0));
  if (length <= 0) return;
  s.current_queue_idx++;
  if (s.current_queue_idx >= length) {
    s.current_queue_idx = 0;
    // 末项的画面仍可能留在视野中；先等它消失，才允许新一轮从第0项匹配。
    s.queue_wrap_wait_clear = 1;
  }
}

// 读取检测矩形两条竖边上、由白到黑的实际边界。y 由远到近递增，
// 因此白区末行就是赛道边界与矩形竖边的交点。
// 此函数只做几何测量，不参与元素分类；偏置锁定期间也可复用来显示当前画面。
// 探测框随候选拐点的远近缩放：远端/近端比例由参数滑块提供（默认 60%/150%），
// 中距离（约 y=30）保持原参数尺寸。这样远处不会把相邻结构一并罩进框内，
// 近处则保留足够的判定范围，且不改变既有中距离标定。
function getCornerBoxHalfSize(cy, params) {
  const span = IMG_H - 1 - IMG_PROC_START;
  const nearRatio = span > 0
    ? Math.max(0, Math.min(1, (cy - IMG_PROC_START) / span))
    : 1;
  const scale = params.boxFarScale + nearRatio * (params.boxNearScale - params.boxFarScale);
  return {
    halfW: Math.max(1, Math.round(params.boxHalfW * scale)),
    halfH: Math.max(1, Math.round(params.boxHalfH * scale)),
  };
}

// 矩形框内的 10 个固定采样点。点位覆盖上/中/下三层，并向左右边缘各内缩 1px，
// 既不会采到框外，也能覆盖路口支路最常出现的边缘区域。
function countCornerBoxSampleHits(bin, sx0, sx1, by0, by1) {
  const xMid = (sx0 + sx1) >> 1;
  const yMid = (by0 + by1) >> 1;
  const xLeft = Math.min(sx1, sx0 + 1);
  const xRight = Math.max(sx0, sx1 - 1);
  const yTop = Math.min(by1, by0 + 1);
  const yBottom = Math.max(by0, by1 - 1);
  const yUpper = by0 + Math.round((by1 - by0) * 0.25);
  const samples = [
    [xLeft, yTop], [xMid, yTop], [xRight, yTop],
    [xLeft, yMid], [xMid, yMid], [xRight, yMid],
    [xLeft, yBottom], [xMid, yBottom], [xRight, yBottom],
    [xMid, yUpper],
  ];
  let hits = 0;
  for (const [x, y] of samples) if (bin[y * IMG_W + x] > 128) hits++;
  return hits;
}

// 在一条竖向检测带内寻找连续白行；同一行内检测带的任一列为白即可。
function hasConsecutiveWhiteRows(bin, x0, x1, y0, y1, requiredRows = 3) {
  let consecutiveRows = 0;
  for (let y = y0; y <= y1; y++) {
    const rb = y * IMG_W;
    let rowHasWhite = false;
    for (let x = x0; x <= x1; x++) {
      if (bin[rb + x] > 128) { rowHasWhite = true; break; }
    }
    consecutiveRows = rowHasWhite ? consecutiveRows + 1 : 0;
    if (consecutiveRows >= requiredRows) return true;
  }
  return false;
}

function measureBoxSideIntersections(bin, cy, params) {
  const cx = IMG_W / 2 | 0;
  const { halfW, halfH } = getCornerBoxHalfSize(cy, params);
  const bx0 = cx - halfW, bx1 = cx + halfW;
  let by0 = cy - halfH; if (by0 < 0) by0 = 0;
  let by1 = cy + halfH; if (by1 >= IMG_H) by1 = IMG_H - 1;
  const sx0 = (bx0 < 0) ? 0 : bx0;
  const sx1 = (bx1 >= IMG_W) ? IMG_W - 1 : bx1;
  const xL0 = sx0;
  let xL1 = sx0 + CORNER.BOX_EDGE_BAND - 1; if (xL1 > sx1) xL1 = sx1;
  let xR0 = sx1 - CORNER.BOX_EDGE_BAND + 1; if (xR0 < sx0) xR0 = sx0;
  const xR1 = sx1;
  let prevLeftHit = 0, prevRightHit = 0;
  let leftY = -1, rightY = -1;
  let leftDistance = Infinity, rightDistance = Infinity;

  for (let y = by0; y <= by1; y++) {
    const rb = y * IMG_W;
    let leftHit = 0, rightHit = 0;
    for (let x = xL0; x <= xL1; x++) if (bin[rb + x] > 128) { leftHit = 1; break; }
    for (let x = xR0; x <= xR1; x++) if (bin[rb + x] > 128) { rightHit = 1; break; }
    if (prevLeftHit && !leftHit) {
      const yHit = y - 1;
      const distance = Math.abs(yHit - cy);
      if (distance < leftDistance) { leftY = yHit; leftDistance = distance; }
    }
    if (prevRightHit && !rightHit) {
      const yHit = y - 1;
      const distance = Math.abs(yHit - cy);
      if (distance < rightDistance) { rightY = yHit; rightDistance = distance; }
    }
    prevLeftHit = leftHit;
    prevRightHit = rightHit;
  }

  return {
    leftY,
    rightY,
    avgY: (leftY >= 0 && rightY >= 0) ? Math.round((leftY + rightY) / 2) : -1,
  };
}

// MOS 的拐点纵坐标必须与实际执行方向一致。队列动作优先，面板的强制左/右
// 又高于队列；直行不选侧点，继续使用普通宽度突跳拐点。
function resolveMosPointDirection(s, params, queueExpectedType) {
  let dir = s.corner_dir;
  if (queueExpectedType === JuncType.MOS && params.useQueueMode === 1) {
    const queuedAction = params.queueAction?.[s.current_queue_idx];
    if (queuedAction === -1 || queuedAction === 0 || queuedAction === 1) dir = queuedAction;
  }
  const forced = params.cornerBiasChoice;
  // “不偏置(0)”只禁止后续进入偏置态，不应把路线已指定的左/右 MOS 改成直行。
  if (forced === -1 || forced === 1) dir = forced;
  return dir < 0 ? -1 : (dir > 0 ? 1 : 0);
}

function selectMosCornerY(direction, leftY, rightY, avgY) {
  return direction < 0 ? leftY : (direction > 0 ? rightY : avgY);
}

function isOpAmpWaitStage(stage) {
  return stage === OpAmpStage.WAIT_RIGHT_1
    || stage === OpAmpStage.WAIT_RIGHT_2
    || stage === OpAmpStage.WAIT_RIGHT_3;
}

function startOpAmpBias(s, p, stage, dir, cornerY, useNormalTurnGuard = false) {
  s.opamp_stage = stage;
  s.bias_active = 1;
  s.bias_dir = dir;
  s.bias_corner_y = Math.max(0, Math.min(IMG_H - 1, cornerY));
  s.bias_start_yaw = s.yaw_accum;
  s.bias_start_encoder = 0;
  // 每个运放转向阶段单独按帧积分；反向惯性结束后，目标方向的首个增量立即开始计数。
  s.opamp_turn_accum_rad = 0;
  s.opamp_prev_yaw = s.yaw_accum;
  s.bias_is_mos = 0;
  s.mos_bottom_seen = 0;
  s.mos_top_seen = 0;
  s.straight_double = 0;
  s.biasExitAdjustRad = 0;
  s.dbg_control_corner_y = s.bias_corner_y;
  s.dbg_corner_dir = dir;
  _cs_straight_frames = 0;
  _cs_straight_next_seen = 0;
  _cs_bias_start_corner_y = s.bias_corner_y;

  if (useNormalTurnGuard && dir !== 0 && p.cornerDetectProtectYawDeg > 0) {
    s.corner_guard_active = 1;
    s.corner_guard_start_yaw = s.yaw_accum;
    s.dbg_corner_guard_active = 1;
  } else {
    s.corner_guard_active = 0;
    s.corner_guard_start_yaw = 0;
  }
}

function clearOpAmpBias(s, { keepGuard = false } = {}) {
  s.bias_active = 0;
  s.bias_dir = 0;
  s.bias_corner_y = 0;
  s.bias_is_mos = 0;
  s.mos_bottom_seen = 0;
  s.mos_top_seen = 0;
  s.corner_is_junction = 0;
  s.corner_junc_type = JuncType.NONE;
  s.vote_history = 0;
  s.straight_double = 0;
  s.biasExitAdjustRad = 0;
  _cs_straight_frames = 0;
  _cs_straight_next_seen = 0;
  if (!keepGuard) {
    s.corner_guard_active = 0;
    s.corner_guard_start_yaw = 0;
    s.dbg_corner_guard_active = 0;
  }
}

function opAmpManeuverFinished(s, p) {
  if (s.opamp_stage === OpAmpStage.ENTRY_STRAIGHT_M
      || s.opamp_stage === OpAmpStage.STRAIGHT_M) {
    s.bias_start_encoder += s.encoder_dist_delta;
    return s.bias_start_encoder >= p.opampStraightCm;
  }

  let exitDeg;
  let expectedDir;
  switch (s.opamp_stage) {
    case OpAmpStage.ENTRY_LEFT:
      exitDeg = p.opampX1Deg;
      expectedDir = -1;
      break;
    case OpAmpStage.ENTRY_RIGHT:
      exitDeg = p.opampX2Deg;
      expectedDir = 1;
      break;
    case OpAmpStage.RIGHT_1:
    case OpAmpStage.RIGHT_2:
      exitDeg = p.biasYawExitDeg + s.biasExitAdjustRad * 180 / Math.PI;
      expectedDir = 1;
      break;
    case OpAmpStage.FINAL_RIGHT:
      exitDeg = p.opampY1Deg;
      expectedDir = 1;
      break;
    case OpAmpStage.FINAL_LEFT:
      exitDeg = p.opampY2Deg;
      expectedDir = -1;
      break;
    default: return false;
  }
  if (exitDeg <= 0) return true;
  // 切换左右方向后，车体惯性及视觉延迟会让偏航短暂延续旧方向。
  // 逐帧只累加目标方向的正增量：惯性期间保持 0，实际反向后立即开始累计，
  // 不要求先把旧方向的惯性超调角“抵消回切换点”。
  const yawDelta = s.yaw_accum - s.opamp_prev_yaw;
  s.opamp_prev_yaw = s.yaw_accum;
  const directedDelta = yawDelta * expectedDir;
  if (directedDelta > 0) s.opamp_turn_accum_rad += directedDelta;
  return s.opamp_turn_accum_rad >= exitDeg * Math.PI / 180;
}

function advanceOpAmpManeuver(s, p) {
  const cornerY = s.bias_corner_y;
  switch (s.opamp_stage) {
    case OpAmpStage.ENTRY_LEFT:
      startOpAmpBias(s, p, OpAmpStage.ENTRY_RIGHT, 1, cornerY);
      break;
    case OpAmpStage.ENTRY_RIGHT:
      // 入口左右转完成后先执行元素直行 m，再恢复普通循迹等待首个右直角。
      startOpAmpBias(s, p, OpAmpStage.ENTRY_STRAIGHT_M, 0, cornerY);
      break;
    case OpAmpStage.ENTRY_STRAIGHT_M:
      clearOpAmpBias(s);
      s.opamp_stage = OpAmpStage.WAIT_RIGHT_1;
      // 前一元素是入口丁字，不存在“同一右直角重复触发”，首个右直角可直接响应。
      s.opamp_right_armed = 1;
      break;
    case OpAmpStage.RIGHT_1:
      // 第一个普通右转之后不是普通巡线，而是既有元素直行补线策略。
      startOpAmpBias(s, p, OpAmpStage.STRAIGHT_M, 0, cornerY);
      break;
    case OpAmpStage.STRAIGHT_M:
      clearOpAmpBias(s);
      s.opamp_stage = OpAmpStage.WAIT_RIGHT_2;
      s.opamp_right_armed = 0;
      break;
    case OpAmpStage.RIGHT_2:
      clearOpAmpBias(s, { keepGuard: true });
      s.opamp_stage = OpAmpStage.WAIT_RIGHT_3;
      s.opamp_right_armed = 0;
      break;
    case OpAmpStage.FINAL_RIGHT:
      startOpAmpBias(s, p, OpAmpStage.FINAL_LEFT, -1, cornerY);
      break;
    case OpAmpStage.FINAL_LEFT:
      clearOpAmpBias(s);
      if (s.queue_matched && s.current_queue_idx === s.opamp_queue_idx) {
        consumeQueueNode(s, p.queueLength);
      }
      s.queue_matched = 0;
      s.opamp_active = 0;
      s.opamp_stage = OpAmpStage.IDLE;
      s.opamp_queue_idx = -1;
      s.opamp_right_armed = 0;
      // 离开当前右直角前不允许后续队列节点被同一画面再次触发。
      s.opamp_exit_wait_clear = 1;
      return true;
    default:
      break;
  }
  return false;
}

function beginOpAmp(s, p) {
  s.opamp_active = 1;
  s.opamp_queue_idx = s.current_queue_idx;
  s.opamp_right_armed = 0;
  s.opamp_exit_wait_clear = 0;
  s.queue_matched = 1;
  startOpAmpBias(s, p, OpAmpStage.ENTRY_LEFT, -1, s.corner_y);
}

// 主入口: 忠实移植 corner_detect_run。读 s.ca[] 与 s.bin[], 写拐点/路口/偏置后的 cx。
export function cornerDetectRun(s, params) {
  const bin = s.bin;
  const p = sanitizeDualPathParams(params);
  const queueExpectedType = (params.useQueueMode === 1
    && s.current_queue_idx < params.queueLength)
    ? params.queueJuncType[s.current_queue_idx]
    : JuncType.NONE;
  let gap = params.cornerGap;
  let skip_junction = 0;
  let opampCompletedThisFrame = false;

  s.corner_y = -1;
  s.corner_dir = 0;
  if (!s.bias_active) { s.corner_is_junction = 0; s.corner_junc_type = JuncType.NONE; }
  s.dbg_corner_y = -1; s.dbg_corner_cx = 0; s.dbg_corner_dir = 0; s.dbg_control_corner_y = -1;
  s.dbg_corner_reached_activation = 0;
  s.dbg_corner_guard_active = 0;
  s.dbg_mos_corner_valid = 0;
  s.dbg_box_w = 0; s.dbg_box_h = 0; s.dbg_box_y = -1;
  s.dbg_box_sample_hits = 0; s.dbg_box_sample_veto = 0;
  s.dbg_has_top = 0; s.dbg_has_bottom = 0; s.dbg_has_left = 0; s.dbg_has_right = 0;
  s.dbg_left_intersection_y = -1; s.dbg_right_intersection_y = -1; s.dbg_intersection_avg_y = -1;
  s.dbg_interference_votes = 0;

  if (gap < 1) gap = 1;
  if (s.bias_corner_y >= IMG_H) s.bias_corner_y = IMG_H - 1;
  if (s.bias_corner_y < 0) s.bias_corner_y = 0;

  // ===== 1. 偏置退出检查 =====
  if (s.bias_active && s.opamp_active) {
    if (opAmpManeuverFinished(s, p)) {
      opampCompletedThisFrame = advanceOpAmpManeuver(s, p);
    }
  } else if (s.bias_active) {
    let should_exit = 0;
    if (s.bias_dir !== 0) {
      const accum_yaw = s.yaw_accum - s.bias_start_yaw;
      const abs_yaw = Math.abs(accum_yaw);
      const biasYawExitRad = p.biasYawExitDeg * Math.PI / 180;
      // MOS 转弯不再硬编码 30° 退出: 与正常左右转一致用 biasYawExitDeg (面板可调)
      const exit_rad = biasYawExitRad
        + s.biasExitAdjustRad;
      if (abs_yaw >= exit_rad) should_exit = 1;
    } else {
      s.bias_start_encoder += s.encoder_dist_delta;
      _cs_straight_frames++;
      const timeout = (_cs_straight_frames >= p.straightTimeoutFrames);
      // 注: MOS 直行不再用 mos_bottom_seen&&mos_top_seen 即时退出 (仿真底行锚定使该判据
      // 要么激活帧瞬间双中、要么永远凑不齐), 统一按编码器里程退出; seen 标志仍置位供 OSD。
      if (s.queue_matched
        && s.current_queue_idx + 1 < params.queueLength
        && params.queueAction[s.current_queue_idx + 1] === 0) {
        if (s.corner_y >= 0 && s.corner_y < _cs_bias_start_corner_y - 5 && s.corner_is_junction) {
          const expected = params.queueJuncType[s.current_queue_idx + 1];
          if (s.corner_junc_type === expected) _cs_straight_next_seen = 1;
        }
        if (_cs_straight_next_seen || s.bias_start_encoder >= p.straightExitCm || timeout) should_exit = 1;
      } else {
        // 其余直行偏置 (S 后接转向 / 队列末尾 / 特殊路口策略直行): 同样按编码器积分 60cm 退出
        if (s.bias_start_encoder >= p.straightExitCm || timeout) should_exit = 1;
      }
    }
    if (should_exit) {
      s.bias_active = 0; s.bias_dir = 0; s.bias_is_mos = 0;
      s.mos_bottom_seen = 0; s.mos_top_seen = 0;
      s.corner_is_junction = 0; s.corner_junc_type = JuncType.NONE;
      s.vote_history = 0; _cs_straight_frames = 0; _cs_straight_next_seen = 0;
      if (s.queue_matched) {
        consumeQueueNode(s, params.queueLength);
        s.queue_matched = 0;
      }
      s.straight_double = 0;
      s.biasExitAdjustRad = 0;
    }
  }

  // 转弯偏置退出后，仍以该次转弯的起始偏航为基准保留防重检角度盲区。
  // 这样退出角小于保护角时，不会在出弯过程把残留路口结构重新当成新拐点。
  let cornerGuardActive = false;
  if (s.corner_guard_active) {
    const protectYawRad = p.cornerDetectProtectYawDeg * Math.PI / 180;
    const turnedRad = Math.abs(s.yaw_accum - s.corner_guard_start_yaw);
    if (protectYawRad <= 0 || turnedRad >= protectYawRad) {
      s.corner_guard_active = 0;
    } else {
      cornerGuardActive = true;
      s.dbg_corner_guard_active = 1;
    }
  }

  // ===== 2. 扫描拐点 (跨gap行宽度突跳) =====
  if (!s.bias_active && !cornerGuardActive) {
    for (let y = IMG_H - 1 - gap; y >= IMG_PROC_START + gap; y--) {
      const yb = y + gap;
      const wy = s.ca[y].raw_width || s.ca[y].width;
      const wyb = s.ca[yb].raw_width || s.ca[yb].width;
      const yValid = s.ca[y].valid || wy >= TRACK_MIN_WIDTH;
      const ybValid = s.ca[yb].valid || wyb >= TRACK_MIN_WIDTH;
      if (yValid && ybValid
        && wy >= CORNER.WIDTH_JUMP_MIN && wyb >= TRACK_MIN_WIDTH) {
        const ratio = wy / wyb;
        if (ratio >= CORNER.WIDTH_JUMP_RATIO) {
          const cy = s.ca[y].raw_cx || s.ca[y].cx;
          const cyb = s.ca[yb].raw_cx || s.ca[yb].cx;
          const delta_cx = cy - (IMG_W / 2 | 0);
          s.corner_dir = (delta_cx > 5) ? 1 : ((delta_cx < -5) ? -1 : 0);
          if (s.corner_dir === 0) {
            const trend = cy - cyb;
            s.corner_dir = (trend > 0) ? 1 : ((trend < 0) ? -1 : 0);
          }
          s.corner_y = y;
          s.dbg_corner_y = y; s.dbg_corner_cx = cy; s.dbg_corner_dir = s.corner_dir;
          break;
        }
      }
    }
  } else if (s.bias_active) {
    // 黄色矩形框锁定即执行偏置状态: 状态退出前不再找新拐点, 冻结在锁定位置
    s.corner_dir = s.bias_dir;
    s.corner_y = s.bias_corner_y;
    s.dbg_corner_y = s.corner_y;
    s.dbg_corner_cx = (s.corner_y >= 0) ? s.ca[s.corner_y].cx : 0;
    s.dbg_control_corner_y = s.corner_y;
    s.dbg_corner_dir = s.bias_dir;
    if (s.corner_y >= 0) {
      const { halfW, halfH } = getCornerBoxHalfSize(s.corner_y, p);
      s.dbg_box_w = halfW * 2; s.dbg_box_h = halfH * 2; s.dbg_box_y = s.corner_y;
      // 黄框代表已锁定的控制拐点。仍测量当前帧交点，供界面核对，
      // 但绝不能改写 bias_corner_y，否则转弯过程中会被画面移动拖动。
      const liveIntersections = measureBoxSideIntersections(bin, s.corner_y, p);
      s.dbg_left_intersection_y = liveIntersections.leftY;
      s.dbg_right_intersection_y = liveIntersections.rightY;
      s.dbg_intersection_avg_y = liveIntersections.avgY;
      // MOS 只在左/右转时使用同侧交点；直行沿用普通拐点，不受交点变化影响。
      // 黄圈仍表示已锁定的控制参考点。
      const liveCornerY = s.bias_dir === 0 ? -1 : selectMosCornerY(s.bias_dir,
        liveIntersections.leftY, liveIntersections.rightY, liveIntersections.avgY);
      if (s.bias_is_mos && liveCornerY >= 0) {
        s.dbg_corner_y = liveCornerY;
        s.dbg_corner_cx = IMG_W / 2 | 0;
      }
    }
  }

  if (s.corner_y >= IMG_H) s.corner_y = IMG_H - 1;
  if (s.corner_y < 0 && s.bias_active && s.bias_corner_y >= 0) {
    s.corner_y = s.bias_corner_y; s.corner_dir = s.bias_dir;
    s.dbg_corner_y = s.bias_corner_y; s.dbg_corner_cx = s.ca[s.bias_corner_y].cx; s.dbg_corner_dir = s.bias_dir;
  }
  const detected_corner_y = s.corner_y;

  // ===== 2.5 干扰元素投票否决 (暂时注释: 用户要求停用; 恢复时取消下方 /* */ 注释) =====
  skip_junction = 0;
  /*
  if (s.corner_y >= 0 && !s.bias_active) {
    let skip_vote = 0;
    if (params.useQueueMode === 1 && s.current_queue_idx < params.queueLength
      && params.queueJuncType[s.current_queue_idx] === 7) skip_vote = 1;
    if (!skip_vote) {
      const cy = s.corner_y;
      let y0 = cy - 20; if (y0 < 0) y0 = 0;
      let y1 = cy + 20; if (y1 >= IMG_H) y1 = IMG_H - 1;
      let max_consecutive = 0, cur_consecutive = 0;
      for (let yi = y0; yi <= y1; yi++) {
        const rb = yi * IMG_W;
        let segments = 0, run = 0;
        for (let xi = 0; xi < IMG_W; xi++) {
          if (bin[rb + xi] > 128) run++;
          else { if (run >= TRACK_MIN_WIDTH) segments++; run = 0; }
        }
        if (run >= TRACK_MIN_WIDTH) segments++;
        if (segments >= 2) { cur_consecutive++; if (cur_consecutive > max_consecutive) max_consecutive = cur_consecutive; }
        else cur_consecutive = 0;
      }
      s.dbg_interference_votes = max_consecutive;
      if (max_consecutive >= 5) {
        s.corner_is_junction = 0; s.corner_junc_type = JuncType.NONE; s.corner_y = -1; skip_junction = 1;
      }
    }
  }
  */

  // ===== 3. 矩形框路口分类 (偏置执行期冻结: 不重找拐点/不重分类) =====
  if (s.corner_y >= 0 && !skip_junction && !s.bias_active) {
    const cy = s.corner_y;
    const cx = IMG_W / 2 | 0;
    const { halfW, halfH } = getCornerBoxHalfSize(cy, p);
    const bx0 = cx - halfW, bx1 = cx + halfW;
    let by0 = cy - halfH; if (by0 < 0) by0 = 0;
    let by1 = cy + halfH; if (by1 >= IMG_H) by1 = IMG_H - 1;
    const sx0 = (bx0 < 0) ? 0 : bx0;
    const sx1 = (bx1 >= IMG_W) ? IMG_W - 1 : bx1;
    s.dbg_box_w = bx1 - bx0; s.dbg_box_h = by1 - by0; s.dbg_box_y = cy;

    // 先做低成本的框内白点否决。10 个代表点全部为黑时，不把宽度突跳
    // 当作可执行的路口/拐点，防止空框或噪声候选触发偏置。
    s.dbg_box_sample_hits = countCornerBoxSampleHits(bin, sx0, sx1, by0, by1);
    s.dbg_box_sample_veto = s.dbg_box_sample_hits === 0 ? 1 : 0;

    if (!s.dbg_box_sample_veto) {

    let cntTop = 0, cntBot = 0;

    // 上下边带
    let yt_end = by0 + CORNER.BOX_EDGE_BAND - 1; if (yt_end > by1) yt_end = by1;
    for (let y = by0; y <= yt_end; y++) { const rb = y * IMG_W; for (let x = sx0; x <= sx1; x++) if (bin[rb + x] > 128) cntTop++; }
    let yb_start = by1 - CORNER.BOX_EDGE_BAND + 1; if (yb_start < by0) yb_start = by0;
    for (let y = yb_start; y <= by1; y++) { const rb = y * IMG_W; for (let x = sx0; x <= sx1; x++) if (bin[rb + x] > 128) cntBot++; }

    // 左右边带默认只在拐点上下 10 行内检测，且要求至少连续 3 行有白点。
    // 队列当前期待 MOS 或十字时，侧支可能远离普通候选拐点行，改为扫描完整框高；
    // 其他元素仍限于拐点上下 10 行，抑制远离候选点的误判。
    const useFullBoxSideScan = queueExpectedType === JuncType.MOS
      || queueExpectedType === JuncType.CROSS;
    const sideY0 = useFullBoxSideScan ? by0 : Math.max(by0, cy - 10);
    const sideY1 = useFullBoxSideScan ? by1 : Math.min(by1, cy + 10);
    const xL_in0 = sx0; let xL_in1 = sx0 + CORNER.BOX_EDGE_BAND - 1; if (xL_in1 > sx1) xL_in1 = sx1;
    let xR_in0 = sx1 - CORNER.BOX_EDGE_BAND + 1; if (xR_in0 < sx0) xR_in0 = sx0; const xR_in1 = sx1;
    // 交点测量独立完成，避免与此处的分类门槛耦合。

    let hasTop = (cntTop >= CORNER.BOX_TOP_THRESH);
    let hasBot = (cntBot >= CORNER.BOX_BOT_THRESH);
    // 记录矩形框内侧带的原始结果。左右 T 的对侧否决只看它，不能被后续
    // 的框外贯穿验证覆盖。
    const boxHasL = hasConsecutiveWhiteRows(bin, xL_in0, xL_in1, sideY0, sideY1);
    const boxHasR = hasConsecutiveWhiteRows(bin, xR_in0, xR_in1, sideY0, sideY1);
    let hasL = boxHasL;
    let hasR = boxHasR;

    // 外侧贯穿验证：与框内侧带使用相同扫描范围，且要求连续 3 行白点。
    if (hasL) {
      const xLo = bx0 - CORNER.BOX_OUTER_OFFSET;
      let xLo0 = xLo - 1, xLo1 = xLo + 1;
      if (xLo0 < 0) xLo0 = 0; if (xLo1 >= IMG_W) xLo1 = IMG_W - 1;
      if (xLo1 < 0) hasL = 0;
      else hasL = hasConsecutiveWhiteRows(bin, xLo0, xLo1, sideY0, sideY1);
    }
    if (hasR) {
      const xRo = bx1 + CORNER.BOX_OUTER_OFFSET;
      let xRo0 = xRo - 1, xRo1 = xRo + 1;
      if (xRo0 < 0) xRo0 = 0; if (xRo1 >= IMG_W) xRo1 = IMG_W - 1;
      if (xRo0 >= IMG_W) hasR = 0;
      else hasR = hasConsecutiveWhiteRows(bin, xRo0, xRo1, sideY0, sideY1);
    }

    const intersections = measureBoxSideIntersections(bin, cy, p);
    const validatedLeftIntersectionY = hasL ? intersections.leftY : -1;
    const validatedRightIntersectionY = hasR ? intersections.rightY : -1;
    const intersectionAvgY = validatedLeftIntersectionY >= 0 && validatedRightIntersectionY >= 0
      ? Math.round((validatedLeftIntersectionY + validatedRightIntersectionY) / 2) : -1;
    s.dbg_left_intersection_y = validatedLeftIntersectionY;
    s.dbg_right_intersection_y = validatedRightIntersectionY;
    s.dbg_intersection_avg_y = intersectionAvgY;

    s.dbg_has_top = hasTop ? 1 : 0; s.dbg_has_bottom = hasBot ? 1 : 0;
    s.dbg_has_left = hasL ? 1 : 0; s.dbg_has_right = hasR ? 1 : 0;

    if (params.useQueueMode === 1) hasBot = true;

    // 队列已明确指定直角元素，或运放状态机正在等待右直角时，顶部可能仍落在
    // 检测框中；此时不将 hasTop 作为直角弯的否决条件，避免把运放内右直角误判为右 T。
    const opampWaitsForRightAngle = queueExpectedType === JuncType.OPAMP
      && s.opamp_active && isOpAmpWaitStage(s.opamp_stage);

    if (queueExpectedType === JuncType.MOS
      && hasBot && ((hasTop ? 1 : 0) + (hasL ? 1 : 0) + (hasR ? 1 : 0)) >= 2) {
      s.corner_is_junction = 1; s.corner_junc_type = JuncType.MOS;
      const mosDirection = resolveMosPointDirection(s, p, queueExpectedType);
      if (mosDirection === 0) {
        // MOS 直行直接使用普通宽度突跳拐点，不依赖左右交点。
        s.dbg_mos_corner_valid = 1;
      } else {
        // MOS 左/右转才使用同侧交点，横坐标固定为图像中心。
        const mosCornerY = selectMosCornerY(mosDirection,
          validatedLeftIntersectionY, validatedRightIntersectionY, intersectionAvgY);
        if (mosCornerY >= 0) {
          s.dbg_mos_corner_valid = 1;
          s.corner_y = mosCornerY;
          s.dbg_corner_y = mosCornerY;
          s.dbg_corner_cx = IMG_W / 2 | 0;
        }
      }
      // 图像 y 向下增大：点到达/越过激活行时，矩形才显示金色。
      s.dbg_corner_reached_activation = (s.dbg_mos_corner_valid && s.corner_y >= p.cornerActivateMinY) ? 1 : 0;
    } else if (queueExpectedType === JuncType.L_LEFT && hasBot && hasL && !hasR) {
      s.corner_is_junction = 1; s.corner_junc_type = JuncType.L_LEFT;
    } else if ((queueExpectedType === JuncType.L_RIGHT || opampWaitsForRightAngle)
      && hasBot && !hasL && hasR) {
      s.corner_is_junction = 1; s.corner_junc_type = JuncType.L_RIGHT;
    } else if (hasTop && hasBot && hasL && hasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.CROSS; }
    // 左右 T：本侧沿用既有的框外贯穿验证；对侧只要在矩形框内判有侧连通，
    // 就否决单侧 T。底边不参与左右 T 分类。
    else if (hasTop && hasL && !boxHasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.T_LEFT; }
    else if (hasTop && !boxHasL && hasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.T_RIGHT; }
    else if (!hasTop && hasL && hasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.T_END; }
    else if (!hasTop && hasBot && hasL && !hasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.L_LEFT; }
    else if (!hasTop && hasBot && !hasL && hasR) { s.corner_is_junction = 1; s.corner_junc_type = JuncType.L_RIGHT; }
    }
  }

  // ===== T_END 密度兜底 =====
  if (detected_corner_y >= 0 && !s.corner_is_junction && !s.dbg_box_sample_veto) {
    let dense_run = 0, max_dense = 0;
    let ys = detected_corner_y - 8; if (ys < IMG_PROC_START) ys = IMG_PROC_START;
    let ye = detected_corner_y + 5; if (ye >= IMG_H) ye = IMG_H - 1;
    for (let yi = ys; yi <= ye; yi++) {
      let wcnt = 0; const rb = yi * IMG_W;
      for (let xi = 0; xi < IMG_W; xi++) if (bin[rb + xi] > 128) wcnt++;
      if (wcnt >= (IMG_W * 80 / 100 | 0)) { dense_run++; if (dense_run > max_dense) max_dense = dense_run; }
      else dense_run = 0;
    }
    if (max_dense >= 3) {
      s.corner_is_junction = 1; s.corner_junc_type = JuncType.T_END;
      if (s.corner_y < 0) s.corner_y = detected_corner_y;
    }
  }

  // ===== 3.5 超级大号运放独立状态机入口/右直角推进 =====
  const detectedRightAngle = s.corner_is_junction
    && s.corner_junc_type === JuncType.L_RIGHT;
  const reachedActivation = s.corner_y >= p.cornerActivateMinY;
  const opampExitBlocked = opampCompletedThisFrame || Boolean(s.opamp_exit_wait_clear);

  // 运放结束后，必须先看到一帧无路口画面，防止第三个右直角继续触发后续队列。
  if (s.opamp_exit_wait_clear && !s.corner_is_junction) {
    s.opamp_exit_wait_clear = 0;
  }
  if (s.queue_wrap_wait_clear && !s.corner_is_junction) {
    s.queue_wrap_wait_clear = 0;
  }

  if (!opampExitBlocked && !s.opamp_active
    && queueExpectedType === JuncType.OPAMP
    && s.corner_is_junction && s.corner_junc_type === JuncType.T_END
    && reachedActivation && !s.dbg_box_sample_veto) {
    beginOpAmp(s, p);
  } else if (s.opamp_active && isOpAmpWaitStage(s.opamp_stage)) {
    // 每个右直角必须在离开上一个右直角后重新武装，不能由同一检测连续跳级。
    if (!cornerGuardActive && !detectedRightAngle) s.opamp_right_armed = 1;
    if (!cornerGuardActive && s.opamp_right_armed && detectedRightAngle
      && reachedActivation && !s.dbg_box_sample_veto) {
      s.opamp_right_armed = 0;
      if (s.opamp_stage === OpAmpStage.WAIT_RIGHT_1) {
        startOpAmpBias(s, p, OpAmpStage.RIGHT_1, 1, s.corner_y, true);
      } else if (s.opamp_stage === OpAmpStage.WAIT_RIGHT_2) {
        startOpAmpBias(s, p, OpAmpStage.RIGHT_2, 1, s.corner_y, true);
      } else {
        startOpAmpBias(s, p, OpAmpStage.FINAL_RIGHT, 1, s.corner_y);
      }
    }
  }

  const opampOwnsActivation = opampExitBlocked || s.opamp_active
    || queueExpectedType === JuncType.OPAMP;

  // ===== 4. 确定偏置方向并激活 =====
  if (!opampOwnsActivation && s.corner_y >= 0 && !s.bias_active && !s.dbg_box_sample_veto
    && (!skip_junction || s.corner_is_junction)) {
    let target_dir = 0;
    let should_activate = 1;
    if (s.corner_is_junction) {
      switch (s.corner_junc_type) {
        case JuncType.CROSS: target_dir = params.crossChoice; break;
        case JuncType.T_LEFT: target_dir = (params.leftTChoice !== 0) ? -1 : 0; break;
        case JuncType.T_RIGHT: target_dir = (params.rightTChoice !== 0) ? 1 : 0; break;
        case JuncType.T_END: target_dir = params.bjtChoice; break;
        case JuncType.L_LEFT: target_dir = -1; break;
        case JuncType.L_RIGHT: target_dir = 1; break;
        case JuncType.MOS: target_dir = s.corner_dir; break;
        default: target_dir = s.corner_dir; break;
      }
      if (params.useQueueMode === 1) {
        if (s.current_queue_idx < params.queueLength) {
          const expected_type = params.queueJuncType[s.current_queue_idx];
          const expected_act = params.queueAction[s.current_queue_idx];
          let match = 0;
          switch (expected_type) {
            case 1: match = (s.corner_junc_type === JuncType.T_END); break;
            case 2: match = (s.corner_junc_type === JuncType.T_LEFT); break;
            case 3: match = (s.corner_junc_type === JuncType.T_RIGHT); break;
            case 4: match = (s.corner_junc_type === JuncType.CROSS); break;
            case 5: match = (s.corner_junc_type === JuncType.L_LEFT); break;
            case 6: match = (s.corner_junc_type === JuncType.L_RIGHT); break;
            case 7: match = (s.corner_junc_type === JuncType.MOS); break;
            case 8: match = 0; break; // 运放由上方入口丁字专用状态机接管。
            default: match = 0; break;
          }
          if (match) { target_dir = expected_act; s.queue_matched = 1; }
          // MOS 是“目标侧交点到位”后才可执行的严格元素；不可用普通 L/T/CROSS
          // 的队列兜底提前消费，否则会在紫点未到激活行时转向。
          else if (s.corner_is_junction && expected_type === JuncType.NONE) {
            target_dir = expected_act; s.queue_matched = 1;
          }
          // MOS 直行可按普通路口通过；左/右转仍须命中 MOS 专用判定。
          else if (s.corner_is_junction && expected_type === JuncType.MOS && expected_act === 0) {
            target_dir = expected_act; s.queue_matched = 1;
          }
          else should_activate = 0;
        } else should_activate = 0;
      }
    } else should_activate = 0;

    // 仿真面板可直接决定识别到的拐点后是否改写拐点以上中线。
    // 自动(2)保持路口/队列策略；不偏置(0)不进入 bias 状态，保留原始中线；
    // 左/右(-1/1)可用于普通拐点或路口的定向偏置测试。
    const cornerBiasChoice = [-1, 0, 1, 2].includes(params.cornerBiasChoice) ? params.cornerBiasChoice : 2;
    if (cornerBiasChoice === 0) {
      should_activate = 0;
    } else if (cornerBiasChoice === -1 || cornerBiasChoice === 1) {
      target_dir = cornerBiasChoice;
      should_activate = 1;
    }

    const queueExpectsMos = params.useQueueMode === 1
      && s.current_queue_idx < params.queueLength
      && params.queueJuncType[s.current_queue_idx] === JuncType.MOS;
    const queueMosAction = queueExpectsMos ? (params.queueAction[s.current_queue_idx] ?? 0) : 0;
    // MOS 直行按普通拐点执行；仅 MOS 左/右转要求同侧交点有效。
    if (queueExpectsMos && queueMosAction !== 0
      && (s.corner_junc_type !== JuncType.MOS || !s.dbg_mos_corner_valid)) {
      should_activate = 0;
      s.queue_matched = 0;
    }
    // 刚完成一整轮时，不得用最后一个节点残留画面立即匹配新一轮的第0项。
    if (params.useQueueMode === 1 && s.queue_wrap_wait_clear) {
      should_activate = 0;
      s.queue_matched = 0;
    }
    if (should_activate && s.corner_y < p.cornerActivateMinY) should_activate = 0;

    if (should_activate) {
      s.bias_active = 1; s.bias_dir = target_dir; s.bias_corner_y = s.corner_y;
      s.dbg_control_corner_y = s.corner_y;
      s.bias_start_yaw = s.yaw_accum; s.bias_start_encoder = 0.0;
      if (target_dir !== 0 && p.cornerDetectProtectYawDeg > 0) {
        s.corner_guard_active = 1;
        s.corner_guard_start_yaw = s.yaw_accum;
        s.dbg_corner_guard_active = 1;
      } else {
        s.corner_guard_active = 0;
        s.corner_guard_start_yaw = 0;
      }
      if (target_dir === 0) _cs_straight_frames = 0;
      s.bias_is_mos = (s.corner_junc_type === JuncType.MOS) ? 1 : 0;
      s.mos_bottom_seen = 0; s.mos_top_seen = 0; s.straight_double = 0;
      s.dbg_corner_dir = target_dir;
      _cs_bias_start_corner_y = s.corner_y; _cs_straight_next_seen = 0;
      // 连续双直行策略已移除 (用户要求): 每个 S 节点独立锁黄框、独立按 60cm 退出并逐个消费
      // (原固件此处对 S 后紧跟 S 置 straight_double=1, 一次贯穿两路口并一次消费两项)
    }
  }

  // ===== 5. 偏置中线 =====
  if (s.bias_active) {
    if (s.bias_dir === 0) {
      const top_cx_buf = [], bot_cx_buf = [];
      const cx_mid = IMG_W / 2 | 0;
      // 顶部3行
      for (let y = IMG_PROC_START; y < IMG_PROC_START + 3 && y < IMG_H; y++) {
        let sum_x = 0, cnt_x = 0; const rb = y * IMG_W;
        for (let xi = 0; xi < IMG_W; xi++) if (bin[rb + xi] > 128) { sum_x += xi; cnt_x++; }
        if (cnt_x >= TRACK_MIN_WIDTH) { const cxv = (sum_x / cnt_x) | 0; if (cxv >= cx_mid - 5 && cxv <= cx_mid + 5) top_cx_buf.push(cxv); }
      }
      // 底部3行
      for (let y = IMG_H - 3; y < IMG_H; y++) {
        if (s.ca[y].valid) { const cxv = s.ca[y].cx; if (cxv >= cx_mid - 5 && cxv <= cx_mid + 5) bot_cx_buf.push(cxv); }
      }
      if (top_cx_buf.length >= 2 && bot_cx_buf.length >= 2) {
        let top_avg = 0, bot_avg = 0;
        for (const v of top_cx_buf) top_avg += v;
        for (const v of bot_cx_buf) bot_avg += v;
        top_avg /= top_cx_buf.length; bot_avg /= bot_cx_buf.length;
        for (let y = IMG_PROC_START; y < IMG_H; y++) {
          const t = (y - IMG_PROC_START) / (IMG_PROC_H - 1);
          s.ca[y].cx = (top_avg + (bot_avg - top_avg) * t) | 0;
          s.ca[y].valid = 1;
        }
      }
      // MOS 拐点追踪
      if (s.bias_is_mos) {
        if (bot_cx_buf.length < 2) {
          let last_y = -1;
          for (let y = IMG_H - 1; y >= IMG_PROC_START; y--) if (s.ca[y].valid) { last_y = y; break; }
          if (last_y >= 0 && top_cx_buf.length >= 2) {
            let top_avg = 0; for (const v of top_cx_buf) top_avg += v; top_avg /= top_cx_buf.length;
            for (let y = IMG_PROC_START; y <= last_y; y++) {
              const t = (last_y - y) / (last_y - IMG_PROC_START);
              s.ca[y].cx = (s.ca[last_y].cx + (top_avg - s.ca[last_y].cx) * t) | 0;
              s.ca[y].valid = 1;
            }
          }
          s.mos_top_seen = 1;
        }
        if (top_cx_buf.length < 2) s.mos_bottom_seen = 1;
      }
      // 底部5行锚定中心
      for (let y = IMG_H - 5; y < IMG_H; y++) { s.ca[y].cx = IMG_W / 2 | 0; s.ca[y].valid = 1; }
    } else {
      // 转弯偏置: 拐点以上拉到边界
      const bias_cx = (s.bias_dir === -1) ? 0 : (IMG_W - 1);
      for (let y = IMG_PROC_START; y < s.corner_y && y < IMG_H; y++) { s.ca[y].cx = bias_cx; s.ca[y].valid = 1; }
    }
    // 重新统计有效行
    s.valid_rows_count = 0;
    for (let y = IMG_PROC_START; y < IMG_H; y++) if (s.ca[y].valid) s.valid_rows_count++;
  }
}

/* ==================== 阶段0: 预处理 (2x2下采样 + 180°翻转) ==================== */

// 原图 188×120 → 94×60。忠实移植 preprocess_downsample + FLIP_180_SRC。
// srcGray: 行主序灰度 Uint8Array(MT9V03X_W*MT9V03X_H) = 188*120, 索引 row*188+col。
// FLIP_180_SRC(r2,c2) = src[(120-1-r2)*188 + (188-1-c2)] (镜头物理翻转180°)。
export function downsample2x2(srcGray, out) {
  out = out || new Uint8Array(IMG_W * IMG_H);
  const SW = MT9V03X_W;   // 188
  const SH = MT9V03X_H;   // 120
  for (let r = 0; r < IMG_H; r++) {
    const rr0 = (SH - 1 - r * 2) * SW;
    const rr1 = (SH - 1 - (r * 2 + 1)) * SW;
    for (let c = 0; c < IMG_W; c++) {
      const cc0 = SW - 1 - c * 2;
      const cc1 = SW - 1 - (c * 2 + 1);
      const v = srcGray[rr0 + cc0] + srcGray[rr0 + cc1] + srcGray[rr1 + cc0] + srcGray[rr1 + cc1];
      out[r * IMG_W + c] = v >> 2;
    }
  }
  return out;
}

/* ==================== 主流水线 (对应 camera_process_run) ==================== */

/**
 * 跑完整视觉流水线一帧。忠实移植 camera_process_run (M3 前不含拐点/路口/偏置)。
 * @param {object} s        createVisionState() 返回的状态 (持有跨帧状态)
 * @param {Uint8Array} srcGray  原图灰度 188×120 (行主序)
 * @param {object} params   defaultCameraParams()
 * @param {number} gyroZ    当前陀螺仪角速度 (M1 未用, M3 偏置退出用)
 * @returns 控制所需结果 + debug(=s, 供 UI 画 bin/中线/边界)
 */
export function runVision(s, srcGray, params, sensors) {
  sensors = sensors || {};   // {gyroZ, yawAccum, encoderDistDelta}; 兼容旧调用传数字/0
  s.current_gyro_y = sensors.gyroZ || 0;
  if (sensors.yawAccum !== undefined) s.yaw_accum = sensors.yawAccum;   // 运行累积偏航 (rad)
  s.encoder_dist_delta = sensors.encoderDistDelta || 0;                 // 本帧里程增量

  downsample2x2(srcGray, s.gray);     // 阶段0
  binarizeRun(s.bin, s.gray, params); // 阶段1
  lineExtractRun(s, params);          // 阶段2
  cornerDetectRun(s, params);         // 阶段3: 拐点/路口/偏置状态机
  updateDualPathOutputs(s, params);
  errorFusionRun(s, params);          // 阶段4

  return {
    error: s.current_error,
    lateralError: s.lateralError,
    headingError: s.headingError,
    nearValid: s.nearValid,
    farValid: s.farValid,
    windowConflict: s.windowConflict,
    errNear: s.lateralError,
    errFar: s.errFar,
    curvature: s.headingError,
    ffW: s.ffW,
    trackStraight: s.trackStraight,
    dpSel: s.dpSel,
    recoveryActive: Boolean(s.recoveryActive),
    juncType: s.corner_junc_type,
    targetBaseV: s.target_base_v,
    cornerState: s.bias_active ? (s.bias_dir === 0 ? 2 : 1) : 0,   // 0循迹 1转弯偏置 2直行偏置
    cornerDir: s.corner_dir,
    biasActive: s.bias_active,
    biasDir: s.bias_dir,
    opAmpActive: Boolean(s.opamp_active),
    opAmpStage: s.opamp_stage,
    isJunction: s.corner_is_junction,
    weightedAvgCx: s.weighted_avg_cx,
    validRows: s.valid_rows_count,
    debug: s,
  };
}
