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

[MCP 配置模板](mcp-config.json)中的命令可按需替换为 `looptrial-mcp` 可执行文件的绝对路径。在两个客户端设置相同的 `LOOPTRIAL_HOME` 绝对路径即可共用记录。每个实验目录都可以单独复制并将目录路径交给 `looptrial review`。
