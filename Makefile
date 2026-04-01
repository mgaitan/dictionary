PYTHON ?= uv run

ROOT_DIR := /home/tin/lab/UniLex
SITE_DIR := $(ROOT_DIR)/site
DATA_DIR := $(SITE_DIR)/data
TOOLS_DIR := $(ROOT_DIR)/tools
SOURCE_DIR := $(ROOT_DIR)/UniLex - Brandstetter Slaby/SlaGro
DLL_PATH := $(ROOT_DIR)/UniLex - Brandstetter Slaby/program/aclexman.dll

DE_ES_IDO := $(SOURCE_DIR)/slagrods.ido
DE_ES_LEO := $(SOURCE_DIR)/slagrods.leo
DE_ES_INDEX := $(DATA_DIR)/index.json
DE_ES_RAW := $(DATA_DIR)/dictionary.json
DE_ES_JSON := $(DATA_DIR)/dictionary-indexed.json
DE_ES_SQLITE := $(DATA_DIR)/dictionary.sqlite

ES_DE_IDO := $(SOURCE_DIR)/slagrosd.IDO
ES_DE_LEO := $(SOURCE_DIR)/slagrosd.LEO
ES_DE_INDEX := $(DATA_DIR)/es-de-index.json
ES_DE_RAW := $(DATA_DIR)/es-de-dictionary.json
ES_DE_JSON := $(DATA_DIR)/es-de-dictionary-indexed.json
ES_DE_SQLITE := $(DATA_DIR)/es-de-dictionary.sqlite

.PHONY: \
	all \
	build-index build-raw build-json build-sqlite build-data \
	build-index-de-es build-raw-de-es build-json-de-es build-sqlite-de-es build-data-de-es \
	build-index-es-de build-raw-es-de build-json-es-de build-sqlite-es-de build-data-es-de \
	serve lock-fastapi clean

all: build-data

build-index: build-index-de-es
build-raw: build-raw-de-es
build-json: build-json-de-es
build-sqlite: build-sqlite-de-es
build-data: build-data-de-es build-data-es-de

build-index-de-es:
	$(PYTHON) $(TOOLS_DIR)/analyze_slagro.py export-index --ido "$(DE_ES_IDO)" --leo "$(DE_ES_LEO)" --output "$(DE_ES_INDEX)"

build-raw-de-es:
	$(PYTHON) $(TOOLS_DIR)/build_raw_dictionary.py --ido "$(DE_ES_IDO)" --leo "$(DE_ES_LEO)" --dll "$(DLL_PATH)" --output "$(DE_ES_RAW)"

build-json-de-es:
	$(PYTHON) $(TOOLS_DIR)/build_site_dictionary.py --raw-dictionary "$(DE_ES_RAW)" --index "$(DE_ES_INDEX)" --output "$(DE_ES_JSON)"

build-sqlite-de-es:
	$(PYTHON) $(TOOLS_DIR)/build_site_sqlite.py --json "$(DE_ES_JSON)" --index "$(DE_ES_INDEX)" --sqlite "$(DE_ES_SQLITE)"

build-data-de-es: build-index-de-es build-raw-de-es build-json-de-es build-sqlite-de-es

build-index-es-de:
	$(PYTHON) $(TOOLS_DIR)/analyze_slagro.py export-index --ido "$(ES_DE_IDO)" --leo "$(ES_DE_LEO)" --record-type none --output "$(ES_DE_INDEX)"

build-raw-es-de:
	$(PYTHON) $(TOOLS_DIR)/build_raw_dictionary.py --ido "$(ES_DE_IDO)" --leo "$(ES_DE_LEO)" --dll "$(DLL_PATH)" --record-type none --output "$(ES_DE_RAW)"

build-json-es-de:
	$(PYTHON) $(TOOLS_DIR)/build_site_dictionary.py --raw-dictionary "$(ES_DE_RAW)" --index "$(ES_DE_INDEX)" --output "$(ES_DE_JSON)"

build-sqlite-es-de:
	$(PYTHON) $(TOOLS_DIR)/build_site_sqlite.py --json "$(ES_DE_JSON)" --index "$(ES_DE_INDEX)" --sqlite "$(ES_DE_SQLITE)"

build-data-es-de: build-index-es-de build-raw-es-de build-json-es-de build-sqlite-es-de

serve:
	cd "$(ROOT_DIR)" && uv run fastapi dev --host 127.0.0.1 --port 8001

lock-fastapi:
	cd "$(ROOT_DIR)" && uv lock

clean:
	rm -f "$(DE_ES_INDEX)" "$(DE_ES_RAW)" "$(DE_ES_JSON)" "$(DE_ES_SQLITE)"
	rm -f "$(ES_DE_INDEX)" "$(ES_DE_RAW)" "$(ES_DE_JSON)" "$(ES_DE_SQLITE)"
