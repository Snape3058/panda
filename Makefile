# This makefile is used to install panda to target directory.

# set prefix
ifeq ($(PREFIX),)
	PREFIX := /opt/canalyze
endif

# install required files
install: panda.py
	install -d $(DESTDIR)$(PREFIX)
	install -m 755 panda.py $(DESTDIR)$(PREFIX)/panda
