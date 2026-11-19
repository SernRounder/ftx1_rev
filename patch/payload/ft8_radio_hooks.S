.syntax unified
.arm
.section .text.ft8_radio_rx_hooks,"ax",%progbits
/* The stock boot can advertise a wrapped size for its primary free block.
   The image's existing stock globals start at 0x607c0000. */
.global ft8_radio_heap_hook
.type ft8_radio_heap_hook,%function
ft8_radio_heap_hook:
    push {r12,lr}
    ldr r12,=0x606e0000
    cmp r4,r12
    bne 1f
    cmp r0,#0xe0000
    movhi r0,#0xe0000
1:
    str r0,[r4,#4]
    pop {r12,lr}
    ldr pc,=0x6047c44c

.global ft8_radio_pool_hook
.type ft8_radio_pool_hook,%function
ft8_radio_pool_hook:
    ldr r0,=0x607c50bc
    ldr r0,[r0]
    cmp r0,#0
    movgt r0,#0
    bxgt lr
    ldr pc,=0x6047703c

.section .ft8_hooks,"a",%progbits
.word ft8_radio_heap_hook, ft8_radio_pool_hook
