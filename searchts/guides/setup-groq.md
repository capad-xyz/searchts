# Groq Whisper setup guide

## What it does
When a YouTube video has no subtitles, use Groq's Whisper API for speech-to-text. Groq offers a free tier.

## Steps the agent can do automatically

1. Check whether it is already configured:
```bash
searchts doctor | grep -i "groq\|whisper"
```

2. If the user provides a key, write it to the config:
```python
from searchts.config import Config
c = Config()
c.set("groq_api_key", "the key the user provided")
```

3. Test (optional):
```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer the key the user provided" \
  -o /dev/null -w "%{http_code}"
```
A 200 response means it works.

## Steps the user must do manually

Tell the user:

> Speech-to-text for video needs a Groq API key (free).
>
> Steps:
> 1. Open https://console.groq.com
> 2. Sign up with a Google account or email
> 3. Click "API Keys" on the left
> 4. Click "Create API Key"
> 5. Copy the generated key and send it to me
>
> Groq's free tier is more than enough for everyday use.

## What the agent does after receiving the key

1. Write the config: `config.set("groq_api_key", key)`
2. Test that the API works
3. Report back: "Speech-to-text is enabled. Now I can extract content even from videos without subtitles."
