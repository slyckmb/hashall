HASH_SCRIPT=hash_scan_parallel.py
VERIFY_SCRIPT=verify_full_hashes.py
CLEAN_SCRIPT=clean_missing_paths.py
DB=$(HOME)/.filehash.db

.PHONY: hash verify clean reset help

hash:
	@if [ -z "$(TARGET)" ]; then \
		echo "❌ Please specify TARGET=/path/to/scan"; \
		exit 1; \
	fi
	@echo "🔍 Scanning: $(TARGET)"
	python3 $(HASH_SCRIPT) $(TARGET)

verify:
	@echo "🔍 Verifying full hashes for duplicates..."
	python3 $(VERIFY_SCRIPT)

clean:
	@echo "🧹 Cleaning missing paths from DB..."
	python3 $(CLEAN_SCRIPT)

reset:
	@echo "🔥 Deleting database at $(DB)..."
	rm -f $(DB)

help:
	@echo "Usage: make [target] TARGET=/path/to/scan"
	@echo "Targets:"
	@echo "  hash     - Scan directory and record partial hashes"
	@echo "  verify   - Fill in full hashes for detected duplicates"
	@echo "  clean    - Remove deleted file paths from DB"
	@echo "  reset    - Delete DB file completely"
	@echo "  help     - Show this help message"
