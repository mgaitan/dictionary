# María Moliner — sesión de integración

Actualizado: 2026-10-28. Responsable: Pedro (sitio, extracción compartida). EPUB: Juan.

## Pedido
1. Nueva pestaña «Uso del español (María Moliner)», buscable, con base independiente libSQL.
2. EPUB saneado: preliminares, introducción y notas del PDF; definiciones del instalable.
3. Mantener este registro y separar el trabajo del EPUB para otro agente.

## Fuentes locales
- `Diccionario de uso del español Maria Moliner (3ª-ED.)/Diccionario de uso del español - Maria Moliner (3ª ED.)/Setup/`.
- Además de instaladores, Setup contiene `index/`: índices Lucene antiguos ya extraídos; `todo/_7kh.cfs` (137 MB), `lemas/_7jy.cfs` (40 MB), etc. Investigar campos almacenados sin ejecutar instaladores.
- `diccionario_maria_moliner_1996.pdf`: 1512 páginas, imágenes con OCR. Metadatos Internet Archive. Las primeras páginas muestran ©1966: verificar edición real; no asumir 1996 por el nombre.
- `/tmp/moliner-front.txt`: OCR preliminar de páginas 1–65 (muy ruidoso).

## Proyecto
- FastAPI, plantillas Jinja, SQLite local por diccionario (`de-es`, `es-de`). Registro en `dictionary/search.py`; conexión en `open_database`; rutas en `dictionary/app.py`.
- Datos previos en `site/data/*.sqlite`; no modificarlos.
- No hay AGENTS.md del proyecto ni herramientas codebase-memory disponibles; descubrimiento con rg y lecturas.
- Skill aplicada: ponytail (cambio mínimo completo, pruebas de lógica nueva).

## Plan / pendientes
- [x] Extraer artículos de los campos almacenados de Lucene, verificar cobertura y formato.
- [x] Exportación compartida reproducible para sitio y EPUB (`chat.md`).
- [x] Base Moliner independiente libSQL; configuración y consulta web, autocompletado y enlaces.
- [x] Pruebas de extracción y rutas; comprobar diccionarios existentes.
- [ ] EPUB: a cargo de Juan; estado propio en `docs/moliner-epub-session.md`.

## Coordinación
El agente EPUB debe mantener `docs/moliner-epub-session.md`, y trabajar en su generador/artefactos propios. El principal mantiene este archivo y la extracción compartida. No editar simultáneamente archivos comunes (README, Makefile, configuración, search.py).

## Estado
**Tarea 1 terminada localmente.** La app está disponible en
`http://127.0.0.1:8001/?dict=moliner` (proceso uvicorn iniciado por Pedro).
Base independiente `site/data/moliner.libsql`, driver libsql 0.1.11.
26 pruebas de sitio/extracción/regresión pasan; vista de escritorio y móvil comprobadas.
No se publicaron cambios ni se ejecutaron instaladores. EPUB continúa con Juan.

## Actualización Pedro — 22:41 ART
- Usuario asignó tarea EPUB al otro agente (Juan), coordinación mediante `chat.md`.
- Descifrado `lemas/_7jy.cfs`: confirmado XML original completo y puntuado. Campos almacenados: idEntrada, lema, idLema, xmlLema, xmlEntrada.
- Contrato JSONL documentado en chat.md, destino `site/data/moliner-articles.jsonl`.
- libsql 0.1.11 agregado a pyproject/uv.lock. Turso CLI sin sesión: preparar uso libSQL local y configuración remota, sin crear cuenta/base remota.
- No usar texto del índice todo para definiciones: elimina puntuación.
- Datos de investigación en `.cache/moliner/`; `/tmp` alcanzó cuota al escribir >100 MB.

## Actualización Pedro — sitio y datos
- Exportación original lista: 88.112 XML válidos, IDs únicos. 110.401 destinos DUE (lemas + expresiones); todas las 12.946 REMISION tienen destino en el corpus.
- Base `site/data/moliner.libsql` generada con driver libsql real: 88.112 entradas, 164.056 acepciones, 208.343 términos y 110.401 IDs XML. Integridad y claves foráneas verificadas.
- Pestaña Moliner integrada y comprobada con TestClient: inicio, consulta `casa`, autocompletado `abac`. Consulta de-es también responde.
- Renderizador XML escapa texto y genera sólo etiquetas/atributos controlados; conserva jerarquía, ejemplos y remisiones.
- Fuentes originales detede1/detede2 recuperadas del instalable; preparando integración para griego.
- Reparada instalación local corrupta de typing-extensions 4.15.0 mediante reinstalación exacta; sin cambiar versión/dependencias del proyecto.
- Faltan: pruebas específicas, documentación/comandos, validación de libSQL remoto con servidor local y revisión visual final. EPUB sigue a cargo de Juan.

