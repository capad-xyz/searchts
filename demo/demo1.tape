# video 1 (hero) - a Claude session: blocked by a bot wall, routes through searchts, answers
Output demo1.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrainsMono Nerd Font Mono"
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
Type "cp /vhs/claude1.sh /usr/local/bin/claude && chmod +x /usr/local/bin/claude"
Enter
Type "clear"
Enter
Show

Sleep 700ms
Type `claude "why is processing a sorted array faster than an unsorted one?"`
Sleep 500ms
Enter
Sleep 18s

Sleep 1.5s
