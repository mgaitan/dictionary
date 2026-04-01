# Sitio PHP del diccionario

Este directorio contiene una app mínima en PHP que consulta bases SQLite
generadas con scripts en Python. Hoy soporta las dos direcciones incluidas
en UniLex:

- `de-es`: alemán -> español
- `es-de`: español -> alemán

La idea es que la parte web sea fácil de subir a hosting compartido, mientras
que la generación de datos siga en Python.

## Flujo recomendado

Desde `/home/tin/lab/UniLex`:

```bash
make build-data
make serve
```

Después abrí `http://127.0.0.1:8000`.

## Targets útiles

```bash
make build-data-de-es
make build-data-es-de
make serve
make clean
```

Los aliases históricos siguen existiendo y apuntan al `de-es`:

```bash
make build-index
make build-raw
make build-json
make build-sqlite
```

## Archivos importantes

- `index.php`: buscador web server-side con selector de dirección
- `styles.css`: estilos del sitio
- `data/dictionary.sqlite`: base `de-es` lista para subir al hosting
- `data/es-de-dictionary.sqlite`: base `es-de` lista para subir al hosting
- `../tools/analyze_slagro.py`: exporta el índice auténtico desde `IDO/LEO`
- `../tools/build_raw_dictionary.py`: reconstruye el JSON crudo desde `IDO/LEO` y `aclexman.dll`
- `../tools/build_site_dictionary.py`: limpia y reagrupa el JSON extraído
- `../tools/build_site_sqlite.py`: convierte el JSON limpio a SQLite

## Salidas generadas

`de-es`:

- `data/index.json`
- `data/dictionary.json`
- `data/dictionary-indexed.json`
- `data/dictionary.sqlite`

`es-de`:

- `data/es-de-index.json`
- `data/es-de-dictionary.json`
- `data/es-de-dictionary-indexed.json`
- `data/es-de-dictionary.sqlite`
