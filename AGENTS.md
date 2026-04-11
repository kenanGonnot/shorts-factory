# AGENTS.md

Guide de contribution pour agents (humains et IA) travaillant sur **Shorts Factory**.

Ce document fusionne l'ancien `project.md` et devient la référence unique pour :
- l'architecture du projet
- le contrat `PipelineState`
- les conventions de contribution et d'extension du pipeline

---

## 🎯 Vue d'ensemble

Shorts Factory est un pipeline **LangChain LCEL** qui transforme un simple topic en **YouTube Short vertical complet** :

```
topic
  └─► ScriptChain
        └─► VoiceTool
              └─► VisualTool
                    └─► VideoAssemblyTool
                          └─► SubtitleTool
                                └─► PublishingTool
```

Ou, sous forme compacte :

```
topic → script → voice → visuals → video assembly → subtitles → YouTube
```

Le pipeline complet est défini dans `app/chains/pipeline.py`.

Le projet doit rester exécutable **sans aucune clé API**. En mode dégradé :
- le script passe en fallback déterministe
- la voix passe en audio silencieux
- les visuels passent en assets offline / couleur unie
- la publication YouTube passe en dry-run

Toutes les étapes échangent un seul objet : `PipelineState` (`TypedDict` défini dans `app/chains/state.py`).

---

## 🧱 Stack technique

| Couche | Choix |
|---|---|
| Langage | Python 3.10+ |
| Pipeline | LangChain LCEL (`Runnable \|`) |
| API | FastAPI + Uvicorn |
| Jobs asynchrones | Celery + Redis |
| Base de données | PostgreSQL + SQLAlchemy 2 |
| Vidéo | ffmpeg |
| Stockage | système de fichiers local ou S3-compatible |
| Configuration | `pydantic-settings` (`.env`) |
| Logs | `structlog` (JSON) |
| Conteneurs | Docker + docker-compose |

---

## 📁 Structure du projet

```
app/
├── api/main.py              # FastAPI: POST /generate, GET /jobs/{id}, GET /health
├── chains/
│   ├── state.py             # PipelineState TypedDict — l'enveloppe commune
│   ├── script_chain.py      # Adaptateur Runnable pour l'étape script
│   ├── script_generator.py  # LLM + schéma Pydantic + fallback déterministe
│   └── pipeline.py          # build_pipeline() — l'expression LCEL principale
├── tools/
│   ├── base.py              # PipelineTool(Runnable) — base class commune
│   ├── voice_tool.py        # TTS + persistance audio / segments
│   ├── visual_tool.py       # Orchestrateur visuel (planner → providers → normalizer)
│   ├── video_tool.py        # Concat ffmpeg + mux audio
│   ├── subtitle_tool.py     # Génération SRT + burn-in
│   └── publish_tool.py      # Upload YouTube / dry-run
├── visual/
│   ├── models.py            # VisualRequest, VisualAsset, ResolvedAsset
│   ├── planner.py           # Planification déterministe des slots visuels
│   ├── providers.py         # Pexels / Nano Banana / fallback offline
│   └── normalizer.py        # Normalisation ffmpeg en MP4 1080x1920 homogène
├── voice/
│   ├── models.py            # VoiceSegment
│   ├── providers.py         # ElevenLabsProvider, SilentProvider
│   └── renderer.py          # Chunking + assemblage audio
├── core/
│   ├── config.py            # Settings pilotés par l'env
│   ├── logging.py           # Configuration structlog
│   └── db.py                # SQLAlchemy engine + session factory
├── services/
│   ├── storage.py           # LocalStorage / S3Storage
│   └── youtube.py           # Wrapper YouTube Data API
├── models/video.py          # ORM: VideoJob, VideoAsset, Metric
└── workers/
    ├── celery_app.py        # App Celery
    └── tasks.py             # Tâche generate_video
```

---

## 📦 Contrat du `PipelineState`

Chaque tool lit et écrit le même `PipelineState`. Les champs sont cumulatifs : on enrichit l'état, on ne remplace pas les sorties précédentes.

| Champ | Renseigné par | Description |
|---|---|---|
| `job_id` | caller | identifiant unique du run |
| `topic` | caller | topic d'entrée |
| `script` | `ScriptChain` | script structuré : `title`, `hook`, `body`, `cta`, `tags` |
| `audio_path` | `VoiceTool` | chemin local vers le MP3 final |
| `audio_segments_path` | `VoiceTool` | chemin local vers le JSON des segments |
| `audio_segments` | `VoiceTool` | segments `{section, chunk_index, text, duration_ms}` |
| `audio_duration_ms` | `VoiceTool` | durée totale de l'audio en ms |
| `voice_provider` | `VoiceTool` | provider réellement utilisé (`elevenlabs` ou `silent`) |
| `voice_id` | `VoiceTool` | identifiant de voix utilisé |
| `visual_assets` | `VisualTool` | manifeste riche des assets visuels normalisés |
| `video_path` | `VideoAssemblyTool` | chemin local vers la vidéo assemblée sans sous-titres |
| `subtitle_path` | `SubtitleTool` | chemin local vers le fichier `.srt` |
| `final_path` | `SubtitleTool` | chemin local vers le MP4 final avec sous-titres incrustés |
| `youtube_id` | `PublishingTool` | identifiant YouTube ou `None` en dry-run |

