PROFILE ?= s0-host
LOCKSTEP_SPIKE ?= ../riscv-isa-sim/build/spike

.PHONY: doctor platform-generate platform-check event-generate event-check memory-generate memory-check lockstep-check check-fast check nightly reference-check

doctor:
	@python3 tools/doctor.py --lock config/toolchain.lock --profile "$(PROFILE)"

platform-generate:
	@python3 tools/gen_platform.py --input config/platform.yaml --write

platform-check:
	@python3 tools/gen_platform.py --input config/platform.yaml --check
	@python3 -m unittest -v tests/test_platform.py

event-generate:
	@python3 tools/gen_commit_event.py --input config/commit_event.yaml --write

event-check:
	@python3 tools/gen_commit_event.py --input config/commit_event.yaml --check
	@python3 -m unittest -v tests/test_commit_event.py

memory-generate:
	@python3 tools/gen_memory_protocol.py --input config/memory_protocol.yaml --write

memory-check:
	@python3 tools/gen_memory_protocol.py --input config/memory_protocol.yaml --check
	@python3 -m unittest -v tests/test_memory_protocol.py

lockstep-check:
	@python3 -m unittest -v tests/test_lockstep.py
	@python3 tools/run_lockstep_smoke.py --spike "$(LOCKSTEP_SPIKE)"

check-fast: platform-check event-check memory-check lockstep-check
	@python3 tools/check_s0.py
	@git diff --check

check: doctor check-fast

nightly: check reference-check

reference-check:
	@$(MAKE) --no-print-directory -C verif/reference/rv32i check
