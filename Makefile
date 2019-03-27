# This makefile is used to install panda to target directory.

# set prefix
ifeq ($(DESTDIR),)
	DESTDIR := /opt/canalyze
endif

BRANCH := $(shell git rev-parse --abbrev-ref HEAD)
COMMIT := $(shell git rev-parse HEAD)
YEAR := $(shell date +%Y)

# install required files
install: panda.py
	sed -i 's/%REPLACE_COMMIT_INFO%/$(BRANCH) - $(COMMIT)/g;s/%REPLACE_NOW%/$(YEAR)/g' panda.py
	install -d $(PREFIX)$(DESTDIR)
	install -m 755 panda.py $(PREFIX)$(DESTDIR)/panda
	git checkout panda.py