## Cierre Pedro — tarea 1
- Datos finales: 88.112 entradas, 164.056 acepciones, **208.347 términos**, 110.401 destinos XML. La diferencia de cuatro términos frente al primer build corresponde a conservar sufijos posteriores a superíndices de homónimos (ej. `actor¹, -a`).
- Extracción reproducible: `tools/extract_moliner.py`; base: `tools/build_moliner_database.py`; ejecutar `make build-moliner` para XML + fuentes + base. `make serve` ahora usa la ruta real del repositorio.
- Definiciones/etimologías/notas/ejemplos/expresiones conservados desde XML original; remisiones DUE navegables. Enlaces APEX a apéndices conservan texto, sin navegación web a esos apéndices (Juan los incluye en EPUB).
- Fuentes detede1/detede2 originales extraídas; detede1 integrada y cargada en navegador para el griego.
- Verificación final: 26 pruebas pasan (`tests/test_moliner.py` + `tests/test_render_gloss_html.py`); lint de archivos nuevos y `git diff --check` sin errores. Una advertencia de deprecación de pytest proviene de anyio existente.
- Base completa: integrity_check y foreign_key_check OK. Consultas reales `a 1`, `abacá`, `casa`, `casa de campo`, `hacer`, `ñandú`, `zurrón`, `zóster`, búsqueda vacía y sin resultados; regresión de-es/es-de OK. Tiempos locales observados ~0,07–0,13 s en esas búsquedas.
- Navegador: escritorio y ancho 390 px, sin desborde horizontal; comprobada carga de fuente griega. Capturas en `.cache/moliner/`.
- Configuración remota documentada y testeado el encaminamiento de URL/token sin requerir archivo local. **Sin prueba de red real contra Turso Cloud**: CLI sin sesión; `turso dev` tampoco pudo correr porque no está instalado sqld. No hace falta para libSQL local.
- Documentación: `docs/moliner.md`, README y este registro. Instaladores, PDF, JSONL e intermedios ignorados por git; base libSQL y fuentes quedan disponibles para versionar. No se hicieron commits ni despliegues.
- Handoff EPUB: `site/data/moliner-articles.jsonl` conserva original; 1.678 valores lemma_xml son fragmentos con variantes posteriores a LEMA; usar entry_xml como documento o envolver el fragmento. Detalles y fuentes comunicados en chat.md. No modificar archivos de Juan.

