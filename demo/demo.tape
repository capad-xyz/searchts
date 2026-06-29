# searchts hero demo - recorded with vhs
Output demo.gif

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 22
Set Width 1280
Set Height 720
Set Padding 30
Set Margin 60
Set MarginFill "/vhs/bg.png"
Set BorderRadius 16
Set WindowBar Colorful
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

# clean prompt, start fresh
Hide
Type "export PS1='~ $ '"
Enter
Type "clear"
Enter
Show

Sleep 800ms

# 1) read any page as clean Markdown - the unlocker status line shows the tier used
Type "searchts read https://en.wikipedia.org/wiki/Web_scraping 2>&1 | head -12"
Sleep 500ms
Enter
Sleep 4.5s

# 2) search the web with no API key
Type "searchts search 'rust terminal ui library' -n 3"
Sleep 500ms
Enter
Sleep 5.5s

Sleep 2s
