# Visual Module — Explication pas à pas

Ce document décortique le **Visual Module** de `shorts-factory` :
comment, à partir d'un script textuel et du timing de la voix off, on
produit une liste de clips vidéo verticaux **prêts à être assemblés**
dans le short final.

> Fichiers concernés
> - `app/visual/models.py` — les structures de données (contrats)
> - `app/visual/planner.py` — fabrique les "slots" visuels
> - `app/visual/providers.py` — va chercher (ou génère) les médias
> - `app/visual/normalizer.py` — uniformise tout en `1080x1920 .mp4`
> - `app/tools/visual_tool.py` — le chef d'orchestre
> - `app/core/config.py` — la config (`Settings`)
> - `docs/visual_module.md` — la spec courte de référence

---

## 1. Le rôle du module en une image

Le module visual se place **après** la génération du script et de la
voix off, et **avant** l'assemblage vidéo final :

```
          ┌───────────┐      ┌───────────┐      ┌───────────────┐      ┌────────────┐
 topic →  │  Script   │  →   │   Voice   │  →   │    VISUAL     │  →   │  Assembly  │  → short.mp4
          │   Tool    │      │   Tool    │      │    MODULE     │      │    Tool    │
          └───────────┘      └───────────┘      └───────────────┘      └────────────┘
                script          audio +              visual_assets         video + audio
                                segments             (manifest)            + subtitles
```

**Contrat d'entrée** (lu dans `PipelineState`, voir `app/chains/state.py`) :

| Clé | Type | Obligatoire ? |
|---|---|---|
| `job_id` | `str` | oui (sert de clé de stockage) |
| `script` | `Script` (`title`/`hook`/`body`/`cta`) | oui |
| `audio_segments` | `list[dict]` | non — issu de `VoiceTool` |
| `audio_duration_ms` | `int` | non — utilisé seulement si pas de segments |

**Contrat de sortie** : une nouvelle clé `visual_assets` — une liste de
dictionnaires, un par "slot" visuel. Chaque `path` pointe vers un
`.mp4` **1080×1920 H.264** déjà à la bonne durée.

> 💡 Point clé : après le visual module, tous les clips ont la **même
> résolution, le même fps et la bonne durée**. `VideoAssemblyTool` n'a
> plus qu'à les concaténer et coller la piste audio dessus.

---

## 2. Les 4 composants — une vue en couches

```
┌────────────────────────────────────────────────────────────────────┐
│                          VisualTool  (orchestrateur)                │
│                       app/tools/visual_tool.py                      │
│                                                                     │
│   ┌───────────┐    ┌───────────────┐    ┌─────────────────────┐     │
│   │  Planner  │ →  │  Providers    │ →  │     Normalizer      │     │
│   │  (pur)    │    │  (réseau/IA)  │    │     (ffmpeg)        │     │
│   └───────────┘    └───────────────┘    └─────────────────────┘     │
│        ↑                  ↑                      ↑                  │
│        │                  │                      │                  │
│   script+audio      VisualRequest          ResolvedAsset            │
│   segments          (slot planifié)        (bytes bruts)            │
│                                                                     │
│                                                  ↓                  │
│                                           VisualAsset (mp4)         │
└────────────────────────────────────────────────────────────────────┘
```

Chaque couche a **une seule responsabilité** :

1. **Planner** : décide *combien* de plans il faut, *quand* ils
   commencent/finissent et *quoi* y mettre comme prompt/requête.
   → pure fonction, zéro IO.
2. **Providers** : prennent un slot et renvoient des **octets bruts**
   (image ou vidéo). Trois implémentations : Pexels, Nano Banana,
   Fallback.
3. **Normalizer** : prend ces octets et produit un `.mp4` 1080×1920
   de la **bonne durée exacte**, sauvegardé dans le `Storage`.
4. **VisualTool** : câble les trois ensemble et gère la **chaîne de
   fallback** si un provider échoue.

---

## 3. Les types de données (`app/visual/models.py`)

Trois dataclasses immuables (`frozen=True, slots=True`) forment le
langage commun entre les couches :

