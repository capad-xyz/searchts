# video 2 - agents get blocked; searchts gets through; one-line install
Output demo2.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1400
Set Height 800
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
Type "export url=https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-an-unsorted-array"
Enter
Type "mkdir -p ~/.claude/commands"
Enter
Type "clear"
Enter
Show

Sleep 800ms

# 1) an AI agent fetches the page the normal way
Type "# an AI agent fetches a page the normal way:"
Sleep 200ms
Enter
Type `python3 -c "import requests,os; print('HTTP', requests.get(os.environ['url']).status_code)"`
Sleep 500ms
Enter
Sleep 2.5s
Type "# 403 - blocked by a Cloudflare bot wall."
Sleep 200ms
Enter
Sleep 1.6s

# 2) searchts clears it and returns clean Markdown
Type "searchts read $url 2>&1 | head -8"
Sleep 500ms
Enter
Sleep 4.5s

# 3) drop it into any agent - as an MCP server...
Type "searchts mcp install"
Sleep 500ms
Enter
Sleep 3.8s

# ...or as a Claude Code slash command
Type "searchts skill install"
Sleep 500ms
Enter
Sleep 3s

Sleep 1.5s
