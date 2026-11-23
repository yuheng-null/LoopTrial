# PowerShell quick start

[简体中文](quickstart.zh-CN.md) · **English**

From a shell with the installed console scripts on PATH:

```powershell
looptrial devices
looptrial describe sim://thermal
$r = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial review $r.id
looptrial wave $r.id --count 4
looptrial-client
```

For a second response at the same initial temperature:

```powershell
$old = (looptrial read sim://thermal | ConvertFrom-Json).verified
looptrial apply sim://thermal kp=0.025
$b = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial compare $r.id $b.id
looptrial apply sim://thermal "kp=$($old.kp)"
```

Run `looptrial mcp-config` in the experiment shell for a ready-to-paste client entry. The [manual configuration template](mcp-config.json) shows which two absolute paths to replace. Copy a run folder and pass its path to `looptrial review` for offline review.