```
VisualRequest                  ResolvedAsset                 VisualAsset
─────────────                  ─────────────                 ───────────
section    "hook|body|cta"     asset_type  "clip|image"      section
chunk_index 0,1,2...           data        bytes             chunk_index
start_ms   int                 mime_type   "video/mp4"...    asset_type
end_ms     int                 provider    "pexels"...       provider
prompt     str (pour IA)       source_url  str|None          path        → .mp4 final
query      str (pour stock)                                  start_ms / end_ms
                                                             duration_ms
   ↑ entrée du provider        ↑ sortie du provider          width=1080 height=1920
   (ce qu'on veut)             (octets bruts)                prompt, source_url

                              [       Normalizer        ]
                           VisualRequest + ResolvedAsset
                              →  VisualAsset (sauvé)
```

Pourquoi ce séparatisme ?
- `VisualRequest` = **plan** (ne change jamais après le planner).
- `ResolvedAsset` = **matière brute** (octets) — chaque provider sait
  en produire, personne ne touche au disque.
- `VisualAsset` = **résultat final** (chemin dans le `Storage`).

---

## 4. Étape 1 — `VisualPlanner` : du texte au timing

**Fichier** : `app/visual/planner.py`

Objectif : produire une liste ordonnée de `VisualRequest`, avec des
bornes temporelles cohérentes avec la voix off.

### 4.1 Deux chemins possibles

```
              plan(script, audio_segments, audio_duration_ms)
                               │
                 audio_segments │ non vide ?
                  ┌────────────┴────────────┐
                  │ OUI                     │ NON
                  ▼                         ▼
       _plan_from_segments()        _plan_equal_split()
       (1 slot par segment          (1 slot par section non vide,
        voix, timing repris         répartition égale sur
        du segment)                 audio_duration_ms)
                  │                         │
                  └──────────┬──────────────┘
                             ▼
                   list[VisualRequest]
```

### 4.2 Chemin principal : `_plan_from_segments`

C'est le chemin utilisé quand `VoiceTool` a déjà calculé les timings
chunk par chunk.

```python
# planner.py (simplifié)
cursor = 0
for seg in segments:
    section = seg["section"]                       # "hook" | "body" | "cta"
    duration = int(seg.get("duration_ms") or default_segment_ms)
    start, end = cursor, cursor + duration
    cursor = end
    requests.append(VisualRequest(
        section=section,
        chunk_index=int(seg.get("chunk_index", 0)),
        start_ms=start, end_ms=end,
        prompt=_prompt_for(script, section, seg["text"]),
        query=_query_for(script, section, seg["text"]),
    ))
```

Exemple avec 4 segments audio :

```
segments:          [ hook 1200ms ] [ body 2500ms ] [ body 2500ms ] [ cta 1000ms ]
                    0           1200          3700           6200         7200

VisualRequest #0:  section=hook  chunk=0  start=0     end=1200
VisualRequest #1:  section=body  chunk=0  start=1200  end=3700
VisualRequest #2:  section=body  chunk=1  start=3700  end=6200
VisualRequest #3:  section=cta   chunk=0  start=6200  end=7200
```

Remarques :
- les durées se **chaînent** via `cursor` → aucun trou, aucun chevauchement.
- un segment malformé (section inconnue) est **ignoré silencieusement**.
- un `duration_ms` à 0 est remplacé par `default_segment_ms` (3 s).

### 4.3 Chemin de secours : `_plan_equal_split`

Quand il n'y a pas de `audio_segments`, on découpe équitablement :

```
audio_duration_ms = 9000, sections non vides = hook/body/cta
                     │
                     ▼
base = 9000 // 3 = 3000
remainder = 9000 - 3000*3 = 0 (le reste va sur le dernier slot)

[ hook 3000ms ] [ body 3000ms ] [ cta 3000ms ]
 0         3000           6000           9000
```

Si `audio_duration_ms` est aussi absent, on tombe sur
`default_segment_ms * nb_sections` (donc 9000 ms par défaut). **Le
pipeline ne plante jamais faute de timing**.

### 4.4 Prompts déterministes (pas de LLM ici)

`_prompt_for` et `_query_for` sont de petites fonctions pures :