---

## 🧩 Catalogue des agents

| Agent | Fichier | Type LangChain | Input lu | Output ajouté |
|---|---|---|---|---|
| **ScriptChain** | `app/chains/script_chain.py` | `RunnableLambda` backed by `ScriptGenerator` | `topic` | `script` |
| **VoiceTool** | `app/tools/voice_tool.py` | `PipelineTool` | `script` | `audio_path`, `audio_segments_path`, `audio_segments`, `audio_duration_ms`, `voice_provider`, `voice_id` |
| **VisualTool** | `app/tools/visual_tool.py` | `PipelineTool` | `script`, `audio_segments`, `audio_duration_ms` | `visual_assets` |
| **VideoAssemblyTool** | `app/tools/video_tool.py` | `PipelineTool` | `visual_assets`, `audio_path` | `video_path` |
| **SubtitleTool** | `app/tools/subtitle_tool.py` | `PipelineTool` | `script`, `video_path` | `subtitle_path`, `final_path` |
| **PublishingTool** | `app/tools/publish_tool.py` | `PipelineTool` | `final_path`, `script` | `youtube_id` |

La logique interne de génération de script vit dans `app/chains/script_generator.py` :
- prompt
- sortie structurée via schéma Pydantic
- validation métier
- fallback déterministe sans clé OpenAI

---

## 🖼️ Architecture du Visual Agent

Le `VisualTool` n'est plus un simple fetcher de stock footage. Il joue le rôle d'un **Visual Agent** avec trois composants internes :

- **`VisualPlanner`** (`app/visual/planner.py`) : transforme `script` + métadonnées voix en slots visuels déterministes.
- **`VisualProvider`** (`app/visual/providers.py`) : résout chaque slot via `Pexels`, `Nano Banana` ou le fallback offline.
- **`VisualNormalizer`** (`app/visual/normalizer.py`) : homogénéise tous les assets en clips MP4 1080x1920 prêts pour l'assemblage.

Stratégie par défaut :
- `hook` → `nano_banana`
- `body` → `pexels`
- `cta` → `nano_banana`

Si le provider primaire échoue ou si les credentials manquent, la chaîne bascule automatiquement vers `fallback`.

---

## 🏗️ Contrat d'un agent

Tout nouvel agent **DOIT** :

1. Hériter de `app.tools.base.PipelineTool`
2. Définir un attribut de classe `name: str` (utilisé pour les logs)
3. Implémenter `run(self, state: PipelineState) -> PipelineState`
4. **Ne jamais muter** `state` en place — toujours renvoyer `{**state, "nouvelle_clé": ...}`
5. Lever une exception en cas d'erreur (le wrapper `invoke` log et propage)
6. Résoudre ses dépendances externes de manière lazy dans `run()` quand c'est possible
7. Être **idempotent** quand c'est possible (clé de stockage déterministe par `job_id`)
8. Prévoir un **mode dégradé exploitable** quand une API ou un secret manque

### Squelette type

```python
from app.tools.base import PipelineTool
from app.chains.state import PipelineState


class MyNewTool(PipelineTool):
    name = "MyNewTool"

    def run(self, state: PipelineState) -> PipelineState:
        script = state["script"]
        result = ...
        return {**state, "ma_nouvelle_clef": result}
```

### Ajouter l'agent au pipeline

Éditer `app/chains/pipeline.py` :

```python
return (
    build_script_chain()
    | VoiceTool()
    | VisualTool()
    | MyNewTool()
    | VideoAssemblyTool()
    | SubtitleTool()
    | PublishingTool()
)
```

### Étendre l'état

Éditer `app/chains/state.py` pour ajouter le champ optionnel :

```python
class PipelineState(TypedDict, total=False):
    ...
    ma_nouvelle_clef: str
```

---

## 🔐 Règles non négociables

- **Pas de `print()`** : utiliser `app.core.logging.log` (`structlog`).
- **Pas d'I/O direct** sur le disque : passer par `app.services.storage.get_storage()`.
- **Pas de secret en dur** : tout passe par `app/core/config.py`.
- **Pas de dépendance circulaire** : `tools/` ne doit jamais importer `chains/pipeline.py`.
- **Pas de mutation d'état** : toujours retourner un nouveau dict.
- **Mode dégradé obligatoire** : le pipeline doit tourner end-to-end sans aucune clé.
- **Clients externes lazy-init** : pas d'instanciation au chargement du module si cela complique les tests.
- **ffmpeg en subprocess** : `check=True` + `capture_output=True`, jamais `shell=True`.
- **Logs structurés** : `log.info("event.name", job_id=..., key=value)`.
- **Noeud public unique** : si une étape grossit, garder un noeud pipeline clair (`VisualTool`) et déplacer la complexité dans des modules internes (`app/visual/`, `app/voice/`, etc.).

