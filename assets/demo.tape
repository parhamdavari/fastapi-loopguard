# VHS tape for assets/demo.gif — reproduce with:
#   brew install vhs
#   pip install -e ".[stress]"   (needs uvicorn; run from the repo root)
#   vhs assets/demo.tape

Output assets/demo.gif

Set Shell bash
Set FontSize 13
Set Width 800
Set Height 660
Set Padding 16
Set TypingSpeed 20ms
Set Theme "Catppuccin Mocha"

Hide
Type "source .venv/bin/activate; clear"
Enter
Sleep 500ms
Show

Type "python examples/demo_app.py 2>/tmp/loopguard-demo.log &"
Enter
Sleep 2s

Type "curl -i localhost:8765/api/items"
Enter
Sleep 2s

Type "curl -i localhost:8765/api/users"
Enter
Sleep 2.5s

Type "tail -n 25 /tmp/loopguard-demo.log"
Enter
Sleep 3.5s

Hide
Type "kill %1"
Enter
Sleep 500ms