```python
# pour un "hook"
"Bold vertical 9:16 poster illustrating: {text}. High contrast, cinematic."

# pour un "cta"
"Clean 9:16 call-to-action still for: {title}. Minimalist, brand-friendly."

# pour "body"
"Informative 9:16 visual for: {text}"
```

Pourquoi c'est important ? **Reproductibilité** : deux `plan()` avec le
même script donneront exactement les mêmes prompts et queries — c'est
d'ailleurs testé explicitement dans `test_planner_prompts_are_deterministic`.

---

## 5. Étape 2 — Les `VisualProvider` : des octets pour chaque slot

**Fichier** : `app/visual/providers.py`

### 5.1 Le protocole

```python
class VisualProvider(Protocol):
    name: str
    def resolve(self, request: VisualRequest) -> ResolvedAsset: ...
```

Un provider prend **un** slot et renvoie **un** `ResolvedAsset`
(bytes + mime). Il **ne touche pas** au disque, à ffmpeg, ni au
storage — ce sont des détails qui appartiennent au `Normalizer`.

Si un provider n'y arrive pas, il lève une `VisualProviderError`.
L'orchestrateur bascule alors sur le suivant dans la chaîne.

### 5.2 Les trois implémentations

```
 ┌──────────────────────────────────────────────────────────────────┐
 │ PexelsVisualProvider            (stock video, HTTP)              │
 │  • search par `request.query` (portrait, per_page=5)             │
 │  • pick la plus haute résolution portrait → download .mp4        │
 │  • renvoie ResolvedAsset(asset_type="clip", mime="video/mp4")    │
 ├──────────────────────────────────────────────────────────────────┤
 │ NanoBananaVisualProvider        (Gemini 3.1 Flash Image)         │
 │  • POST generateContent avec `request.prompt`                    │
 │  • responseModalities=["IMAGE"], aspectRatio="9:16"              │
 │  • décode le base64 → PNG                                        │
 │  • renvoie ResolvedAsset(asset_type="image", mime="image/png")   │
 ├──────────────────────────────────────────────────────────────────┤
 │ FallbackVisualProvider          (offline, zero dépendance)       │
 │  • renvoie un PNG 16x16 gris foncé construit avec stdlib zlib    │
 │  • ne peut PAS échouer — aucun réseau, aucune lib externe        │
 └──────────────────────────────────────────────────────────────────┘
```

### 5.3 Pourquoi un fallback 100 % stdlib ?

Dans `providers.py` la fonction `_build_solid_png(w, h, rgb)` écrit
un PNG à la main en assemblant les chunks `IHDR` / `IDAT` / `IEND` et
en compressant les lignes avec `zlib`. Avantages :

- **zéro dépendance** (pas de Pillow) → pas de risque de CI rouge.
- **déterministe** → les mêmes octets à chaque exécution.
- **garanti valide** → le normalizer ne risque pas d'échouer sur
  une image corrompue.

Le pipeline **ne peut pas** échouer côté visuel : au pire il sort un
clip uniforme gris de la bonne durée.

### 5.4 Construction du registre (`build_providers`)

```
              build_providers(settings)
                       │
                       ▼
           ┌─────────────────────────┐
           │ {"fallback": Fallback()}│  ← toujours présent
           └─────────────────────────┘
                       │
       pexels_api_key ?│
                       ▼
           +  "pexels": PexelsVisualProvider(...)
                       │
       nano_banana_api_key
       or google_api_key ?│
                       ▼
           +  "nano_banana": NanoBananaVisualProvider(...)
                       │
                       ▼
                 dict de providers
```

Les clés manquantes **ne plantent rien** — le provider concerné est
juste absent du registre, et la chaîne tombe sur `fallback`.

---

## 6. Étape 3 — Le `VisualNormalizer` : tout en `1080×1920.mp4`

**Fichier** : `app/visual/normalizer.py`

C'est la seule couche qui parle à `ffmpeg` et au `Storage`.

### 6.1 Pourquoi normaliser ?

`VideoAssemblyTool` attend une liste de clips **interchangeables** :
même résolution, même fps, même codec. Sinon il faudrait re-encoder
à l'assemblage, gérer les cas image/vidéo différemment, etc.

