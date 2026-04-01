# Dictionary

Este repo contiene:

- scripts en Python para extraer y reconstruir los diccionarios UniLex
- una app FastAPI en `dictionary/`
- bases SQLite generadas en `site/data/`

## Correr FastAPI localmente

```bash
cd /home/tin/lab/UniLex
uv lock
uv run fastapi dev --host 127.0.0.1 --port 8001
```

O con Make:

```bash
make lock-fastapi
make serve
```

Después abrí `http://127.0.0.1:8001`.

## Desplegar en FastAPI Cloud

La app expone `dictionary.app:app`, así que FastAPI Cloud debería detectarla sola.

```bash
cd /home/tin/lab/UniLex
fastapi deploy
```

El archivo `uv.lock` se genera con `uv lock` y conviene incluirlo para dejar
las dependencias pinneadas.

## Datos

Las bases SQLite y los JSON generados viven en `site/data/`. La app FastAPI
las abre directamente desde ahí, así que pueden viajar con el repo completo
al deploy.
