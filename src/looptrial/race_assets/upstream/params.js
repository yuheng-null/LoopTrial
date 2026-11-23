// 参数默认值 — 移植自固件。
// 【原则】增益等数值以固件 .c 源码的实际初始化为准，不以头文件注释或过往文档代替。

// 视觉参数 (CameraParams) — 全部取自 menu.c g_cam_params 实际初始化 (权威, 2026-07-02 核对)
// ⚠️ 纠正过时: minWhite 真值 65 (camera_process.h 注释写 150 已过时); bjtChoice 默认 -1(左转)。
export function defaultCameraParams() {
  return {
    brightFloor: 75,
    // 路口偏置方向选择: -1左 / 0居中(或直行) / 1右
    crossChoice: 0,
    leftTChoice: 0,
    rightTChoice: 0,
    bjtChoice: -1,           // 丁字路口默认左转
    // 队列模式
    useQueueMode: 0,
    queueLength: 0,
    queueJuncType: new Array(20).fill(0),
    queueAction: new Array(20).fill(0),
    // 拐点检测与偏置
    cornerGap: 2,
    cornerThresh: 5,
    cornerBiasMargin: 3,
    // 仿真拐点偏置选择: 2自动(沿用路口/队列策略) / 0不偏置 / -1左 / 1右。
    cornerBiasChoice: 2,
    // 固件默认 15；页面默认 48（用户调优值），保留原页面"更近时再激活"的可调行为。
    cornerActivateMinY: 15,
    biasYawExitDeg: 60.0,
    // 仿真防重检保护：转弯起始后的该累计偏航范围内不再检测新拐点；0=关闭。
    cornerDetectProtectYawDeg: 70.0,
    straightExitCm: 45.0,       // 直行偏置退出里程 (真车标定 45cm = 坐标 4.5 格)
    straightTimeoutFrames: 60,  // 直行偏置超时兜底 (帧)
    // 超级大号运放独立状态机参数：入口左/右、出口右/左陀螺积分角，
    // 以及入口左右转后和首个普通右转后共用的元素直行里程。
    opampX1Deg: 30.0,
    opampX2Deg: 60.0,
    opampY1Deg: 60.0,
    opampY2Deg: 30.0,
    opampStraightCm: 45.0,
    // 加权平均
    weightPower: 1.0,        // 加权平均幂次 (远处行主导)
    // 拐点检测矩形框
    boxHalfW: 10,
    boxHalfH: 8,
    // 检测框透视缩放：远端/近端相对基准尺寸的比例（仿真可调）
    boxFarScale: 0.60,
    boxNearScale: 1.50,
    // 二值化 (Bradley-Roth 自适应)
    bradleyS: 12,            // 局部窗口大小
    bradleyT: 115,           // 白线灵敏度 (百分比阈值)
    minWhite: 65,            // 绝对亮度底线 (.c 真值; .h 注释 150 已过时)
    // 迷宫法 (本次移植暂不启用)
    farCenterY: 14.5,
    nearCenterY: 54.5,
    nearRows: 10,
    farRows: 10,
    lateralAlpha: 0.7,
    headingAlpha: 0.7,
    ffMaxW: 150.0,
    slopeGyroResetPx: 4.0,
    glideDistCm: 10.0,
    recoverMagnet: 1.0,
    recoverAlignPx: 4.0,
    recoverMaxFrames: 20,
    recoverCarryDeg: 0.0,
    useMaze: 0,
  };
}

// 控制参数 — 全部取自 motor_control.c 源码 (权威, 2026-07-02 逐行核对完毕)
// 当前仿真速度环采用加速度前馈；参考速度先经加速度限制，再以 Ka·a_ref 叠加到 PI。
const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));
const finiteOr = (value, fallback) => Number.isFinite(value) ? value : fallback;
const clampFinite = (value, fallback, lo, hi) => clamp(finiteOr(value, fallback), lo, hi);
const clampInt = (value, fallback, lo, hi) => Math.trunc(clampFinite(value, fallback, lo, hi));

