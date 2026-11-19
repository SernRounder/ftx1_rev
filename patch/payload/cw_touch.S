.syntax unified
.arm
.section .text.cw_touch, "ax", %progbits
.global cw_touch
.type cw_touch, %function
cw_touch:
    movw    ip, #0x1134
    cmp     r1, ip
    beq     .Ltry_local
.Lstock:
    push    {r4-r10, lr}
    movw    ip, #0x32e4
    movt    ip, #0x6042
    bx      ip
.Ltry_local:
    push    {r0-r4, lr}
    bl      cw_local_touch
    cmp     r0, #0
    pop     {r0-r4, lr}
    beq     .Lstock
    bx      lr
.size cw_touch, .-cw_touch

.global cw_readback_hook
.type cw_readback_hook, %function
cw_readback_hook:
    push    {r0-r4, lr}
    mov     r0, r1
    mov     r1, r2
    bl      cw_report_packet
    pop     {r0-r4, lr}
    ldr     pc, =0x604c965c
.size cw_readback_hook, .-cw_readback_hook
