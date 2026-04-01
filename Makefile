PYTHON ?= uv run
PHP ?= php
SITE_DIR := /home/tin/lab/UniLex/site
TOOLS_DIR := /home/tin/lab/UniLex/tools

.PHONY: all build-json build-sqlite build-data serve clean

all: build-data

build-json:
	$(PYTHON) $(TOOLS_DIR)/build_site_dictionary.py

build-sqlite:
	$(PYTHON) $(TOOLS_DIR)/build_site_sqlite.py

build-data: build-json build-sqlite

serve:
	cd $(SITE_DIR) && $(PHP) -S 127.0.0.1:8000

clean:
	rm -f $(SITE_DIR)/data/dictionary-indexed.json
	rm -f $(SITE_DIR)/data/dictionary.sqlite
