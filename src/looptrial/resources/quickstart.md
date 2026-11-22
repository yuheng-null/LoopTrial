# PowerShell quick start

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

MCP host configuration template: mcp-config.json. Replace the command with the installed looptrial-mcp executable's full path when necessary. Set the same absolute LOOPTRIAL_HOME in both clients to share the catalog. Each run folder is portable by itself. Copy it and pass its path to looptrial review.
