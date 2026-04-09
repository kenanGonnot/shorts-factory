# Shorts Factory

Pipeline automatisée de génération et publication de **YouTube Shorts**, orchestrée avec **LangChain (LCEL)**.

```
graph TD
    A[Topic Input] --> B[ScriptChain]
    B --> C[VoiceTool]
    C --> D[VisualTool]
    D --> E[VideoAssemblyTool]
    E --> F[SubtitleTool]
    F --> G[PublishingTool]
    G --> H[YouTube Shorts]
```
```
topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
```


Chaque étape est un `Runnable[PipelineState, PipelineState]` composable avec l'opérateur `|`. Le pipeline complet est défini dans `app/chains/pipeline.py`.

---

## ✨ Fonctionnalités

- **Génération de script** via `ScriptGenerator` avec sortie structurée validée par schéma
- **Text-to-Speech** (ElevenLabs, fallback ffmpeg silence en dev)
- **Visuels** stock (Pexels, fallback couleur unie)
- **Assemblage vidéo** ffmpeg en 1080×1920 (format Shorts)
- **Sous-titres** SRT générés et incrustés
- **Upload YouTube Shorts** automatique
- **Jobs asynchrones** via Celery + Redis
- **Persistance** PostgreSQL (jobs, assets, métriques)
- **Stockage** local ou S3-compatible
- **Observabilité** : logs structurés JSON via `structlog`
- **CLI Typer** pour déclencher manuellement le pipeline
- **Dockerisé** : `docker compose up` et c'est parti

---

## 🧱 Stack technique

| Couche | Choix |
|---|---|
| Langage | Python 3.10 |
| API | FastAPI + Uvicorn |
| Orchestration | **LangChain LCEL** (Runnable) |
| Jobs | Celery + Redis |
| DB | PostgreSQL + SQLAlchemy 2 |
| Vidéo | ffmpeg |
| Stockage | local / S3 (boto3) |
| Config | pydantic-settings (`.env`) |
| Logs | structlog (JSON) |
| Conteneurs | Docker + docker-compose |

---

## 📁 Structure du projet

```
shorts-factory/
├── app/
│   ├── api/main.py              # FastAPI : POST /generate, GET /jobs/{id}
│   ├── core/                    # config, logging, db
│   ├── chains/
│   │   ├── state.py             # PipelineState (TypedDict)
│   │   ├── script_chain.py      # Adaptateur Runnable pour l'étape script
│   │   ├── script_generator.py  # Génération structurée + validation + fallback
│   │   └── pipeline.py          # build_pipeline() — composition LCEL
│   ├── tools/
│   │   ├── base.py              # PipelineTool(Runnable)
│   │   ├── voice_tool.py        # TTS
│   │   ├── visual_tool.py       # stock footage
│   │   ├── video_tool.py        # ffmpeg assembly
│   │   ├── subtitle_tool.py     # SRT + burn-in
│   │   └── publish_tool.py      # YouTube upload
│   ├── services/                # storage (local/S3), youtube client
│   ├── models/video.py          # VideoJob, VideoAsset, Metric
│   └── workers/                 # Celery app + tasks
├── scripts/run_pipeline.py      # CLI Typer
├── tests/                       # smoke tests
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## 🚀 Démarrage rapide

### 1. Cloner et configurer

```bash
git clone <repo>
cd shorts-factory
cp .env.example .env
# Éditez .env (clés API optionnelles — le pipeline tourne en mode dégradé sans elles)
```
 
### 2. Lancer avec Docker

```bash
docker compose up --build
```

Services exposés :
- API → `http://localhost:8000` (Swagger sur `/docs`)
- Postgres → `localhost:5432`
- Redis → `localhost:6379`
- Worker Celery → en background

### 3. Déclencher un job

**Via API :**
```bash
curl -X POST localhost:8000/generate \
  -H 'content-type: application/json' \
  -d '{"topic": "3 surprising facts about octopuses"}'
# → {"job_id": "...", "status": "pending"}

curl localhost:8000/jobs/<job_id>
```

**Via CLI :**
```bash
python -m scripts.run_pipeline "Why coffee makes you focus"
```

---

## 🧠 Flow LangChain

Le pipeline complet est **une seule expression LCEL** :

```python
# app/chains/pipeline.py
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

Un `PipelineState` (TypedDict) traverse les étapes et s'enrichit à chaque passage : `script`, `audio_path`, `image_paths`, `video_path`, `subtitle_path`, `final_path`, `youtube_id`.

`ScriptChain` reste l'entrée LCEL du pipeline, mais l'implémentation est maintenant déléguée à `ScriptGenerator`, qui:
- génère un script structuré via `ChatOpenAI.with_structured_output(...)`
- valide le payload via un schéma Pydantic
- applique un fallback déterministe quand `OPENAI_API_KEY` est absent

Les autres tools héritent de `PipelineTool(Runnable[State, State])` — isolés, testables individuellement, et swappables (changer ElevenLabs → Coqui = modifier un seul fichier).

---

## ⚙️ Variables d'environnement

Voir `.env.example`. Les principales :

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Clé LLM |
| `LLM_MODEL` | Modèle (défaut: `gpt-4o-mini`) |
| `ELEVENLABS_API_KEY` | TTS (optionnel en dev) |
| `PEXELS_API_KEY` | Stock footage (optionnel) |
| `YOUTUBE_CLIENT_SECRETS_FILE` | OAuth Google (optionnel — dryrun sinon) |
| `STORAGE_BACKEND` | `local` ou `s3` |
| `DATABASE_URL` | URL Postgres |
| `REDIS_URL` | URL Redis |

> Sans aucune clé API, le pipeline tourne en **mode dégradé** : audio silencieux, clip couleur unie, upload YouTube en dryrun. Idéal pour valider la plomberie.

---

## 🧪 Tests

```bash
pytest
```

Le test smoke (`tests/test_pipeline.py`) compose le pipeline avec des stubs et vérifie que le `PipelineState` traverse toutes les étapes.

---

## 🔌 Extensibilité

- **Nouveau provider TTS** : créer une classe qui hérite de `PipelineTool` avec le même contrat d'état, l'importer dans `pipeline.py`.
- **Nouvelle étape** : insérer un nouveau Runnable dans la chaîne (ex: `MusicTool`, `ThumbnailTool`).
- **Multi-Agent (MAS)** : la composition LCEL est compatible avec LangGraph — remplacer `build_pipeline()` par un graphe pour gérer branches conditionnelles, retries, ou validation humaine.
- **Nouveau backend de stockage** : implémenter `Storage` dans `app/services/storage.py`.

---

## 📊 Observabilité

- Logs structurés JSON via `structlog`
- Événements `tool.start` / `tool.end` / `tool.error` par étape avec `job_id`
- Compatible avec **LangSmith** : ajouter `LANGCHAIN_TRACING_V2=true` et `LANGCHAIN_API_KEY` dans `.env`

---

## 📜 Licence

MIT — voir `LICENSE` (à ajouter).
