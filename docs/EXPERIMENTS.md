# 跨领域实验

**简体中文** · [English](EXPERIMENTS.en.md)

以下 PowerShell 命令从已安装的 `looptrial` 开始。每个 `run` 都按设备当前的生效参数启动一次采集，返回实验编号。每个模拟对象运行在主机上，采样时间是模型时间。把一轮试验的 `id` 传给 `review` 可从 CSV 重新计算指标，`wave` 可按索引取一小段带时间戳的样本。运行记录目录中的 `plot.svg` 可以用浏览器打开。

从新建的记录库开始，可以复现实验的默认配置。正常使用时沿用同一个 `LOOPTRIAL_HOME`，即可在不同 CLI 或 MCP 会话间查到已有记录和模拟设备当前配置。

```powershell
$env:LOOPTRIAL_HOME = Join-Path $PWD ("trials-" + [guid]::NewGuid())
looptrial devices
looptrial describe sim://thermal
looptrial read sim://thermal
```

## 温控器升温慢

先确定用户平时工作的温度。以 50 °C 为例，20 °C 起始、180 秒观察窗口中，`rise_s` 是首次实测达到 48.5 °C 的时间，即从 20 到 50 °C 这一变化的 95%。把升温时间作为目标，上冲、末段误差及是否真正到达作为约束，就能避免只追求第一个穿越点。以下限值演示一个实验选择，使用者可根据自己的基线、热工艺容差和允许的试验预算设定。

```powershell
$t0 = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial apply sim://thermal kp=0.05 ki=0.0016
$t1 = looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint reached:ge:1 --constraint overshoot_c:le:1 --constraint steady_error_c:le:0.25 | ConvertFrom-Json
looptrial compare $t0.id $t1.id
looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint reached:ge:1 --constraint overshoot_c:le:1 --constraint steady_error_c:le:0.25
looptrial review $t1.id
```

默认温度下，基线升温时间为 60 s，这组参数约为 37.5 s。每段数据都从相同环境温度和空的延迟队列开始。模型的热时间常数为 35 s，满功率平衡温升为 85 °C，`delay_s` 决定占空比变化到送入热对象的延迟。控制器使用带积分限幅逻辑的 PI。调整用户工况时，同时查看真实记录条件 `target_c` 与每一行的目标列。若 `reached=0`，返回的 `rise_s` 仅是观测截止时间。

长实验可以让调用方先离开。以下示例在采集前保留 5 秒现实时间用于查询和取消。退出当前终端后，可在同一记录库下按编号继续查询。

```powershell
$job = looptrial run sim://thermal step --background --pace 5 | ConvertFrom-Json
looptrial status $job.id
Start-Sleep 6
looptrial status $job.id
```

## 传感器抖动与滤波延迟

50 Hz 压力源在 3 s 从 10 kPa 阶跃到 20 kPa。同一 `seed` 和 `noise_std` 产生完全相同的原始输入。在 1 到 3 s 的静止窗口计算滤后总体标准差，用变化后首次连续三个读数达到观测阶跃幅度 90% 的起点计算延迟。两个指标共用一条波形。只需诊断时可在第一条采集后直接查看原始和过滤列。

压力模型 1.1 在正式采样前用独立的种子噪声让滤波器预运行 5 s，便于在 1–3 s 的窗口评价滤后波动。90% 阈值由阶跃前后的已标定输入估计。慢滤波器在短窗口内尚未稳定时也使用同一判据。旧模型 1.0 的记录复核仍使用原有的滤后末段阈值。

```powershell
$s0 = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial wave $s0.id --start 148 --count 8
looptrial apply sim://sensor alpha=0.25
$s1 = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial compare $s0.id $s1.id
looptrial run sim://sensor capture --condition seed=18 --goal noise_std:le:0.5 --constraint delay_s:le:0.30 --constraint reached:ge:1
```

在这段固定输入上，把当前样本权重从 1 降到 0.25，静止噪声约从 0.930 降到 0.355 kPa，延迟从 0 增至 0.14 s。换种子检验新噪声实现，更高的 `noise_std` 可用于检验原有参数能否维持要求。静止样本的标准差只能衡量重复性。实体测量需要稳定基准、时间对齐的参考阶跃以及相同的采样率和输入条件来解释延迟。

## 两点标定及第三点验证

同一个压力设备可以在三个已知标准量上各采 50 个读数。用低、高参考拟合 `reference = fit_scale × raw + fit_offset`，在独立第三点核对残差。这里的 `raw` 是传感器以标称比例换算出的 kPa，`filtered` 表示滤后读数。标定用 `raw` 的平均值。实际 ADC 可以把输入单位换为 count，相应的系数单位改为 kPa/count。

```powershell
$c = looptrial run sim://sensor calibrate --condition ref_low=5 --condition ref_high=35 --condition ref_check=19 | ConvertFrom-Json
$c.metrics
looptrial apply sim://sensor "scale=$($c.metrics.fit_scale)" "offset=$($c.metrics.fit_offset)"
$check = looptrial run sim://sensor calibrate --condition seed=18 --condition ref_check=19 | ConvertFrom-Json
$check.metrics
looptrial review $check.id
```

