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
