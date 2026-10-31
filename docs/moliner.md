# María Moliner: extracción e integración

La tercera pestaña consulta el Diccionario de uso del español de María Moliner
(DUE 3.0 / 3.ª edición) en una base **SQLite independiente** de UniLex.

## Fuentes y procedencia

El paquete local contiene `Setup/index/lemas/_7jy.cfs`, un índice Lucene 2.2
cifrado, con XML completo en sus campos almacenados. El lector `CryptDirectory`
y el algoritmo `AlgDUE` del `due.jar` incluido permiten identificar su formato:

- ocho bytes iniciales: tamaño real, entero big endian;
- bloques AES-128-ECB de 1024 bytes, cada uno con un byte de padding;
- contenido descifrado: archivo compuesto Lucene con `.fnm`, `.fdx` y `.fdt`;
- campos almacenados comprimidos con zlib: `idEntrada`, `idLema`, `lema`,
  `xmlLema`, `xmlEntrada`.

`tools/extract_moliner.py` implementa esa lectura con Python estándar y OpenSSL.
Valida límites de documentos, padding y codificación. No ejecuta los instaladores
ni el JAR. Se consultó el [formato oficial de Lucene](https://lucene.apache.org/core/3_0_3/fileformats.html)
para los campos almacenados y archivos compuestos.

El índice `todo` contiene texto preparado para búsqueda que pierde puntuación;
no se usa como fuente de las definiciones.

El PDF `diccionario_maria_moliner_1996.pdf` es una fuente diferente: sus páginas
legales indican ©1966. Lo utiliza el generador EPUB para los preliminares y
notas en un trabajo separado. Las definiciones del sitio proceden exclusivamente
del instalable de la tercera edición.

## Exportación compartida

`site/data/moliner-articles.jsonl`, UTF-8, una línea por documento:

```json
{"id":"1","lemma_id":"1","headword":"a 1","lemma_xml":"<LEMA id=\"DUE_1\">…</LEMA>","entry_xml":"<ENTRADA id-entrada=\"1\">…</ENTRADA>"}
```

Se conservan todos los XML originales, incluidos notas, expresiones, ejemplos,
atributos tipográficos, identificadores y referencias. El JSONL es regenerable
y no se versiona. El agente del EPUB puede consumirlo sin depender de la base web.

Comandos desde la raíz del proyecto:

```bash
uv run python tools/extract_moliner.py --source '/ruta/Setup/index/lemas/_7jy.cfs'
uv run python tools/build_moliner_database.py
```

Desde el repositorio, `make build-moliner` usa las rutas del paquete recibido y
extrae además `detede1.ttf` y `detede2.ttf` del instalador Linux. Esas fuentes
son necesarias para los fragmentos griegos codificados con `FUENTE face="detede"`;
el sitio utiliza detede1, como las hojas XSL originales. La extracción de fuentes
se puede invocar con `--fonts-from /ruta/DUE-3.0-linux-installer.bin`.

## Base SQLite

`tools/build_moliner_database.py` usa `sqlite3` para crear
`site/data/moliner.sqlite`, sin modificar las bases existentes. Contiene:

| Tabla | Contenido |
| --- | --- |
| `entries` | 88.112 entradas e identificación original |
| `senses` | 164.056 acepciones, texto sin marcado para interoperabilidad |
| `search_terms` | 208.347 términos: lemas, variantes y expresiones |
| `articles` | XML original de cada entrada |
| `xml_ids` | 110.401 destinos de remisiones: lemas y expresiones |
| `metadata` | procedencia, contadores y SHA-256 del JSONL utilizado |

La base está versionada y se incluye en el despliegue para consultas locales.

Los importadores escriben un archivo temporal y reemplazan el destino sólo al
terminar. La base se verifica con `integrity_check` y `foreign_key_check`.

La búsqueda reutiliza el ranking y la paginación de UniLex: lema exacto,
coincidencia exacta en variantes/expresiones, prefijo y contenido del término.
Se normalizan tildes y mayúsculas. También se indexan expresiones abreviadas,
por ejemplo `c. de campo` y `casa de campo`. No es una búsqueda dentro del texto
de las definiciones.

El renderizador transforma el XML en HTML escapado; no inserta etiquetas ni
atributos arbitrarios del documento. Conserva texto y jerarquía completa,
incluidas subacepciones. Las 12.946 remisiones `REMISION` tienen destino en
el corpus y enlazan a la entrada y al fragmento correspondiente. Los `LINK`
a apéndices gramaticales conservan su texto; esos apéndices no forman parte
del buscador web.

## Configuración

La aplicación utiliza SQLite local. Para indicar otra ubicación:

```bash
export MOLINER_DATABASE_PATH=/ruta/moliner.sqlite
```

Las antiguas variables de conexión a Turso ya no afectan a la aplicación.

## Verificación

```bash
uv run --with pytest python -m pytest -q tests/test_moliner.py tests/test_render_gloss_html.py
make serve
```

Las pruebas cubren extracción de un archivo compuesto, preservación de XML,
importación con SQLite, búsqueda sin tildes, expresiones, remisiones, autocompletado,
escape de contenido y recuperación ante archivos truncados o importaciones fallidas.
La base completa se comprobó además con búsquedas reales de principio a fin
del alfabeto. Los instaladores, PDF e intermedios se conservan localmente y están
ignorados por git.
