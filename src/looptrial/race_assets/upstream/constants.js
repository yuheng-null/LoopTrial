// 编译期常量 — 对照固件 algo_state.h 与 camera_process.h 的定义移植
// 算法工作在原图 2x 下采样后的小图上 (94×60)。原始摄像头 188×120 (MT9V03X)。

export const MT9V03X_W = 188;
export const MT9V03X_H = 120;

export const IMG_W = MT9V03X_W / 2; // 94
export const IMG_H = MT9V03X_H / 2; // 60
export const SMALL_W = IMG_W / 2;   // 47 (二值化/迷宫法用到的更小图)
export const SMALL_H = IMG_H / 2;   // 30

export const IMG_PROC_START = 10;                  // 远端不可靠 + 顶部裁剪 (原20, 缩放后向上取整)
export const IMG_PROC_H = IMG_H - IMG_PROC_START;  // 有效处理行数: 50
export const TRACK_MIN_WIDTH = 2;                  // 赛道最小宽度阈值 (原4, 等比缩放)
export const IMG_CROP_LEFT = 3;                    // 左侧裁剪列数 (原6列/2)
export const IMG_CROP_RIGHT = 3;                   // 右侧裁剪列数 (原6列/2)
export const HOLLOW_SEARCH_HALF = 30;              // 空心框/斑马线搜索半径 (原60)
export const STARTUP_VALID_CNT = 2;                // 起步阶段连续白点验证数 (原4)

// 边界钳位 (对应 C 宏 CLAMP_X / CLAMP_Y)
export const CLAMP_X = (v) => (v < 0 ? 0 : (v >= IMG_W ? IMG_W - 1 : v));
export const CLAMP_Y = (v) => (v < 0 ? 0 : (v >= IMG_H ? IMG_H - 1 : v));

// 拐点方向 (CornerDir)
export const CORNER_NONE = 0;
export const CORNER_LEFT = -1;
export const CORNER_RIGHT = 1;

// 拐点/路口/偏置常量 (camera_process.c corner_detect_run 的 #define, 权威)
export const CORNER = Object.freeze({
  WIDTH_JUMP_MIN: 18,          // 突跳后最小宽度
  WIDTH_JUMP_RATIO: 1.8,       // 宽度突跳比例阈值
  BIAS_YAW_EXIT_DEG: 60.0,     // 转弯偏置退出角度默认值 (运行时由参数 biasYawExitDeg 覆盖; MOS 转弯与此统一)
  BOX_EDGE_BAND: 2,            // 矩形框边带行/列数
  BOX_TOP_THRESH: 2,           // 上边白点阈值
  BOX_BOT_THRESH: 2,           // 下边白点阈值
  BOX_SIDE_THRESH: 2,          // 左/右边白点阈值
  BOX_OUTER_OFFSET: 10,        // 外侧贯穿验证偏移
  BOX_OUTER_THRESH: 3,         // 外侧贯穿阈值
  CORNER_ACTIVATE_MIN_Y: 15,   // 拐点行 <15 (太远) 不激活偏置
});

// 路口类型 (JuncType) — camera_process.h
export const JuncType = Object.freeze({
  NONE:    0,
  T_END:   1, // 丁字路口
  T_LEFT:  2, // 左T字路口
  T_RIGHT: 3, // 右T字路口
  CROSS:   4, // 十字路口
  L_LEFT:  5, // 左直角弯
  L_RIGHT: 6, // 右直角弯
  MOS:     7, // MOS (仅队列模式检测)
  OPAMP:   8, // 超级大号运放（队列专用，入口由丁字触发）
});

// 超级大号运放独立状态机。入口左右转后及首个普通右转后均执行元素直行 m；
// 等待态恢复普通循迹，其余动作态复用元素偏置补线。
export const OpAmpStage = Object.freeze({
  IDLE: 0,
  ENTRY_LEFT: 1,
  ENTRY_RIGHT: 2,
  WAIT_RIGHT_1: 3,
  RIGHT_1: 4,
  STRAIGHT_M: 5,
  WAIT_RIGHT_2: 6,
  RIGHT_2: 7,
  WAIT_RIGHT_3: 8,
  FINAL_RIGHT: 9,
  FINAL_LEFT: 10,
  ENTRY_STRAIGHT_M: 11,
});
