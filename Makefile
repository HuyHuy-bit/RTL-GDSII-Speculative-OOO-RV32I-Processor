PROFILE ?= s0-host

.PHONY: doctor platform-generate platform-check check-fast check nightly reference-check

doctor:
	@python3 tools/doctor.py --lock config/toolchain.lock --profile "$(PROFILE)"

platform-generate:
	@python3 tools/gen_platform.py --input config/platform.yaml --write

platform-check:
	@python3 tools/gen_platform.py --input config/platform.yaml --check
	@python3 -m unittest -v tests/test_platform.py

check-fast: platform-check
	@python3 tools/check_s0.py
	@git diff --check

check: doctor check-fast

nightly: check reference-check

reference-check:
	@$(MAKE) --no-print-directory -C verif/reference/rv32i check
