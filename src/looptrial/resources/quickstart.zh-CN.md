# PowerShell 快速开始

**简体中文** · [English](quickstart.md)

在已安装 LoopTrial 且 PATH 包含其命令的终端中运行以下示例。

```powershell
looptrial devices
looptrial describe sim://thermal
$r = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial review $r.id
looptrial wave $r.id --count 4
looptrial-client
```

保持相同的初始温度，改变增益并采第二段响应，比较后恢复原值。

```powershell
$old = (looptrial read sim://thermal | ConvertFrom-Json).verified
looptrial apply sim://thermal kp=0.025
$b = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial compare $r.id $b.id
looptrial apply sim://thermal "kp=$($old.kp)"
```

在实验终端运行 `looptrial mcp-config` 可生成当前环境的客户端配置。手填时按[配置模板](mcp-config.json)替换 Python 和实验目录这两个绝对路径。复制任一实验目录，将其路径交给 `looptrial review` 即可离线复核。
