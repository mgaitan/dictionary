# Dictionary

Buscador web para diccionarios alemán-español e inglés-español en ambas
direcciones, reconstruidos a partir de aplicaciones antiguas.

La app publicada hoy corre con FastAPI y usa SQLite como base de consulta. La
generación de datos sigue en Python y se apoya en una pequeña pipeline de
ingeniería inversa para pasar de `IDO/LEO` a un formato web consultable.

## Qué hace el sitio

- permite buscar por palabra fuente en cuatro direcciones
- pagina resultados en el servidor
- resalta abreviaturas gramaticales, marcas semánticas y etiquetas
- trabaja directamente sobre cuatro bases SQLite incluidas en el proyecto

## Estructura

```text
dictionary/
  app.py                 FastAPI app y wiring de templates/estáticos
  search.py              lógica de búsqueda, normalización y render de glosas
  templates/index.html   interfaz HTML server-side
  static/styles.css      estilos

site/data/
  de-es-dictionary.sqlite alemán → español
  es-de-dictionary.sqlite español → alemán
  en-es-dictionary.sqlite inglés → español
  es-en-dictionary.sqlite español → inglés
  *.json                 artefactos intermedios locales, no versionados

tools/
  analyze_slagro.py      exporta índices auténticos desde IDO/LEO
  build_raw_dictionary.py genera diccionario crudo desde IDO/LEO + DLL
  build_site_dictionary.py limpia y agrupa entradas
  build_site_sqlite.py   genera SQLite para la web
  extract_msdict.py      inspecciona PDB MSDict y genera SQLite
```

## Cómo funciona

### 1. Build de datos

La web no lee `IDO` ni `LEO` directamente. Antes se genera una base SQLite por
dirección:

```mermaid
flowchart LR
    A[slagrods.ido / slagrods.leo] --> B[analyze_slagro.py]
    A --> C[build_raw_dictionary.py]
    B --> D[de-es-index.json]
    C --> E[de-es-dictionary.json]
    D --> F[build_site_dictionary.py]
    E --> F
    F --> G[de-es-dictionary-indexed.json]
    G --> H[build_site_sqlite.py]
    D --> H
    H --> I[de-es-dictionary.sqlite]
```

Para `es → de` se usa la misma pipeline sobre `slagrosd.IDO/LEO`. Los
diccionarios Oxford `en → es` y `es → en` se extraen directamente de sus PDB
MSDict:

```mermaid
flowchart LR
    A[EnglishSpanish.pdb] --> C[extract_msdict.py]
    B[SpanishEnglish.pdb] --> C
    C --> D[BER + DEFLATE ramificado]
    D --> E[SQLite]
```

### 2. Consulta web

La app FastAPI abre la SQLite correspondiente según el query param `dict`:

- `de-es`
- `es-de`
- `en-es`
- `es-en`

Después:

1. normaliza la búsqueda
2. consulta `search_terms`
3. rankea coincidencia exacta, luego prefijo y luego contenido
4. trae las acepciones desde `senses`
5. renderiza HTML con Jinja2

```mermaid
sequenceDiagram
    participant U as Usuario
    participant F as FastAPI
    participant S as SQLite

    U->>F: GET /?dict=de-es&q=machen&page=1
    F->>S: buscar entry_id en search_terms
    S-->>F: ids candidatos
    F->>S: traer entries + senses
    S-->>F: filas normalizadas
    F-->>U: HTML renderizado
```

## Detalle técnico FastAPI

La aplicación expone:

- entrypoint: `dictionary.app:app`
- ruta principal: `GET /`
- healthcheck: `GET /healthz`

El render es server-side, sin SPA ni frontend compilado. La UI sale desde
[`dictionary/templates/index.html`](dictionary/templates/index.html)
y usa helpers registrados en Jinja2 desde
[`dictionary/app.py`](dictionary/app.py).

La lógica de búsqueda está concentrada en
[`dictionary/search.py`](dictionary/search.py):

- `normalize_for_search()`: saca acentos y normaliza texto
- `search_entries()`: hace ranking y paginación
- `find_unresolved_index_entry()`: muestra fallback si el índice conoce un lema
  pero todavía no hay artículo reconstruido
- `render_gloss_html()`: colorea etiquetas, notas y abreviaturas

## Detalle técnico SQLite

Cada base tiene estas tablas principales:

- `entries`: una fila por lema agrupado
- `senses`: acepciones de cada lema
- `search_terms`: términos indexados para búsqueda
- `index_entries`: índice auténtico derivado del `IDO`, incluso si todavía no
  existe artículo decodificado
- `metadata`: contadores y origen del build

```mermaid
erDiagram
    entries ||--o{ senses : has
    entries ||--o{ search_terms : indexed_by
    index_entries {
        integer id
        text headword
        text normalized_headword
        integer leo_offset
        integer page_span
        integer has_decoded_entry
    }
    entries {
        integer id
        text headword
        text normalized_headword
        integer decoded_complete
    }
    senses {
        integer id
        integer entry_id
        integer sense_index
        text source
        text glosses_json
        text tags_json
    }
    search_terms {
        integer entry_id
        text term
        text normalized_term
        text kind
    }
```

## Comandos útiles

Regenerar todo:

```bash
make build-data
```

Solo alemán → español:

```bash
make build-data-de-es
```

Solo español → alemán:

```bash
make build-data-es-de
```

Solo los dos diccionarios PDB:

```bash
make build-pdb-data
```

Inspeccionar metadatos y algunas entradas sin generar una base:

```bash
uv run tools/extract_msdict.py EnglishSpanish.pdb --samples 5
```

Todas las tools son scripts PEP 723. No contienen rutas locales por defecto:
los inputs y outputs se pasan por CLI y por eso se pueden ejecutar desde
cualquier checkout. Cada script incluye ejemplos completos en su docstring y
en `--help`.

Correr local:

```bash
make lock-fastapi
make serve
```

## Deploy

FastAPI Cloud detecta la app desde `pyproject.toml`:

```toml
[tool.fastapi]
entrypoint = "dictionary.app:app"
```

El proyecto incluye `uv.lock`, por lo que las dependencias quedan pinneadas
también en deploy.

## Artefactos versionados

El repo publica las cuatro bases SQLite listas para consulta web.

- `site/data/de-es-dictionary.sqlite`
- `site/data/es-de-dictionary.sqlite`
- `site/data/en-es-dictionary.sqlite`
- `site/data/es-en-dictionary.sqlite`

Los JSON intermedios de extracción y limpieza siguen existiendo como parte del
pipeline, pero quedan ignorados en git y se regeneran localmente cuando hace
falta. Los PDB y APK originales son inputs locales propietarios y también están
excluidos del repositorio.

## Formatos y palabras clave

Este repositorio incluye investigación reproducible para **reverse engineering
de MSDict Palm PDB**, BER de longitud definida y **branched raw DEFLATE** con
continuaciones alineadas a nivel de bits. También documenta la extracción del
formato UniLex `IDO/LEO` mediante un codebook recuperado de una DLL.

Palabras clave: `MSDict`, `Palm PDB`, `PDB dictionary decompiler`, `BER parser`,
`branched DEFLATE`, `UniLex`, `IDO`, `LEO`, `dictionary reverse engineering`.

## Documentación adicional

- [Ingeniería inversa del formato](./docs/ingenieria-inversa.md)
