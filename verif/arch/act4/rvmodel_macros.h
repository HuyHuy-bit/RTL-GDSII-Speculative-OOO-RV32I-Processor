#ifndef SPEC_OOO_RVMODEL_MACROS_H
#define SPEC_OOO_RVMODEL_MACROS_H

#define RVMODEL_DATA_SECTION \
  .pushsection .tohost,"aw",@progbits; \
  .align 3; .global tohost; tohost: .dword 0; \
  .align 3; .global fromhost; fromhost: .dword 0; \
  .popsection

#define RVMODEL_BOOT

#define RVMODEL_HALT_PASS \
  li x1, 1; \
  la t0, tohost; \
1: sw x1, 0(t0); \
  sw x0, 4(t0); \
  j 1b;

#define RVMODEL_HALT_FAIL \
  li x1, 3; \
  la t0, tohost; \
1: sw x1, 0(t0); \
  sw x0, 4(t0); \
  j 1b;

#define RVMODEL_IO_INIT(_R1, _R2, _R3)
#define RVMODEL_IO_WRITE_STR(_R1, _R2, _R3, _STR_PTR)
#define RVMODEL_ACCESS_FAULT_ADDRESS 0x20000000

/* ACT4 requires these hooks; invoking an unsupported interrupt fails the test. */
#define RVMODEL_INTERRUPT_LATENCY 0
#define RVMODEL_TIMER_INT_SOON_DELAY 0
#define RVMODEL_SET_MEXT_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_CLR_MEXT_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_SET_MSW_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_CLR_MSW_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_SET_SEXT_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_CLR_SEXT_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_SET_SSW_INT(_R1, _R2) j rvmodel_halt_fail;
#define RVMODEL_CLR_SSW_INT(_R1, _R2) j rvmodel_halt_fail;

#endif
