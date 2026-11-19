.syntax unified
.arm
.section .text.ft8_touch, "ax", %progbits
.global ft8_touch
.type ft8_touch, %function
ft8_touch:
    movw    ip, #0x1134
    cmp     r1, ip
    movwne  ip, #0x1135
    cmpne   r1, ip
#ifdef FT8_CUSTOM_MODES
    movwne  ip, #0x1138
    cmpne   r1, ip
#endif
    beq     .Ltry_local
    movw    ip, #0x1200          /* our in-page event range 0x1200..0x12FF */
    sub     ip, r1, ip
#ifdef FT8_RADIO
    cmp     ip, #0x200
    blo     .Ltry_local
#else
    cmp     ip, #0x100
    blo     .Ltry_local
#endif
.Lstock:
    push    {r4-r10, lr}
    movw    ip, #0x32e4
    movt    ip, #0x6042
    bx      ip
.Ltry_local:
    push    {r0-r4, lr}
    bl      ft8_local_touch
    cmp     r0, #0
    pop     {r0-r4, lr}
    beq     .Lstock
    bx      lr
.size ft8_touch, .-ft8_touch
