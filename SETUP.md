# Setup Guide -- Shorts Factory

This guide explains how to get every API key the project uses and how to configure your environment.

---

## 1. Clone and create your `.env`

```bash
git clone <repo-url>
cd shorts-factory
cp .env.example .env
```

Edit `.env` with the values described below. **No API key is strictly required** -- the pipeline runs end-to-end in degraded mode (silent audio, solid-color visuals, YouTube dry-run).

---

## 2. API Keys

### OpenAI (script generation)

Used by `ScriptChain` to generate structured scripts via `gpt-4o-mini` (or any model you configure).

1. Go to <https://platform.openai.com/signup> and create an account (or log in).
2. Navigate to **API keys**: <https://platform.openai.com/api-keys>.
3. Click **"Create new secret key"**, give it a name, and copy it.
4. Paste it into `.env`:

```
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini          # optional, change model here
```

**Without this key:** the pipeline uses a deterministic fallback script (good for testing).

---

### ElevenLabs (text-to-speech)

Used by `VoiceTool` to generate voiceover audio.

1. Go to <https://elevenlabs.io> and create an account.
2. Navigate to your **Profile** page (click your avatar, top-right).
3. Copy your **API Key** from the profile section.
4. (Optional) Browse **Voices** in the VoiceLab to find a voice ID you like.
5. Paste into `.env`:

```
ELEVENLABS_API_KEY=your-key-here
ELEVENLABS_VOICE_ID=Rachel      # default voice; change to any ElevenLabs voice ID
ELEVENLABS_MODEL=eleven_turbo_v2
VOICE_PROVIDER=auto             # auto = ElevenLabs if key present, silent otherwise
```

**Without this key:** the pipeline generates a silent `.mp3` file via ffmpeg (degraded mode).

---

### Pexels (stock video footage)

Used by `PexelsVisualProvider` for stock video clips (primarily for `body` sections).

1. Go to <https://www.pexels.com/api/> and click **"Get Started"**.
2. Create a free account or log in.
3. Create a new API project and copy the **API Key**.
4. Paste into `.env`:

```
PEXELS_API_KEY=your-key-here
```

**Without this key:** the visual pipeline falls back to solid-color placeholder clips.

---

### Google / Gemini (AI image generation -- Nano Banana 2)

Used by `NanoBananaVisualProvider` to generate still images for `hook` and `cta` sections. The model used is **Gemini 3.1 Flash Image** (`gemini-3.1-flash-image`), internally known as Nano Banana 2.

1. Go to <https://aistudio.google.com/apikey>.
2. Sign in with your Google account.
3. Click **"Create API key"** and select or create a Google Cloud project.
4. Copy the generated key.
5. Paste into `.env`:

```
GOOGLE_API_KEY=your-key-here
VISUAL_AI_MODEL=gemini-3.1-flash-image   # default, can be changed
```

**Without this key:** image generation requests fall through to the `FallbackVisualProvider` (solid-color frames). The pipeline still works.

---

### YouTube (upload)

Used by `PublishingTool` to upload the final video as a YouTube Short.

1. Go to the **Google Cloud Console**: <https://console.cloud.google.com/>.
2. Create a project (or select an existing one).
3. Enable the **YouTube Data API v3**:
   - Navigate to **APIs & Services > Library**.
   - Search for "YouTube Data API v3" and click **Enable**.
4. Create **OAuth 2.0 credentials**:
   - Go to **APIs & Services > Credentials**.
   - Click **"Create Credentials" > "OAuth client ID"**.
   - Application type: **Desktop app** (or Web if hosting).
   - Download the JSON file.
5. Place the JSON file somewhere accessible and reference it in `.env`:

```
YOUTUBE_CLIENT_SECRETS_FILE=/path/to/client_secret.json
YOUTUBE_TOKEN_FILE=/path/to/token.json    # will be created on first auth
YOUTUBE_PRIVACY=private                   # private | unlisted | public
```

On first run, the tool will open a browser for OAuth consent. After that, the token file is cached.

**Without this key:** YouTube upload runs in dry-run mode (video is produced but not uploaded).

---

## 3. Visual Provider Strategy

The visual pipeline supports multiple provider strategies, configured via:

```
VISUAL_PROVIDER=section_map
```

| Value          | Behavior                                                    |
|----------------|-------------------------------------------------------------|
| `section_map`  | Per-section provider mapping (default, see below)           |
| `pexels`       | Use Pexels stock footage for all sections                   |
| `nano_banana`  | Use Gemini AI image generation for all sections             |
| `fallback`     | Use solid-color fallback for all sections (no API needed)   |

Default section mapping (when `VISUAL_PROVIDER=section_map`):

| Section | Provider         | Reason                              |
|---------|------------------|-------------------------------------|
| `hook`  | `nano_banana`    | Eye-catching generated image        |
| `body`  | `pexels`         | Motion video holds viewer attention  |
| `cta`   | `nano_banana`    | Clean branded still for CTA         |

---

## 4. Infrastructure

### Docker (recommended)

```bash
docker compose up --build
```

This starts PostgreSQL, Redis, the API server, and the Celery worker. No local install needed.

### Local development

Requirements: **Python 3.10+**, **ffmpeg**, **PostgreSQL**, **Redis**.

```bash
# Install dependencies
pip install -e ".[dev]"

# Or with uv
uv sync

# Set infra URLs in .env
DATABASE_URL=postgresql+psycopg://shorts:shorts@localhost:5432/shorts
REDIS_URL=redis://localhost:6379/0

# Run the pipeline via CLI
python -m scripts.run_pipeline "3 surprising facts about octopuses"
```

### Storage

```
STORAGE_BACKEND=local
STORAGE_LOCAL_DIR=./storage     # local path for generated assets
```

For S3-compatible storage:

```
STORAGE_BACKEND=s3
S3_BUCKET=my-bucket
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
```

---

## 5. Running tests

```bash
pytest
```

Tests run without any API keys -- all external calls are stubbed.

---

## 6. Quick reference -- minimal `.env`

For the **full pipeline** with all features:

```
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...
PEXELS_API_KEY=...
GOOGLE_API_KEY=...
```

For **zero-config testing** (degraded mode):

```
# leave everything empty or use defaults from .env.example
ENV=dev
```
