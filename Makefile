.PHONY: sync check-google install-watcher

sync:
	python3 scripts/sync_from_cv.py

check-google:
	python3 scripts/sync_from_cv.py --check-google

install-watcher:
	bash scripts/install_watcher.sh
