/* platform-sha256: 378dbc14e4dda2a3d833f0f238441c55efda7224b2f969dec7710ed2602532de */
ENTRY(_start)
MEMORY
{
  ram (rwx) : ORIGIN = 0x00000000, LENGTH = 0x00010000
}
SECTIONS
{
  . = ORIGIN(ram);
  .text : { KEEP(*(.text.init)) *(.text .text.*) } > ram
  .rodata : { *(.rodata .rodata.*) } > ram
  .data : { *(.data .data.*) } > ram
  .bss : { *(.bss .bss.* COMMON) } > ram
  . = ALIGN(16);
  _end = .;
  _stack_top = ORIGIN(ram) + LENGTH(ram);
}