// 范围来自 menu.c 的菜单项及 Flash 加载钳位。
export function sanitizeDualPathParams(p = {}) {
  return {
    ...p,
    farCenterY: clampFinite(p.farCenterY, 14.5, 10, 59),
    nearCenterY: clampFinite(p.nearCenterY, 54.5, 10, 59),
    nearRows: clampInt(p.nearRows, 10, 3, 30),
    farRows: clampInt(p.farRows, 10, 3, 30),
    lateralAlpha: clampFinite(p.lateralAlpha, 0.7, 0, 1),
    headingAlpha: clampFinite(p.headingAlpha, 0.7, 0, 1),
    // 元素注入前馈允许反向，用负值可反转拐点/路口对外环的角速度注入方向。
    ffMaxW: clampFinite(p.ffMaxW, 150, -900, 900),
    slopeGyroResetPx: clampFinite(p.slopeGyroResetPx, 4, 0.5, 20),
    glideDistCm: clampFinite(p.glideDistCm, 10, 1, 50),
    recoverMagnet: clampFinite(p.recoverMagnet, 1, 0.5, 5),
    recoverAlignPx: clampFinite(p.recoverAlignPx, 4, 1, 20),
    recoverMaxFrames: clampInt(p.recoverMaxFrames, 20, 5, 60),
    recoverCarryDeg: clampFinite(p.recoverCarryDeg, 0, 0, 30),
    biasYawExitDeg: clampFinite(p.biasYawExitDeg, 60, 10, 120),
    cornerDetectProtectYawDeg: clampFinite(p.cornerDetectProtectYawDeg, 70, 0, 180),
    cornerBiasChoice: [-1, 0, 1, 2].includes(Math.trunc(finiteOr(p.cornerBiasChoice, 2)))
      ? Math.trunc(finiteOr(p.cornerBiasChoice, 2)) : 2,
    cornerActivateMinY: clampFinite(p.cornerActivateMinY, 15, 10, 50),
    boxFarScale: clampFinite(p.boxFarScale, 0.60, 0.2, 1.0),
    boxNearScale: clampFinite(p.boxNearScale, 1.50, 1.0, 2.0),
    straightExitCm: clampFinite(p.straightExitCm, 45, 5, 120),
    straightTimeoutFrames: clampInt(p.straightTimeoutFrames, 60, 10, 200),
    opampX1Deg: clampFinite(p.opampX1Deg, 30, 0, 180),
    opampX2Deg: clampFinite(p.opampX2Deg, 60, 0, 180),
    opampY1Deg: clampFinite(p.opampY1Deg, 60, 0, 180),
    opampY2Deg: clampFinite(p.opampY2Deg, 30, 0, 180),
    opampStraightCm: clampFinite(p.opampStraightCm, 45, 5, 200),
  };
}

export function defaultControlParams() {
  return {
    controlPeriodMs: 10,
    maxDeltaWPerMs: 10.0,
    // 角速度目标参考加速度限幅；外环与角速度测试目标都先经过此斜坡。
    // 外环只保留近端回线、远端预瞄和视觉侧转弯前馈。
    // KD 使用 px/s 的连续时间量纲；dFilterHz 为一阶微分低通的截止频率。
    steer: { kp: 0.3, kp2: 0.0, kd: 0.0, dFilterHz: 10.0 },
    // 角速度中环 位置式 PI       Omega_PID_Init(..., 3.0, 0.0, ±OMEGA_V_DIFF_MAX)  输出=速度差(编码器单位)
    omega: { kp: 3.0, ki: 0.0 },
    // 速度环增量式 PI：当前参考左 0.65/0.025，右 0.75/0.025。
    motorL: { kp: 0.65, ki: 0.025 },
    motorR: { kp: 0.75, ki: 0.025 },

    // DiffParams 实际初始化 (motor_control.c L14-32; 与本次移植无关的地图/曲率项略)
    diff: {
      base_speed: 0,         // 当前 C 静态初始化值；运行时由 VOFA/面板显式设定
      kw_ff: 1.71,           // 角速度→速度差前馈: v_diff = target_w × kw_ff
      diff_reduce_max: 0.80, // 内轮减速上限 (×target_v); 调大>1 内轮反转过直角弯
      deadzone_l: 0,         // 当前 C 静态初始化值；与 plant 物理起转阈值分离
      deadzone_r: 0,
      speed_calib: 27.5,     // 编码器/占空比% (显示/地图用, 串级未用)
      // 仿真扩展：速度命令先限为 ±ref_accel_limit，再使用左右独立 Ka·a_ref。
      ref_accel_limit: 2000, // enc/s²，控制周期 10ms 时每拍最多变化 20 enc
      acc_ff_l: 0.40,        // 左轮加速度前馈 Ka（PWM / (enc/s²)）
      acc_ff_r: 0.40,        // 右轮加速度前馈 Ka（PWM / (enc/s²)）
    },

    MAX_PWM_DUTY: 7000.0,    // motor_control.h
  };
}

// 控制环编译期常量 (motor_control.c L51-76, 权威)
export const CTRL = Object.freeze({
  OMEGA_DT: 0.01,               // 角速度环 dt = 10ms (100Hz, 全串级在10ms)
  OMEGA_V_DIFF_MAX: 300.0,      // 角速度PI输出限幅 (速度差, 编码器单位)
  KP2_ERR_THRESHOLD: 15.0,      // 非线性P²启用阈值: |error| 超过才叠加
  D_FILTER_HZ: 10.0,            // 摄像头外环 D 项一阶低通截止频率 (Hz)
  OPENLOOP_DUTY: 4000.0,
  OPENLOOP_R_STOP_TICKS: 200,   // 2s / 10ms
  OMEGA_TEST_W: 100.0,          // 模式3 方波幅值 (°/s)
  OMEGA_TEST_HALF_TICKS: 50,    // 模式3 半周期 (50×10ms=0.5s)
});
