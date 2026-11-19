.syntax unified
.arm
.section .ft8_tx_hooks,"ax",%progbits

/* Replace the original store to CH3 N0SA, then resume the stock start. */
.global ft8_radio_source_hook
.type ft8_radio_source_hook,%function
ft8_radio_source_hook:
    push {r1-r4,r12,lr}
    bl ft8_radio_dma_source
    pop {r1-r4,r12,lr}
    str r0,[r6,#0xc0]
    ldr pc,=0x604452b8

/* Keep the stock completion flag and return to the original IRQ dispatcher. */
.global ft8_radio_done_hook
.type ft8_radio_done_hook,%function
ft8_radio_done_hook:
    str r0,[r1]
    push {r0-r3,r12,lr}
    bl ft8_radio_dma_done
    pop {r0-r3,r12,lr}
    bx lr

.global ft8_radio_readback_hook
.type ft8_radio_readback_hook,%function
ft8_radio_readback_hook:
    push {r0-r4,lr}
    mov r0,r1
    mov r1,r2
    bl ft8_radio_report_packet
    pop {r0-r4,lr}
    ldr pc,=0x604c965c

.global ft8_radio_gps_hook
.type ft8_radio_gps_hook,%function
ft8_radio_gps_hook:
    ldr ip,=ft8_radio_gps_packet
    bx ip

/* Replace the RMC status comparison and keep its flags for the stock BNE.
   At this point the stock byte receiver has verified the NMEA checksum. */
.global ft8_radio_gps_status_hook
.type ft8_radio_gps_status_hook,%function
ft8_radio_gps_status_hook:
    cmp r1,#'A'
    bxeq lr
    push {r2,r3}
    ldr r2,=ft8_radio_gps_grid
    mov r3,#0
    str r3,[r2]
    pop {r2,r3}
    bx lr
