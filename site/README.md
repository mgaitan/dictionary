# Sitio PHP del diccionario

Este directorio ahora contiene una app mínima en PHP que consulta una base SQLite
generada con scripts en Python. La idea es que la parte web sea fácil de subir a
hosting compartido, mientras que la generación de datos siga en Python.

## Flujo recomendado

1. Generar el JSON limpio:

```bash
uv run /home/tin/lab/UniLex/tools/build_site_dictionary.py
```

2. Importarlo a SQLite:

```bash
uv run /home/tin/lab/UniLex/tools/build_site_sqlite.py
```

Eso genera `data/dictionary.sqlite`.

3. Servir la app localmente con PHP:

```bash
cd /home/tin/lab/UniLex/site
php -S 127.0.0.1:8000
```

Después abrí `http://127.0.0.1:8000`.

## Atajos con Make

Desde `/home/tin/lab/UniLex` también podés usar:

```bash
make build-data
make serve
```

## Archivos importantes

- `index.php`: buscador web server-side
- `styles.css`: estilos del sitio
- `data/dictionary.sqlite`: base lista para subir al hosting
- `data/dictionary-indexed.json`: dataset limpio intermedio
- `../tools/build_site_dictionary.py`: limpia y reagrupa el JSON extraído
- `../tools/build_site_sqlite.py`: convierte el JSON limpio a SQLite
