PROFILE ?= s0-host

.PHONY: doctor check-fast check nightly reference-check

doctor:
	@python3 tools/doctor.py --lock config/toolchain.lock --profile "$(PROFILE)"

check-fast:
	@python3 tools/check_s0.py
	@git diff --check

check: doctor check-fast

nightly: check reference-check

reference-check:
	@$(MAKE) --no-print-directory -C verif/reference/rv32i check
