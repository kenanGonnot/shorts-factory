# Shorts Factory

Pipeline automatisée de génération et de publication de **YouTube Shorts** orchestrée avec **LangChain LCEL**.

```
topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
```

À partir d'un topic, le projet produit un short vertical complet et peut l'uploader sur YouTube. Sans credentials, le pipeline continue à tourner en **mode dégradé** : script déterministe, audio silencieux, visuels offline et publication en dry-run.

---

## ✨ Fonctionnalités

- Génération de script structurée via `ScriptGenerator`
- Text-to-Speech avec `ElevenLabs` ou fallback silencieux
- Orchestration visuelle par section (`hook`, `body`, `cta`) avec providers interchangeables
- Normalisation et assemblage vidéo via `ffmpeg` en 1080x1920
- Génération de sous-titres SRT et burn-in
- Upload YouTube automatisé avec mode dry-run sans secrets
- API FastAPI, workers Celery, persistance PostgreSQL
- Stockage local ou S3-compatible
- Logs JSON via `structlog`

---

## 🧱 Stack technique

| Couche | Choix |
|---|---|
| Langage | Python 3.10+ |
| Pipeline | LangChain LCEL (`Runnable \|`) |
| API | FastAPI + Uvicorn |
| Jobs | Celery + Redis |
| DB | PostgreSQL + SQLAlchemy 2 |
| Vidéo | ffmpeg |
| Stockage | local / S3-compatible |
| Config | `pydantic-settings` |
| Logs | `structlog` |
| Conteneurs | Docker + docker-compose |

---

## 🧠 Architecture

Le pipeline complet est défini dans `app/chains/pipeline.py` :

```python
def build_pipeline() -> Runnable:
    return (
        build_script_chain()
        | VoiceTool()
        | VisualTool()
        | VideoAssemblyTool()
        | SubtitleTool()
        | PublishingTool()
    )
```

Chaque étape échange un unique `PipelineState` qui s'enrichit au fil du run. Les principaux champs produits sont :

| Champ | Produit par |
|---|---|
| `script` | `ScriptChain` |
| `audio_path`, `audio_segments`, `audio_segments_path` | `VoiceTool` |
| `visual_assets` | `VisualTool` |
| `video_path` | `VideoAssemblyTool` |
| `subtitle_path`, `final_path` | `SubtitleTool` |
| `youtube_id` | `PublishingTool` |

Le module visuel repose sur trois briques internes :
- `VisualPlanner` : transforme le script et la voix en slots visuels
- `VisualProvider` : résout chaque slot (`pexels`, `nano_banana`, `fallback`)
- `VisualNormalizer` : convertit tout en clips MP4 homogènes avant assemblage

Par défaut, la stratégie visuelle est `section_map` :
- `hook` → `nano_banana`
- `body` → `pexels`
- `cta` → `nano_banana`

---

## 📁 Structure du projet

```
shorts-factory/
├── app/
│   ├── api/main.py
│   ├── chains/
│   ├── core/
│   ├── services/
│   ├── tools/
│   ├── visual/
│   ├── voice/
│   ├── workers/
│   └── models/video.py
├── scripts/run_pipeline.py
├── tests/
├── docs/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## 🚀 Démarrage rapide

### 1. Prérequis

- Python 3.10+
- `ffmpeg`
- Docker + Docker Compose si vous voulez lancer l'API, Redis et Postgres ensemble

### 2. Installation locale

```bash
git clone <repo>
cd shorts-factory
cp .env.example .env
pip install -e ".[dev]"
```

### 3. Exécuter un run complet en CLI

```bash
python -m scripts.run_pipeline "3 surprising facts about octopuses"
```

### 4. Lancer la stack complète

```bash
docker compose up --build
```

Services exposés :
- API : `http://localhost:8000`
- Swagger : `http://localhost:8000/docs`
- Redis : `localhost:6379`
- PostgreSQL : `localhost:5432`

---

## 🌐 API

### Créer un job

```bash
curl -X POST http://localhost:8000/generate \
  -H "content-type: application/json" \
  -d '{"topic": "Why coffee makes you focus"}'
```

Réponse :

```json
{"job_id":"<uuid>","status":"pending"}
```

### Lire l'état d'un job

```bash
curl http://localhost:8000/jobs/<job_id>
```

### Vérifier la santé du service

```bash
curl http://localhost:8000/health
```

---

## ⚙️ Variables d'environnement

Le template minimal est `.env.example`. Les réglages avancés sont définis dans `app/core/config.py`.

| Variable | Défaut | Description |
|---|---|---|
| `OPENAI_API_KEY` | `""` | clé LLM ; vide → fallback déterministe |
| `LLM_MODEL` | `gpt-4o-mini` | modèle OpenAI |
| `VOICE_PROVIDER` | `auto` | `auto` \| `elevenlabs` \| `silent` |
| `ELEVENLABS_API_KEY` | `""` | clé TTS ; vide → silence |
| `PEXELS_API_KEY` | `""` | clé stock footage |
| `GOOGLE_API_KEY` | `""` | clé Gemini image générique |
| `NANO_BANANA_API_KEY` | `""` | clé dédiée au provider image |
| `NANO_BANANA_MODEL` | `""` | override du modèle visuel |
| `VISUAL_PROVIDER` | `section_map` | `section_map` \| `pexels` \| `nano_banana` \| `fallback` |
| `YOUTUBE_CLIENT_SECRETS_FILE` | `""` | secrets OAuth YouTube ; vide → dry-run |
| `YOUTUBE_TOKEN_FILE` | `""` | token OAuth persisté |
| `YOUTUBE_PRIVACY` | `private` | visibilité de publication |
| `STORAGE_BACKEND` | `local` | `local` \| `s3` |
| `STORAGE_LOCAL_DIR` | `./storage` | stockage local |
| `DATABASE_URL` | `postgresql+psycopg://shorts:shorts@localhost:5432/shorts` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | broker / backend Celery |

---

## 🧪 Tests

```bash
pytest
ruff check app/
```

Les tests couvrent :
- la configuration et les fallbacks
- la génération de script
- la voix et les métadonnées de segments
- le pipeline visuel
- la composition LCEL de bout en bout

---

## 🔌 Extensibilité

- Ajouter un nouveau tool : créer un `PipelineTool`, étendre `PipelineState`, puis l'insérer dans `build_pipeline()`.
- Ajouter un provider voix ou visuel : encapsuler l'intégration dans `app/voice/` ou `app/visual/` avec lazy-init et fallback.
- Passer à LangGraph : possible tant que le contrat `PipelineState` reste stable pour les tools existants.

Les règles de contribution détaillées vivent dans `AGENTS.md`.
