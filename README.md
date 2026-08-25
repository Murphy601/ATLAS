# ATLAS

EGO annotation engine: [`remotasks-lidar-assistant/`](remotasks-lidar-assistant/README.md)

Offline non-AI operator copilot (IX Browser → [Chat Home Base claimed](https://chathomebase.com/chat/claimed)): [`offline-chat-copilot/`](offline-chat-copilot/README.md)

You open **IX Browser** and the task yourself. The engine attaches to that window (no second Chrome). Debug port 9222 is optional.

Chat copilot branch (checkout; do not merge from another branch):

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout -B cursor/offline-chat-copilot-7517 origin/cursor/offline-chat-copilot-7517
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
