# video 2 - add searchts to any agent: MCP server or Claude Code skill
Output demo2.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1400
Set Height 880
Set Padding 30
Set Margin 60
Set MarginFill "/vhs/bg.png"
Set BorderRadius 16
Set WindowBar Colorful
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

Hide
Type "export PS1='~ $ '"
Enter
Type "mkdir -p ~/.claude/commands"
Enter
Type "clear"
Enter
Show

Sleep 700ms
Type "# 1. add searchts to any agent as an MCP server"
Sleep 200ms
Enter
Type "searchts mcp install"
Sleep 400ms
Enter
Sleep 4.5s

Type "# 2. or as a Claude Code slash command"
Sleep 200ms
Enter
Type "searchts skill install"
Sleep 400ms
Enter
Sleep 3.5s

Sleep 1.5s
