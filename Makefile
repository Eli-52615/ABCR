PYTHON = .venv/bin/python
PYTEST = .venv/bin/pytest

.PHONY: bootstrap stage1-regression stage2-regression stage3-regression stage4-regression mini-loop repro-pack resource-smoke resource-smoke-3b chunk-run

bootstrap:
	bash scripts/bootstrap.sh

stage1-regression:
	$(PYTEST) tests/contract/stage1 -x -q

stage2-regression:
	$(PYTEST) tests/contract/stage2 -x -q

stage3-regression:
	$(PYTEST) tests/contract/stage3 -x -q

stage4-regression:
	$(PYTEST) tests/contract/stage4 -x -q

mini-loop:
	$(PYTHON) -m abcr.run --config configs/runs/mini_vanilla.yaml --dev
	$(PYTHON) -m abcr.run --config configs/runs/mini_text.yaml --dev
	$(PYTHON) -m abcr.run --config configs/runs/mini_vector.yaml --dev
	$(PYTHON) -m abcr.run --config configs/runs/mini_random.yaml --dev

resource-smoke:
	$(PYTHON) -m abcr.resource_guard smoke

resource-smoke-3b:
	$(PYTHON) -m abcr.resource_guard smoke-3b

chunk-run:
	bash scripts/chunk_driver.sh $(CONFIG)

repro-pack:
	$(PYTHON) -m abcr.repro_pack --preset $(PRESET) --out repro_packs/$(PRESET)

# ==== 自动化控制面（fable 在 R1 门汇编；广播 20260715 AMENDMENT-40：一律 .venv312 + PYTHONPATH=src）====
CTL_PYTHON = .venv312/bin/python

.PHONY: preflight contract-pkgabc test-pkga test-pkgb test-pkgc r1-selfcheck-b

preflight:
	PYTHONPATH=src $(CTL_PYTHON) scripts/preflight_kickoff.py

contract-pkgabc:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/contract_pkgabc -q

test-pkga:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/contract_pkgabc tests/ledger tests/audit -q

test-pkgb:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/contract_pkgabc tests/ops tests/rig -q -m "not golden"

test-pkgc:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/contract_pkgabc tests/governor tests/report -q

r1-selfcheck-b:
	bash scripts/b_r1_selfcheck.sh

# ==== V17 成本闸自检（零计费；不设 APPROVE_COST 时必须拦住付费测试）====
.PHONY: cost-gate-check

# 可覆盖解释器（worktree 里可能没有本地 .venv312）：
#   make cost-gate-check COST_GATE_PYTHON=../../abcr/.venv312/bin/python
COST_GATE_PYTHON ?= $(CTL_PYTHON)

cost-gate-check:
	@PY="$(COST_GATE_PYTHON)"; \
	 [ -x "$$PY" ] || PY=../../abcr/.venv312/bin/python; \
	 [ -x "$$PY" ] || PY=python3; \
	 OUT=$$(mktemp); \
	 env -u APPROVE_COST -u OPENAI_API_KEY -u DEEPSEEK_API_KEY -u OPENAI_BASE_URL \
	   PYTHONPATH=src "$$PY" -m pytest --collect-only -q >"$$OUT" 2>&1; \
	 grep -q "cost-gate: armed" "$$OUT" \
	   || { echo "COST-GATE FAIL: gate not armed during collection"; cat "$$OUT"; rm -f "$$OUT"; exit 1; }; \
	 grep -qE "^tests/.*test_b_direction_3b|^tests/.*test_b_pv_e2e_05b" "$$OUT" \
	   && { echo "COST-GATE FAIL: paid test still collected without APPROVE_COST"; rm -f "$$OUT"; exit 1; }; \
	 grep -c "^cost-gate: blocked " "$$OUT" | xargs -I{} echo "COST-GATE OK: {} paid test file(s) excluded before import (APPROVE_COST unset)"; \
	 rm -f "$$OUT"

# ==== 2026-07-19 人格探索控制面（零网络 CODE_RC）====
.PHONY: control-contract control-test control-adversarial control-fixture control-rc

control-contract:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/control/test_deployment_contract.py tests/explore/test_goal_persona.py -q

control-test:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/explore tests/probe tests/control -q

control-adversarial:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/control/test_black_box_oracle.py tests/control/test_worktree_release.py tests/control/test_work_spool.py tests/control/test_ed25519.py -q

control-fixture:
	PYTHONPATH=src $(CTL_PYTHON) -m pytest tests/integration/test_control_journeys.py -q

control-rc: control-contract control-test control-adversarial control-fixture
