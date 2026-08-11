# VHS tape for assets/demo.gif — reproduce with:
#   brew install vhs
#   pip install -e ".[stress]"   (needs uvicorn; run from the repo root)
#   vhs assets/demo.tape
#
# Design: three scenes, one message per screen.
#   1. fast endpoint  -> 200, x-blocking-detected: false
#   2. blocking endpoint -> 503, x-loopguard-enforcement: strict
#   3. the LoopGuard console banner
# curl output is filtered to the status line and x-* headers so each
# scene stays under ~8 lines and is readable at a glance.

Output assets/demo.gif

Set Shell bash
Set FontSize 15
Set Width 800
Set Height 540
Set Padding 16
Set TypingSpeed 20ms
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set BorderRadius 8

Hide
Type "source .venv/bin/activate && python examples/demo_app.py >/tmp/loopguard-demo.log 2>&1 & sleep 2; clear"
Enter
Sleep 2.5s
Show

Type "# fast async endpoint -> passes untouched"
Enter
Type "curl -si localhost:8765/api/items | grep -E 'HTTP/|x-'"
Enter
Sleep 2.2s

Ctrl+L
Type "# this endpoint blocks the event loop -> LoopGuard fails it"
Enter
Type "curl -si localhost:8765/api/users | grep -E 'HTTP/|x-'"
Enter
Sleep 2.8s

Ctrl+L
Type "# the server console explains what happened"
Enter
Type "grep -B 2 -A 18 'LOOPGUARD' /tmp/loopguard-demo.log"
Enter
Sleep 4s

Hide
Type "kill %1"
Enter
Sleep 500ms