La solution : **toujours** produire `1080×1920 @ 30 fps, H.264,
yuv420p, sans piste audio**, de la **durée exacte** du slot.

```
TARGET_WIDTH  = 1080
TARGET_HEIGHT = 1920
TARGET_FPS    = 30
_SCALE_VF     = scale=1080:1920:force_original_aspect_ratio=increase,
                crop=1080:1920,setsar=1
```

`scale=increase + crop` = on agrandit puis on rogne au centre pour
garantir le ratio 9:16 sans bandes noires.

### 6.2 Deux branches selon le `asset_type`

```
resolved.asset_type
        │
        ├── "image" → ffmpeg -loop 1 -i src.png -t <durée>
        │             -vf <scale+crop> -r 30 -pix_fmt yuv420p -an  out.mp4
        │             (une image fixe bouclée sur N secondes)
        │
        └── "clip"  → ffmpeg -i src.mp4 -t <durée>
                      -vf <scale+crop> -r 30 -pix_fmt yuv420p -an  out.mp4
                      (re-encodage au format cible)
```

> Note : le pan/zoom (effet Ken Burns) sur les images est
> **intentionnellement reporté** à plus tard. On garde d'abord un
> pipeline minimal et fiable.

### 6.3 Clé de stockage déterministe

```python
def _key(self, request: VisualRequest) -> str:
    return f"{self.job_id}/visuals/{request.section}_{request.chunk_index:02d}.mp4"
```

Exemples pour `job_id="demo"` :

```
demo/visuals/hook_00.mp4
demo/visuals/body_00.mp4
demo/visuals/body_01.mp4
demo/visuals/cta_00.mp4
```

Conséquence directe : **idempotence**. Relancer la pipeline sur le
même `job_id` écrase les mêmes fichiers — pas d'accumulation, pas de
chaos.

### 6.4 La méthode `normalize()` en une séquence

```
normalize(request, resolved)
        │
        ▼
  tempfile.TemporaryDirectory()           ← fichiers éphémères
        │
        ├─ écrit resolved.data →  src.{png|mp4}
        │
        ├─ si image  → _render_image_to_clip(src, out, duration_ms)
        └─ si clip   → _reencode_clip(src, out, duration_ms)
                             │
                             ▼
                        out.mp4 (1080x1920, durée exacte)
                             │
                             ▼
                    storage.save(key, out.read_bytes())
                             │
                             ▼
                   VisualAsset(path=<chemin persisté>, ...)