## Seguimiento Pedro — inglés de producción y configuración .env
- El usuario señaló que producción tenía inglés. Verificado `/healthz` de https://dictionary.fastapicloud.dev/: de-es, es-de, en-es, es-en.
- El checkout inicial estaba un commit atrás. `git fetch origin` encontró `4ef16fd` (#22); main avanzó por fast-forward a ese commit, preservando el trabajo Moliner. Resueltos conflictos en registro, README, Makefile e ignores. Ahora están las cinco pestañas y las cuatro bases bilingües de producción, incluida la persistencia de selección por cookie.
- Creado `.env` local vacío y `.env.example` versionable; dotenv se carga al importar dictionary, antes de leer configuración. Declarada dependencia python-dotenv. Variables: MOLINER_DATABASE_URL y MOLINER_AUTH_TOKEN; URL vacía mantiene libSQL local. El entorno del proceso tiene prioridad y hay que reiniciar tras editar .env. `.env` ignorado por git.
- Tamaño exacto de Moliner: 101.412.864 bytes = 101,4 MB decimales = 96,71 MiB.
- 32 pruebas pasan, incluyendo las nuevas pruebas traídas de producción. Comprobadas búsquedas reales en los cinco diccionarios y healthz con cinco IDs. No se desplegó ni se importó la base a Turso Cloud.

## Pedro — importación remota solicitada
- Usuario completó .env y autorizó importar base a Turso y subir variables con FastAPI CLI.
- Conexión remota verificada: destino vacío. No hay login de Turso CLI; se utiliza el token de la base para importación SQL sobre HTTP.
- Agregado `tools/upload_moliner.py`: inserciones agrupadas por tamaño (~1 MB SQL), conserva rowids para reintentos idempotentes, crea índices después de datos, compara contadores/rowids/longitudes por columna y valida integridad/FK. Reanudación con `--resume` sólo si coincide SHA-256 del origen.
- 3 pruebas del importador HTTP pasan: fidelidad de valores Unicode/comillas/NULL/BLOB y rowids, reintentos sin duplicar y errores SQL dentro de respuestas HTTP 200.
- Importación en curso; log en `.cache/moliner/upload.log` (sin credenciales).
- FastAPI CLI sin sesión: se pidió al usuario iniciar `uv run fastapi login` mientras avanza la importación. Variables Cloud todavía no subidas.

## Pedro — importación Turso completada
- Base remota cargada en **363,2 s (6 min 3 s), 135 solicitudes HTTP**. Destino verificado vacío antes de comenzar; sin borrados.
- Verificados en remoto: metadata 8 filas, entries 88.112, senses 164.056, search_terms 208.347, articles 88.112, xml_ids 110.401. Coinciden con local contadores, sumas/límites de rowid y sumas de longitudes de cada columna.
- Índices creados después del bulk; foreign_key_check vacío e integrity_check = ok.
- Validación de lectura con driver libsql real y búsqueda FastAPI contra Turso en curso.
- Preparado `.cache/moliner/push_cloud_env.py`: identifica inequívocamente app `dictionary`, la vincula localmente y ejecuta los comandos FastAPI CLI env set/list en memoria, sin exponer valores en argv ni salida; token marcado secreto.
- Pendiente: sesión vigente de FastAPI CLI. Intento de configuración devuelve que hace falta `uv run fastapi login`. No se configuraron variables Cloud todavía; se pidió login al usuario mediante pregunta asíncrona. No se desplegó código.

## Pedro — variables FastAPI Cloud configuradas
- Usuario confirmó autenticación; sesión vigente utilizada.
- Vinculado checkout local a la app existente `dictionary` usando utilidades de FastAPI CLI (`.fastapicloud/cloud.json`, ignorado por git).
- Ejecutados mediante FastAPI CLI: env set MOLINER_DATABASE_URL y env set MOLINER_AUTH_TOKEN --secret. Ambos comandos finalizaron correctamente; env list confirmó los dos nombres. Valores tomados de .env sin mostrarlos ni pasarlos por argumentos del sistema.
- Validación final contra Turso con el driver libsql de la app: contadores correctos para las cinco tablas de datos; búsqueda FastAPI `abaca` devuelve el artículo original y no incluye token en HTML. Validación completa de lectura/búsqueda: 6,7 s.
- Pedido de importación + subida de envvars completado. Código Moliner todavía sin commit ni despliegue; producción mostrará la pestaña cuando se despliegue ese código.

## Pedro — preparación de commit y despliegue
- Usuario autorizó commitear todo lo relevante y desplegar.
- Suite completa: **44 pruebas pasan**, incluida extracción/renderizado web, subida a Turso, regresiones bilingües y 9 pruebas del generador EPUB entregado por Juan.
- Se incluyen en el commit sitio, importadores, generador EPUB entregado, pruebas, fuentes tipográficas, plantilla .env, documentación y registros de coordinación.
- Base Moliner local (96,7 MiB) ahora ignorada por git: producción ya consulta Turso. Se conservan localmente base, JSONL, EPUB y fuentes originales, sin incluirlos en el commit/despliegue.
- Revisión del empaquetado real de FastAPI CLI: 45 archivos / 117,45 MiB sin comprimir, principalmente las cuatro bases bilingües existentes. Credenciales, PDF, instaladores, cachés, EPUB y base local Moliner excluidos. Fuentes necesarias y cuatro bases bilingües incluidas.
- Sesión FastAPI CLI vigente y app dictionary vinculada. Commit/despliegue en curso; actualizar con el resultado de producción.

## Pedro — corrección de alcance solicitada por el usuario
- El usuario aclaró que el commit/despliegue debe contener sólo el trabajo de Pedro, no el de Juan.
- Error reconocido: el commit local bc32c8f había incluido 5 archivos del EPUB. No se había pusheado. Cancelado el despliegue; FastAPI Cloud confirmó estado upload_cancelled, por lo que producción conservó la versión anterior.
- Deshecho únicamente ese commit local con reset --soft, preservando todos los archivos. Fuera del índice: tools/build_moliner_epub.py, tools/moliner_frontmatter.json, tests/test_moliner_epub.py, docs/moliner-epub-session.md y docs/moliner-frontmatter-notes.md. Sus hashes se verifican sin cambios; quedan para Juan.
- Nuevo commit: sólo sitio, extracción compartida, base/importador Turso, pruebas de Pedro, fuentes necesarias, configuración y documentación de Pedro.
- Agregada .fastapicloudignore para excluir tools/tests/docs/registros del paquete runtime; el .epub, PDF, instaladores, datos generados y credenciales ya estaban excluidos.

## Pedro — cierre de commit y despliegue de tarea 1
- Commit corregido: **2b8e7a4**, `Add María Moliner search backed by Turso`. Sólo trabajo de Pedro; los cinco archivos de Juan continúan intactos y sin versionar. Verificados hashes sin cambios.
- **35 pruebas pasan** para sitio, extracción compartida, importación HTTP y regresiones bilingües.
- Despliegue FastAPI Cloud **success**: `50a9b958-87f9-4ab6-a7f8-cdf921f3f9c5`, iniciado 2026-10-29 02:33 UTC (2026-10-28 23:33 ART).
- Producción: https://dictionary.fastapicloud.dev/?dict=moliner . Confirmadas 88.112 entradas y 164.056 acepciones en la portada Moliner; búsqueda real `abaca` devuelve definición original desde Turso.
- Comprobadas búsquedas reales de-es Macher, es-de mujer, en-es house, es-en casa y moliner abaca; healthz muestra cinco diccionarios, autocompletado abac contiene abacá, fuente griega responde con longitud correcta.
- El paquete runtime excluye todas las herramientas, pruebas, documentación, registros y artefactos locales; no contiene el EPUB ni sus archivos de generación de Juan. No contiene .env, PDF, instaladores ni base local Moliner.
- El primer intento incorrecto permanece cancelado (`upload_cancelled`) y el commit incorrecto bc32c8f no está en la historia de main. No hubo push a GitHub; despliegue directo con FastAPI CLI desde commit local autorizado.
