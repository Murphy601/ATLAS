# ATLAS

ESI hierarchical caption labeling (MultiMango): [`esi-caption-labeling/`](esi-caption-labeling/README.md)

You open **IX Browser** or **MoreLogin** and the task yourself. The engine attaches to that window (no second Chrome). Debug port 9222 is optional.

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout -B cursor/esi-caption-labeling-7517 origin/cursor/esi-caption-labeling-7517
powershell -ExecutionPolicy Bypass -File .\run-ix.ps1
# or
powershell -ExecutionPolicy Bypass -File .\run-morelogin.ps1
```
