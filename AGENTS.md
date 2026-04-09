# AGENTS.md

Guide de contribution pour agents (humains et IA) travaillant sur **Shorts Factory**.

Ce document décrit l'architecture des agents LangChain, les conventions du projet, et les règles à suivre pour ajouter / modifier un composant du pipeline.

---

## 🎯 Vue d'ensemble

Shorts Factory est un pipeline LCEL où **chaque étape est un agent** (au sens LangChain : un `Runnable` autonome). Le pipeline complet est défini dans `app/chains/pipeline.py` :

```
topic
  └─► ScriptChain        (ScriptGenerator → sortie structurée validée)
        └─► VoiceTool    (TTS)
              └─► VisualTool         (stock footage)
                    └─► VideoAssemblyTool   (ffmpeg)
                          └─► SubtitleTool       (SRT + burn-in)
                                └─► PublishingTool   (YouTube)
```

Toutes les étapes échangent un seul objet : `PipelineState` (TypedDict défini dans `app/chains/state.py`).

---

## 🧩 Catalogue des agents

| Agent | Fichier | Type LangChain | Input ajouté | Output ajouté |
|---|---|---|---|---|
| **ScriptChain** | `app/chains/script_chain.py` | `RunnableLambda` backed by `ScriptGenerator` | `topic` | `script` |
| **VoiceTool** | `app/tools/voice_tool.py` | `PipelineTool` | `script` | `audio_path` |
| **VisualTool** | `app/tools/visual_tool.py` | `PipelineTool` | `script` | `image_paths` |
| **VideoAssemblyTool** | `app/tools/video_tool.py` | `PipelineTool` | `image_paths`, `audio_path` | `video_path` |
| **SubtitleTool** | `app/tools/subtitle_tool.py` | `PipelineTool` | `script`, `video_path` | `subtitle_path`, `final_path` |
| **PublishingTool** | `app/tools/publish_tool.py` | `PipelineTool` | `final_path`, `script` | `youtube_id` |

La logique interne de génération de script vit dans `app/chains/script_generator.py` :
- prompt
- sortie structurée via schéma Pydantic
- validation métier
- fallback déterministe sans clé OpenAI

---

## 🏗️ Contrat d'un agent

Tout nouvel agent **DOIT** :

1. Hériter de `app.tools.base.PipelineTool`
2. Définir un attribut de classe `name: str` (utilisé pour les logs)
3. Implémenter `run(self, state: PipelineState) -> PipelineState`
4. **Ne jamais muter** `state` en place — toujours renvoyer `{**state, "nouvelle_clé": ...}`
5. Lever une exception en cas d'erreur (le wrapper `invoke` log et propage)
6. Être **idempotent** quand c'est possible (clé de stockage déterministe par `job_id`)

### Squelette type

```python
from app.tools.base import PipelineTool
from app.chains.state import PipelineState

class MyNewTool(PipelineTool):
    name = "MyNewTool"

    def run(self, state: PipelineState) -> PipelineState:
        # 1. lire les champs nécessaires
        script = state["script"]
        # 2. appeler l'API / faire le travail
        result = ...
        # 3. persister via storage si fichier
        # 4. retourner un état enrichi
        return {**state, "ma_nouvelle_clef": result}
```

### Ajouter l'agent au pipeline

Éditer `app/chains/pipeline.py` :

```python
return (
    build_script_chain()
    | VoiceTool()
    | VisualTool()
    | MyNewTool()          # ← ici
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

- **Pas de `print()`** : utilise `app.core.logging.log` (structlog).
- **Pas d'I/O direct** sur le disque : passe par `app.services.storage.get_storage()`.
- **Pas de secret en dur** : tout dans `app/core/config.py` via `pydantic-settings`.
- **Pas de dépendance circulaire** : `tools/` ne doit jamais importer `chains/pipeline.py`.
- **Pas de mutation d'état** : retourne toujours un nouveau dict.
- **Mode dégradé obligatoire** : si une clé API manque, l'agent doit produire un fallback exploitable (ex: silence pour TTS, couleur unie pour visuels) — le pipeline doit tourner end-to-end sans aucune clé.
- **ffmpeg en subprocess** : `check=True` + `capture_output=True`. Pas de shell=True.
- **Logs structurés** : `log.info("event.name", job_id=..., key=value)` — JSON, pas de f-string en message.

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

Le smoke test global (`tests/test_pipeline.py`) vérifie la composition LCEL avec des stubs — ne pas le supprimer en cas de refactor.

---

## ➕ Ajouter un nouveau LLM ou provider

1. Créer un wrapper minimal dans `app/services/` (ex: `coqui.py`)
2. L'utiliser depuis le tool concerné — **ne jamais** instancier le client dans `__init__` global (lazy-init dans `run()` pour rester testable)
3. Ajouter les variables nécessaires à `app/core/config.py` ET `.env.example`
4. Documenter dans le README section "Variables d'environnement"

---

## 🧠 Convention LCEL

- Préférer **LCEL** (`|`) à `Chain` legacy.
- Pour la logique conditionnelle complexe (branches, retries, validation humaine, multi-agent), migrer vers **LangGraph** — remplacer `build_pipeline()` par un `StateGraph` mais **garder le contrat `PipelineState`** pour ne pas casser les tools existants.
- Les callbacks LangChain (LangSmith, custom tracers) se branchent via `RunnableConfig` à `invoke()` — ne pas hardcoder.

---

## 🚦 Workflow de contribution

1. Créer une branche `feat/<nom>` ou `fix/<nom>`
2. Implémenter + test + log
3. `pytest` doit passer
4. `ruff check app/` doit passer
5. Mettre à jour ce fichier si tu ajoutes/modifies un agent
6. Mettre à jour le README si tu changes une variable d'env publique
7. Commit conventionnel : `feat(voice): add coqui provider`, `fix(video): handle 0-clip case`, etc.

---

## 🔭 Roadmap agents

Idées d'agents à ajouter (non implémentés) :

- `MusicTool` — fond musical libre de droits, ducking automatique
- `ThumbnailTool` — génération vignette via DALL·E / SDXL
- `HookOptimizerAgent` — A/B testing du hook via LLM critique (LangGraph loop)
- `AnalyticsAgent` — récupère les métriques YouTube et alimente la table `Metric`
- `HumanReviewAgent` — pause LangGraph + webhook Slack pour validation manuelle

Chaque ajout doit suivre le contrat décrit ci-dessus.
