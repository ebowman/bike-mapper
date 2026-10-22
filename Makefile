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

ui-check:
	@mkdir -p /tmp/ui-check
	@uv run python -c "import re,sys; s=open('web/index.html').read(); m=re.findall(r'<script>(.*?)</script>', s, re.S); assert m, 'no inline script'; open('/tmp/ui-check/inline.js','w').write(m[-1])"
	node --check /tmp/ui-check/inline.js
	@echo "ui-check ok"

.PHONY: ui-check

# Flow route planner: see docs/planner.md. BRouter and the planner run in two terminals.
planner-setup:
	scripts/run_brouter.sh setup
	$(MAKE) flow-index

brouter:
	scripts/run_brouter.sh serve

planner-profiles:
	scripts/run_brouter.sh profiles

planner:
	@echo "Planner: http://localhost:8081"
	uv run scripts/flow_server.py --port 8081

planner-check:
	uv run pytest -q
	uvx ruff check scripts/ tests/
	$(MAKE) ui-check

.PHONY: planner-setup brouter planner planner-check planner-profiles

# Cycle infrastructure overlay for the planner map (needs data/osm/ireland.osm.pbf; ~40 s). See docs/planner.md.
cycle-overlay:
	uv run scripts/build_cycle_overlay.py

.PHONY: cycle-overlay
