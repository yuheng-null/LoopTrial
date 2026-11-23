# 用雷霆之车复现实验

**简体中文** · [English](RACE.en.md)

`race://yali` 把雷霆之车的视觉、三环控制和差速车辆模型接入 LoopTrial。摄像头根据车在自绘赛道上的实际位姿渲染，每轮从静止起跑。上游代码固定在 [a7237f9](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d)。两条路线都是公开实验用椭圆跑道，不代表某届比赛的官方路线。

## 第一次试跑

安装主机 wheel，电脑需装 Edge 或 Chromium 系浏览器并支持 WebGL。Windows 在常见安装位置自动找到浏览器。其他位置可将 `LOOPTRIAL_BROWSER` 设为可执行文件的完整路径。页面、相机渲染器和全部算法在包内。试跑使用临时本机 HTTP 服务和独立的无界面浏览器进程；安装后运行无需联网。离线复核 CSV 无需浏览器。

```powershell
looptrial describe race://yali
$saved = (looptrial read race://yali | ConvertFrom-Json).verified
$b = looptrial run race://yali lap --condition course=1 --constraint valid_lap:ge:1 | ConvertFrom-Json
looptrial apply race://yali drive_speed=320
$c = looptrial run race://yali lap --condition course=1 --constraint valid_lap:ge:1 | ConvertFrom-Json
looptrial compare $b.id $c.id
looptrial review $c.id
looptrial apply race://yali "drive_speed=$($saved.drive_speed)"
```

在新的数据目录中，默认轮速请求为 250 个模型编码器单位每秒，`steer_gain` 为 10.85 °/s/px。每轮从同一位置清零车速和控制器，程序根据 `seed` 初始化陀螺仪噪声。可换种子独立复测，或改用 `--condition course=2` 运行较紧的弯道。`--background` 配合 `status`、`cancel` 可在另一进程查询或停止试跑。取消后原始记录保留主机已收到的样本前缀。

## 如何判定有效完赛

- 两条路线都是两段直线加两个半圆。每段直线长 1.30 m，宽弯半径 0.85 m（`course=1`），紧弯半径 0.62 m（`course=2`）。线路标宽 6.5 cm。车辆从左侧直道中点朝负 Z 方向起步。默认合法走廊为车体中心距线中心不超过 5.5 cm。`lane_half_width_m` 表示整个试跑期间的这一限制。
- 八个有限宽度的检查门沿路线等距设置，第八门是起终点。对相邻采样点的轨迹线段和有方向的门做相交判断；重置位姿落在起点门上，不计为完赛。`valid_lap=1` 要求一直在走廊内、正向依次过八门并在期限内到达。切弯抄近路同样受走廊约束。
- `samples.csv` 每 10 ms 记录一次时间、位置（米）、航向、速度、视觉误差、有效扫描行数、PWM、横向偏离、已过门数和事件。`event` 为 0 行进、1 过门、2 完赛、3 越界（含切弯）、4 漏门/错序、5 超时、6 逆向过门。`review` 用轨迹重新求交、检查位姿与速度航向的一致性，并重新计算判定。
- `lap_time_s` 是终止时刻；仅对有效完赛可当作圈时。`bend_time_s` 是车体中心位于两端半圆区域的累计模型时间，`max_offset_m` 可检查提速后的循线余量。给圈时或弯道用时设门槛时，系统自动将有效完赛加入该指标的判断。停在第一弯的较短时间不能用来证明变快。

## 首次整车接入的改动和成本

| 在旧工程中找什么 | 本例的映射 |
| --- | --- |
| 车辆动作与信号来源 | 原页面 `processVisionAndControl_M2` 和 `createCircuitTrack` 把图像赛道纹理放到水平面上。188×120、水平视场 120° 的相机通过 WebGL 读像素，原版 `runVision` 从像素提取误差。上游 `createController(...).update10ms` 输出两轮 PWM，`createPlant(...).step` 计算实际车速、陀螺和位姿增量。 |
| 可写参数及单位 | `drive_speed` 映射到 `params.diff.base_speed`。`steer_gain` 映射到 `steer.kp`。前者为模型编码器速度，换算真实转速需实车标定。每轮将已回读的主机仿真参数装入新控制器。 |
| 新增的包装和裁判 | `race_assets/lap.js` 按原页面的相机、控制周期、延迟队列和位姿更新连接七个原封不动的上游模块；自绘赛道使用原图像平面的缩放方式。`race.py` 声明能力、启动浏览器并从轨迹独立评分。CLI 和 MCP 共用此后端。裁判的坐标及检查点不作为控制器输入。 |
| 所需工作 | 本机此前用上游的独立速度环测过插件接口。这次整车接入从创建独立检出到取得第一条可复核的完整轨迹，用工作站时间约 3 分 38 秒，含首次试跑。原型轨迹为 858 点。此数字不含先前调研，也不含随后对赛道、裁判、进程清理、测试、许可证和发布包的工作。上游工作树无需改动。 |

仿真时相机每 20 ms 采图，控制器每 10 ms 更新，电机每 1 ms 积分。保留 30 ms 视觉反馈延迟和 10 ms 编码器延迟。主机每 25 个控制周期收一批轨迹，批次到达速度取决于浏览器与电脑。此处的试跑时间、改进和车辆动力学均为模型结果。上车前还需要实际编码器尺度、轮胎抓地、负载、相机安装与延迟标定，以及能识别有效完赛的现场测量。

七个上游算法文件与 Three.js r128 分别保留 MIT 声明。浏览器从 wheel 内载入渲染器，不加载上游赛事图片、标志和预置地图。[上游核心](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d/core) · [Three.js r128 源码](https://github.com/mrdoob/three.js/tree/r128) · [第三方声明](../THIRD_PARTY.zh-CN.md)
