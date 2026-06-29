# video 1 - read a Cloudflare-walled page as clean Markdown (rendered to mp4 for zoom pass)
Output demo1.mp4

Require searchts

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1400
Set Height 760
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
Type "clear"
Enter
Show

Sleep 800ms

# a Stack Overflow page that returns 403 + a Cloudflare wall to a normal bot
Type "url=https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-an-unsorted-array"
Sleep 300ms
Enter
Sleep 400ms

# searchts clears it with a real-browser TLS fingerprint and returns clean Markdown
Type "searchts read $url 2>&1 | head -14"
Sleep 500ms
Enter
Sleep 5s

# and search the web with no API key
Type "searchts search 'branch prediction sorted array' -n 3"
Sleep 500ms
Enter
Sleep 5.5s

Sleep 2s