```

Le dossier temporaire est nettoyé automatiquement à la sortie du
`with`, et seul le fichier persisté dans `Storage` survit.

---

## 7. Étape 4 — `VisualTool` : le chef d'orchestre

**Fichier** : `app/tools/visual_tool.py`

C'est un **thin wrapper** au sens strict : il câble planner →
providers → normalizer et renvoie un nouvel état.

### 7.1 Le flux complet `run()`

```
VisualTool.run(state)
        │
        │  (résolution paresseuse des dépendances — pas d'IO au __init__)
        ▼
  settings  = self._settings  or get_settings()
  planner   = self._planner   or VisualPlanner()
  providers = self._providers or build_providers(settings)
  storage   = self._storage   or get_storage()
  normalizer = VisualNormalizer(storage, state["job_id"])
        │
        ▼
  requests = planner.plan(state.script, state.audio_segments, state.audio_duration_ms)
        │
        ▼
  ┌──────────────────  pour chaque request  ──────────────────┐
  │                                                            │
  │   resolved = _resolve_with_fallback(request, providers,   │
  │                                     settings)             │
  │                                                            │
  │   asset    = normalizer.normalize(request, resolved)      │
  │                                                            │
  │   log.info("visual.asset.ready", section, provider, ...)  │
  │                                                            │
  │   assets.append(asset)                                    │
  └────────────────────────────────────────────────────────────┘
        │
        ▼
  return {**state, "visual_assets": [a.as_dict() for a in assets]}
```

Points importants :

- **État immuable en entrée** : on renvoie `{**state, ...}` (copie
  peu profonde enrichie). Testé par `test_visual_tool_does_not_mutate_input_state`.
- **Dépendances injectables** : planner, providers, storage, settings
  sont tous paramétrables — c'est ce qui permet les tests unitaires
  offline avec des fake providers et un fake normalizer.
- **Résolution paresseuse** : rien ne se charge au constructeur → pas
  de connexion réseau, pas d'accès disque au simple `VisualTool()`.

### 7.2 La chaîne de fallback : `_resolve_with_fallback`

```
section → _primary_provider_name(section, settings)
                       │
             (stratégie)│
                       ▼
         "section_map" → settings.visual_provider_map[section]
         "pexels"      → "pexels"
         "nano_banana" → "nano_banana"
         "fallback"    → "fallback"
                       │
                       ▼
              chain = [primary, "fallback"]
                       │
                       ▼
  ┌──── pour chaque provider de la chain ────┐
  │                                           │
  │   try:                                    │
  │     return provider.resolve(request) ────┼──→  ✅ ResolvedAsset
  │   except VisualProviderError as e:        │
  │     log.warning(...)                      │
  │     continue                              │
  │                                           │
  └───────────────────────────────────────────┘
                       │
                       ▼
  (inatteignable en pratique : fallback ne lève jamais)
```

Visualisation de la stratégie par défaut (`section_map`) :

```
        section         primary         fallback
        ┌──────┐      ┌──────────┐      ┌──────────┐
 hook → │ hook │  →   │nano_banana│ →   │ fallback │
        └──────┘      └──────────┘      └──────────┘
        ┌──────┐      ┌──────────┐      ┌──────────┐
 body → │ body │  →   │  pexels  │  →   │ fallback │
        └──────┘      └──────────┘      └──────────┘
        ┌──────┐      ┌──────────┐      ┌──────────┐
  cta → │ cta  │  →   │nano_banana│ →   │ fallback │
        └──────┘      └──────────┘      └──────────┘
```

Le `hook` et le `cta` tapent sur de l'IA générative (image de marque
forte, précise), le `body` sur du stock vidéo (du mouvement qui tient
l'attention). Le fallback est **toujours** en fin de chaîne.

---

## 8. Configuration (`app/core/config.py`)

```python
class Settings(BaseSettings):
    ...
    # Visuals
    pexels_api_key: str = ""
    visual_provider: str = "section_map"    # ou "pexels" | "nano_banana" | "fallback"
    visual_provider_map: dict[str, str] = {
        "hook": "nano_banana",
        "body": "pexels",
        "cta":  "nano_banana",
    }
    visual_ai_model: str = "gemini-3.1-flash-image"
    google_api_key: str = ""
    nano_banana_api_key: str = ""
    nano_banana_model: str = ""
```

Mapping des variables d'environnement (via `pydantic-settings`) :

```
.env                              Settings attribute
─────────────────────────────     ──────────────────────────
PEXELS_API_KEY=...              → pexels_api_key
NANO_BANANA_API_KEY=...         → nano_banana_api_key
NANO_BANANA_MODEL=...           → nano_banana_model
GOOGLE_API_KEY=...              → google_api_key       (fallback)
VISUAL_PROVIDER=section_map     → visual_provider
```

**Aucun credential → aucun crash** : le provider concerné est
silencieusement désactivé, `fallback` prend le relais.

---

## 9. Un exemple complet end-to-end

Basé sur `examples/visual_tool_example.py` avec :

```python
script = {
    "title": "Why honey never spoils",
    "hook":  "Did you know honey lasts forever?",
    "body":  "Honey has very low water content and high acidity.",
    "cta":   "Follow for more food facts!",
}
audio_segments = [
    {"section":"hook","chunk_index":0,"text":"...","duration_ms":2000},
    {"section":"body","chunk_index":0,"text":"Honey low water.","duration_ms":2500},
    {"section":"body","chunk_index":1,"text":"High acidity.","duration_ms":2500},
    {"section":"cta", "chunk_index":0,"text":"...","duration_ms":1500},
]
```

Déroulé visuel :

```
┌─────────────────────────── ENTRÉE ───────────────────────────┐
│ script + audio_segments                                      │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌───────────────────────  VisualPlanner  ─────────────────────┐
│                                                              │
│  [ hook#0  0 → 2000ms ]   prompt="Bold vertical 9:16 ..."    │
│  [ body#0  2000 → 4500 ]  query="Honey low water"            │
│  [ body#1  4500 → 7000 ]  query="High acidity"               │
│  [ cta#0   7000 → 8500 ]  prompt="Clean 9:16 CTA still..."   │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌───────────── Provider chain (section_map) ──────────────────┐
│  hook#0 →  nano_banana  →  PNG bytes        (image)          │
│  body#0 →  pexels       →  .mp4 bytes       (clip)           │
│  body#1 →  pexels       →  .mp4 bytes       (clip)           │
│  cta#0  →  nano_banana  →  PNG bytes        (image)          │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌────────────────── VisualNormalizer (ffmpeg) ─────────────────┐
│                                                              │
│  image → -loop 1 + scale/crop + -t 2.000  → hook_00.mp4      │
│  clip  →  scale/crop          + -t 2.500  → body_00.mp4      │
│  clip  →  scale/crop          + -t 2.500  → body_01.mp4      │
│  image → -loop 1 + scale/crop + -t 1.500  → cta_00.mp4       │
│                                                              │
│  → persistés dans  Storage: demo/visuals/*.mp4               │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌───────────────────────── SORTIE ─────────────────────────────┐
│ state["visual_assets"] = [                                   │
│   {section:"hook", chunk_index:0, provider:"nano_banana",    │
│    path:".../demo/visuals/hook_00.mp4",                      │
│    start_ms:0, end_ms:2000, duration_ms:2000,                │
│    width:1080, height:1920, asset_type:"image", ...},        │
│   {section:"body", chunk_index:0, provider:"pexels", ...},   │
│   {section:"body", chunk_index:1, provider:"pexels", ...},   │
│   {section:"cta",  chunk_index:0, provider:"nano_banana",...}│
│ ]                                                            │
└──────────────────────────────────────────────────────────────┘
```

Sortie console attendue :

```
Active providers: ['fallback', 'nano_banana', 'pexels']
Rendered 4 visual assets:
  [hook#0] nano_banana  2000ms  .../demo/visuals/hook_00.mp4
  [body#0] pexels       2500ms  .../demo/visuals/body_00.mp4
  [body#1] pexels       2500ms  .../demo/visuals/body_01.mp4
  [cta#0 ] nano_banana  1500ms  .../demo/visuals/cta_00.mp4
```

---

## 10. Les invariants à retenir

1. **Le pipeline ne plante jamais sur les visuels**.
   La chaîne se termine toujours par `fallback`, qui est
   offline et sans dépendance.
2. **Chaque slot produit exactement un fichier** `1080×1920 .mp4`
   de la durée attendue.
3. **Les clés de storage sont déterministes** (`<section>_<idx:02d>.mp4`)
   → re-runs idempotents.
4. **Les prompts et queries sont déterministes** (pas d'appel LLM
   dans le planner) → mêmes entrées = même plan.
5. **`VisualTool.run(state)` ne mute pas `state`** — il renvoie une
   copie enrichie.
6. **Les dépendances sont injectables** → tests offline rapides
   possibles avec des fake providers et un fake normalizer.

---

## 11. Tests de référence (`tests/test_visual.py`)

Pour comprendre la spec en action, lire dans cet ordre :

| Test | Ce qu'il prouve |
|---|---|
| `test_planner_uses_audio_segments_for_timing` | chaînage correct des `start_ms`/`end_ms` |
| `test_planner_equal_splits_when_segments_missing` | chemin de secours équitable |
| `test_planner_prompts_are_deterministic` | zéro aléatoire dans les prompts |
| `test_pexels_provider_happy_path` | format de réponse Pexels + choix du fichier |
| `test_nano_banana_provider_uses_injected_client` | seam de test injectable |
| `test_fallback_provider_always_returns_image` | le PNG de secours est un vrai PNG |
| `test_normalizer_renders_still_image_to_clip` | l'intégration ffmpeg marche de bout en bout |
| `test_visual_tool_falls_back_when_primary_fails` | la chaîne de fallback route bien |
| `test_visual_tool_does_not_mutate_input_state` | immutabilité du state |

Ces neuf tests couvrent l'intégralité des contrats décrits ci-dessus.
