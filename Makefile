# This makefile is used to install panda to target directory.

# set prefix
ifeq ($(DESTDIR),)
	DESTDIR := /opt/canalyze
endif

BRANCH := $(shell git rev-parse --abbrev-ref HEAD)
COMMIT := $(shell git rev-parse HEAD)
COMPILER := $(shell gcc --version | head -n 1)
SYSTEM := $(shell uname -srm)
TIME := $(shell date +%Y%m%d-%H%M)
OWNER := $(shell ls -l panda.py |awk '{print $$3}')

# set debug flag
ifeq ($(DEBUG),1)
	CC_FLAGS := -O0 -g -DDEBUG=1 -DBUILD_TYPE='"Debug"'
else
	CC_FLAGS := -O3 -DBUILD_TYPE='"Release"'
endif
CC_ENVIRONMENT_DEFINES := -DBUILD_TIME='"$(TIME)"' -DBUILD_BRANCH='"$(BRANCH)"' -DBUILD_COMMIT='"$(COMMIT)"' -DBUILD_COMPILER='"$(COMPILER)"' -DBUILD_SYSTEM='"$(SYSTEM)"'

libpanda.so: panda.c
	gcc $(CC_FLAGS) $(CC_ENVIRONMENT_DEFINES) -fPIC -shared -o $@ $< -ldl

# install required files
install: panda.py libpanda.so
	sudo -u ${OWNER} sed -i 's/%REPLACE_COMMIT_INFO%/$(BRANCH) - $(COMMIT)/g' panda.py
	install -d $(PREFIX)$(DESTDIR)
	install -m 755 panda.py $(PREFIX)$(DESTDIR)/panda
	install -m 755 libpanda.so $(PREFIX)$(DESTDIR)/panda
	sudo -u ${OWNER} git checkout panda.py

.PHONY: clean
clean:
	rm -f libpanda.so
