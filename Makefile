setup:
	uv sync

map:
	uv run python scripts/build_map_data.py
	@echo "Serve with: uv run python -m http.server 8080 --directory docs/map"

.PHONY: setup map

REGION ?= ireland

flow-index:
	uv run scripts/build_flow_index.py --region $(REGION)

.PHONY: flow-index
