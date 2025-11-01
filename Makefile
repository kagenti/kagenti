
.PHONY: lint
lint:
	cd kagenti/ui; uv run pylint Home.py pages/*.py lib/*.py

.PHONY: kinst
kinst:
	cd kagenti/kinst && uv run kinst $(ARGS)
