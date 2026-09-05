OUTPUT_ARCH("riscv")
ENTRY(rvtest_entry_point)

SECTIONS
{
  . = 0x00000000;
  .text.init : { *(.text.init) }
  .text.rvtest : { *(.text.rvtest) *(.text.rvtest.*) }
  . = ALIGN(0x4000);
  .data : { *(.data) }
  . = ALIGN(0x1000);
  .text.rvmodel : { *(.text.rvmodel) *(.text.rvmodel.*) *(.text) *(.text.*) }
  . = ALIGN(8);
  .tohost : { *(.tohost) }
  . = ALIGN(16);
  _end = .;
  ASSERT(_end <= 0x00010000, "ACT image exceeds BRAM")
}
