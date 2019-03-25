# This makefile is used to install panda to target directory.

# set prefix
ifeq ($(DESTDIR),)
	DESTDIR := /opt/canalyze
endif

# install required files
install: panda.py
	install -d $(PREFIX)$(DESTDIR)
	install -m 755 panda.py $(PREFIX)$(DESTDIR)/panda
