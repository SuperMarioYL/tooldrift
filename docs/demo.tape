# ToolDrift demo — vhs script (https://github.com/charmbracelet/vhs)
# Renders the 30s happy path: snapshot one provider, then `run` catching a
# DeepSeek -> Qwen tool-call contract drift with a red, non-zero exit.
#
#   vhs docs/demo.tape -o assets/demo.gif

Output assets/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1200
Set Height 720
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "export PS1='$ '"  Enter
Type "clear"            Enter
Show

# 1. Snapshot DeepSeek's tool-call contract — no API key, replay an offline fixture.
Type "tooldrift snapshot --base deepseek --from-fixtures"
Sleep 600ms
Enter
Sleep 3s

# 2. Run the regression: probe old vs new, diff the contracts, red-light on drift.
Type "tooldrift run --old deepseek --new qwen --from-fixtures"
Sleep 600ms
Enter
Sleep 3500ms

# 3. The drift exit code is what CI keys on.
Type 'echo CI exit code: $?'
Sleep 400ms
Enter
Sleep 2500ms