---

## ▶️ Exécution locale

```bash
git clone <repo>
cd shorts-factory
cp .env.example .env
pip install -e ".[dev]"
python -m scripts.run_pipeline "3 surprising facts about octopuses"
docker compose up --build
```

Endpoints exposés par l'API :
- `POST /generate`
- `GET /jobs/{job_id}`
- `GET /health`

Swagger : `http://localhost:8000/docs`

---

## ⚙️ Variables d'environnement clés

Voir `.env.example` pour le minimum et `app/core/config.py` pour la liste complète supportée par l'application.

| Variable | Défaut | Description |
|---|---|---|
| `OPENAI_API_KEY` | `""` | clé LLM ; vide → fallback script |
| `LLM_MODEL` | `gpt-4o-mini` | modèle OpenAI |
| `VOICE_PROVIDER` | `auto` | `auto` \| `elevenlabs` \| `silent` |
| `ELEVENLABS_API_KEY` | `""` | clé TTS ; vide → audio silencieux |
| `PEXELS_API_KEY` | `""` | stock footage ; vide → fallback |
| `GOOGLE_API_KEY` | `""` | clé Gemini image générique |
| `NANO_BANANA_API_KEY` | `""` | override dédié au provider image |
| `NANO_BANANA_MODEL` | `""` | override du modèle visuel |
| `VISUAL_PROVIDER` | `section_map` | `section_map` \| `pexels` \| `nano_banana` \| `fallback` |
| `YOUTUBE_CLIENT_SECRETS_FILE` | `""` | OAuth Google ; vide → dry-run |
| `STORAGE_BACKEND` | `local` | `local` \| `s3` |
| `STORAGE_LOCAL_DIR` | `./storage` | racine du stockage local |
| `DATABASE_URL` | `postgresql+psycopg://shorts:shorts@localhost:5432/shorts` | URL PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | URL Redis |

---

## 🧪 Tester un agent

Chaque agent doit avoir un test unitaire isolé sous `tests/`. Exemple :

```python
from app.tools.voice_tool import VoiceTool


def test_voice_tool_dev_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path))
    state = {"job_id": "t1", "script": {"hook": "h", "body": "b", "cta": "c"}}
    out = VoiceTool().invoke(state)
    assert out["audio_path"].endswith(".mp3")
```

Commandes attendues :

```bash
pytest
ruff check app/
```

Le smoke test global (`tests/test_pipeline.py`) vérifie la composition LCEL avec des stubs — ne pas le supprimer pendant un refactor.

---

## ➕ Ajouter un nouveau LLM ou provider

1. Créer un wrapper minimal dans `app/services/`, `app/voice/` ou `app/visual/` selon le domaine.
2. L'utiliser depuis le tool concerné — **ne jamais** instancier le client dans un `__init__` global.
3. Ajouter les variables nécessaires à `app/core/config.py` et, si elles sont publiques, à `.env.example`.
4. Documenter le comportement dans le `README.md`.
5. Prévoir un fallback utilisable si le provider est indisponible.

---

## 🧠 Convention LCEL

- Préférer **LCEL** (`|`) aux `Chain` legacy.
- Pour la logique conditionnelle complexe (branches, retries, validation humaine, multi-agent), migrer vers **LangGraph**.
- Si `build_pipeline()` devient un graphe, **garder le contrat `PipelineState`** pour ne pas casser les tools existants.
- Les callbacks LangChain (LangSmith, custom tracers) doivent passer par `RunnableConfig` à `invoke()`, pas via du hardcode.

---

## 🚦 Workflow de contribution

1. Créer une branche `feat/<nom>` ou `fix/<nom>`.
2. Implémenter + tester + logger.
3. `pytest` doit passer.
4. `ruff check app/` doit passer.
5. Mettre à jour ce fichier si tu ajoutes ou modifies un agent, un champ d'état, ou un contrat d'orchestration.
6. Mettre à jour le `README.md` si tu changes une commande, un endpoint, ou une variable d'env publique.
7. Utiliser un commit conventionnel : `feat(voice): add coqui provider`, `fix(video): handle 0-clip case`, etc.

---

## 🔭 Roadmap agents

Idées d'agents à ajouter :

- `MusicTool` — fond musical libre de droits avec ducking automatique
- `ThumbnailTool` — génération de vignette via DALL·E / SDXL
- `HookOptimizerAgent` — A/B testing du hook via boucle critique LLM
- `AnalyticsAgent` — récupération des métriques YouTube et alimentation de `Metric`
- `HumanReviewAgent` — pause LangGraph + webhook Slack pour validation manuelle

Chaque ajout doit suivre le contrat décrit ci-dessus.
