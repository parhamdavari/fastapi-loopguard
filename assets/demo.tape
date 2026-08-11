# VHS tape for assets/demo.gif — reproduce with:
#   brew install vhs
#   pip install -e ".[stress]"   (needs uvicorn; run from the repo root)
#   vhs assets/demo.tape
#
# Story: pain -> catch -> install.
#   1. baseline: the async app answers in ~0.1s
#   2. one request runs blocking code -> EVERY request freezes with it
#      (the hang is real: /api/items stalls ~2s on screen, then the
#      blocking request comes back 503)
#   3. the LoopGuard console banner explains the fix + install CTA

Output assets/demo.gif

Set Shell bash
Set FontSize 14
Set Width 800
Set Height 540
Set Padding 12
Set TypingSpeed 20ms
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set BorderRadius 8

Hide
Type "source .venv/bin/activate && python examples/demo_app.py >/tmp/loopguard-demo.log 2>&1 & sleep 2; TIMEFORMAT='  took %Rs'; clear"
Enter
Sleep 2.5s
Show

Type "# a healthy async app"
Enter
Type "time curl -s localhost:8765/api/items"
Enter
Sleep 2s

Ctrl+L
Type "# one request runs blocking code - every request freezes with it"
Enter
Type "(curl -so /dev/null -w 'culprit -> %{http_code}\n' localhost:8765/api/users &)"
Enter
Type "time curl -s localhost:8765/api/items"
Enter
Sleep 4.5s

Ctrl+L
Type "# the server console explains what happened"
Enter
Type "grep -B 2 -A 18 'LOOPGUARD' /tmp/loopguard-demo.log"
Enter
Sleep 2.5s
Type "# pip install fastapi-loopguard  ->  app.add_middleware(LoopGuardMiddleware)"
Enter
Sleep 2.5s

Hide
Type "kill %1"
Enter
Sleep 500ms
