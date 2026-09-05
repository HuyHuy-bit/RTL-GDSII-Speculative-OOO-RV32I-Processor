.section .text.init
.globl _start
_start:
    addi x5, x0, 7
    addi x6, x5, 5
    add  x7, x5, x6
    beq  x7, x6, 1f
    addi x8, x7, 1
1:
    ebreak
