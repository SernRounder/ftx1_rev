.syntax unified
.arm
.section .ft8_vectors,"ax",%progbits

/* Each slot is one ARM instruction. A tail branch preserves the stock
   caller's LR, arguments and flags. Append new slots after the existing ones. */
.macro vector entry
.global vector_\entry
.type vector_\entry,%function
vector_\entry:
    b \entry
.size vector_\entry, .-vector_\entry
.endm

vector func_menu_tile
vector ft8_touch
vector ft8_ui_worker
vector ft8_pre_swap
vector ft8_key_send_hook
vector ft8_live_capture
vector ft8_panel_hit
vector ft8_radio_heap_hook
vector ft8_radio_pool_hook
#ifdef FT8_RADIO_TX_HOOKS
vector ft8_radio_source_hook
vector ft8_radio_done_hook
vector ft8_radio_readback_hook
vector ft8_radio_gps_hook
vector ft8_radio_gps_status_hook
#endif
