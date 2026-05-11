PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
SCRIPT := mpp
SRC    := $(CURDIR)/bin/$(SCRIPT)
DEST   := $(BINDIR)/$(SCRIPT)

.PHONY: help install uninstall check

help:
	@echo "Targets:"
	@echo "  install     Symlink bin/$(SCRIPT) into $(BINDIR) (PREFIX=$(PREFIX))"
	@echo "  uninstall   Remove the symlink"
	@echo "  check       Verify required dependencies are on PATH"

install:
	@mkdir -p $(BINDIR)
	@ln -sf $(SRC) $(DEST)
	@echo "Installed: $(DEST) -> $(SRC)"

uninstall:
	@if [ -L $(DEST) ] || [ -f $(DEST) ]; then \
		rm -f $(DEST); \
		echo "Removed: $(DEST)"; \
	else \
		echo "Not installed: $(DEST)"; \
	fi

check:
	@for tool in pandoc marker_single bash; do \
		if command -v $$tool >/dev/null 2>&1; then \
			echo "✓ $$tool ($$($$tool --version 2>/dev/null | head -1))"; \
		else \
			echo "✗ $$tool not found"; \
		fi; \
	done
