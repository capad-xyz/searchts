# video 2 - a Claude session that installs searchts (MCP + skill) and verifies it on a real link
Output demo2.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1480
Set Height 880
Set Padding 30
Set Margin 60
Set MarginFill "/vhs/bg.png"
Set BorderRadius 16
Set WindowBar Colorful
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "export PS1='~ $ '"
Enter
Type "cp /vhs/claude2.sh /usr/local/bin/claude && chmod +x /usr/local/bin/claude"
Enter
Type "mkdir -p ~/.claude/commands"
Enter
Type "clear"
Enter
Show

Sleep 700ms
Type `claude "add searchts so you can read pages that block normal fetches"`
Sleep 500ms
Enter
Sleep 17s

Sleep 1.5s