`raw_residual` 给出第三点在原始比例下的偏差。`fitted_residual` 用本轮拟合的两系数计算第三点偏差。`applied_residual` 用设备实际生效的系数计算。第一次试验默认系数为 1 和 0，所以后者等于原始偏差。写入并换种子重测后，`applied_residual` 才是使用上一次系数的独立测量。记录中的三个参考、全部样本和实际系数可用来独立验算。两点只支持仿射修正。真实校准若缺少可溯源的独立标准，应保留原配置并报告缺失条件。

## 电机跟踪与输出饱和

轮速模型从静止开始，控制器每 20 ms 更新占空比。负载用等效满量程驱动比例表示，电机时间常数为 0.42 s。默认目标 90 rpm 下，基线能到达 95% 目标，时间约 5.14 s。范围内的一组候选 `kp=0.012, ki=0.022` 约为 1.14 s。

```powershell
$m0 = looptrial run sim://motor step | ConvertFrom-Json
looptrial apply sim://motor kp=0.012 ki=0.022
$m1 = looptrial run sim://motor step --goal rise_s:le:2 --constraint reached:ge:1 --constraint overshoot_rpm:le:2 | ConvertFrom-Json
looptrial compare $m0.id $m1.id
looptrial run sim://motor step --goal rise_s:le:2 --constraint reached:ge:1 --constraint overshoot_rpm:le:2
$cap = looptrial run sim://motor step --condition target_rpm=180 --condition drive_limit=0.6 --goal reached:ge:1 | ConvertFrom-Json
$cap.metrics
looptrial wave $cap.id --start 391 --count 10
```

最后一轮把驱动限制为 60%，仍有 8% 的对抗负载。模型满驱动空载轮速 180 rpm，稳态上限为 `180 × (0.60 − 0.08) = 93.6 rpm`。检查观测到的末段转速、速度斜率、占空比和连续饱和区间。末段输出保持上限且速度几乎不再变化，支持在该工况下停止增益搜索。请用记录中实际出现的区间核对这个判断。瞬时限幅与整段输出受限有不同含义。

## 直立扰动与车轮漂移

```powershell
$b = looptrial run sim://balance disturb --condition kick_deg=3 --goal recovery_s:le:2 --constraint recovered:ge:1 --constraint small_angle_valid:ge:1 --constraint max_drift_m:le:0.12 --constraint peak_output:le:4 | ConvertFrom-Json
$b.metrics
looptrial review $b.id
```

小角度倒立摆与水平车轴的模型在设备模拟器内每 10 ms 执行全状态反馈。0.5 s 时施加 3° 倾角，前五十个样本可检验原先静止直立。对于杆长 0.25 m，模型满足 `角加速度 = (9.81 × 倾角 − 车轴加速度) / 0.25`，倾角以 rad 代入。默认参数下，扰动后约 1.60 s 回到 ±0.2° 并保持，车轴最大漂移约 0.092 m，峰值加速度约 1.02 m/s²。比较候选时把漂移和输出都纳入硬约束。若越出 ±12° 的线性适用范围，`small_angle_valid=0`，应结束该模型上的性能判断。

## 接入已有压力记录器

随安装包提供的 `resources/pressure_adapter` 是独立的扩展示例。它把 50 Hz 老记录器的 `timestamp_ms,adc_count` CSV 映射为只读压力设备，并增加一个压力波动实验。将原始计数和相对秒、标称 kPa 一起存入记录，即可复核尺度与采样间隔。新后端通过 Python 包入口 `looptrial.devices` 注册，CLI、MCP 服务和记录格式共用原实现。

在已激活的 Python 环境中执行以下命令。示例自带八条合成的旧格式输入，足以验证接入。构建这个可选扩展需要 setuptools 77 或更高版本，pip 默认在单独的构建环境获取它。

```powershell
$location = looptrial resources | ConvertFrom-Json
$adapter = Join-Path $location.examples pressure_adapter
Copy-Item -Recurse $adapter ./pressure_adapter
python -m pip install ./pressure_adapter
looptrial devices
looptrial describe pressure://fixture
$r = looptrial run pressure://fixture ripple --constraint peak_to_peak_kpa:le:0.5 | ConvertFrom-Json
looptrial review $r.id
```

这段旧记录的原始最小值为 499 count、最大值为 507 count。模板的标称换算为 `(count − 50) × 0.05 kPa`，故波动峰峰值为 0.4 kPa。可将 `LOOPTRIAL_PRESSURE_LOG` 设为同格式文件的绝对路径，以文件 SHA-256 作为输入标识。以下命令要求记录至少有八条连续的 20 ms 样本。适配器核对输入摘要、采样周期、12 位 ADC 范围和窗口完整性。离线 `review` 仅使用存下来的样本及已安装的指标实现。

```powershell
$env:LOOPTRIAL_PRESSURE_LOG = (Resolve-Path ./export.csv).Path
$digest = (Get-FileHash $env:LOOPTRIAL_PRESSURE_LOG -Algorithm SHA256).Hash.ToLowerInvariant()
looptrial run "pressure://$digest" ripple --condition samples=8
```

新增已有协议时，从 `legacy_pressure.py` 的三个函数入手。用 `describe` 声明身份、版本、单位、允许的动作和边界，用 `acquire` 把有限窗口变成带设备时间戳的原始样本，用纯函数 `metrics` 离线评价。只读设备填写空的 `parameters`。需要写入真实设备时，实现 `read(uri)` 和 `apply(uri, values)`，让 `read` 取得目标当前的生效值。调整换算关系或指标定义时同步更新适配器版本。示例复用已有采样结果，无法预测新控制参数下的装置响应。
