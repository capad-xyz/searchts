# video 2 - an agent hits a bot wall, installs searchts on demand, retries, succeeds
Output demo2.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1400
Set Height 840
Set Padding 30
Set Margin 60
Set MarginFill "/vhs/bg.png"
Set BorderRadius 16
Set WindowBar Colorful
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

Hide
Type "export PS1='~ $ '"
Enter
Type "cp /vhs/claude.sh /usr/local/bin/claude && chmod +x /usr/local/bin/claude"
Enter
Type "mkdir -p ~/.claude/commands"
Enter
Type "clear"
Enter
Show

Sleep 700ms
Type `claude "search Stack Overflow for why a sorted array is faster, and give me the answer"`
Sleep 500ms
Enter
Sleep 19s

Sleep 1.5s
