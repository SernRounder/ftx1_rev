.syntax unified
.arm
.text

/* The stock task constructor initializes CPSR for an ARM entry. */
.global ft8_radio_worker_entry
.type ft8_radio_worker_entry,%function
ft8_radio_worker_entry:
    ldr r3,=ft8_radio_worker
    bx r3

.global ft8_radio_watchdog_entry
.type ft8_radio_watchdog_entry,%function
ft8_radio_watchdog_entry:
    ldr r3,=ft8_radio_watchdog
    bx r3
