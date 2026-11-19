    .section .text.softkey_hooks,"ax"

    .global _softkey_menu_reg_hook
_softkey_menu_reg_hook:
    bsr.a   stock_reg_last
    bsr.a   _softkey_register_items
    rts

    .global _softkey_slot0_next_hook
_softkey_slot0_next_hook:
    bsr.a   _softkey_next_page
    rtsd    #16

    .global _softkey_cb28_key0
_softkey_cb28_key0:
    mov.l   #0, r2
    bra.w   _softkey_cb28_key

    .global _softkey_cb28_key1
_softkey_cb28_key1:
    mov.l   #1, r2
    bra.w   _softkey_cb28_key

    .global _softkey_cb28_key2
_softkey_cb28_key2:
    mov.l   #2, r2
    bra.w   _softkey_cb28_key

    .global _softkey_cb28_key3
_softkey_cb28_key3:
    mov.l   #3, r2
    bra.w   _softkey_cb28_key

    .global _softkey_cb28_key4
_softkey_cb28_key4:
    mov.l   #4, r2
    bra.w   _softkey_cb28_key

    .global _softkey_cb32_key0
_softkey_cb32_key0:
    mov.l   #0, r1
    bra.w   _softkey_cb32_key

    .global _softkey_cb32_key1
_softkey_cb32_key1:
    mov.l   #1, r1
    bra.w   _softkey_cb32_key

    .global _softkey_cb32_key2
_softkey_cb32_key2:
    mov.l   #2, r1
    bra.w   _softkey_cb32_key

    .global _softkey_cb32_key3
_softkey_cb32_key3:
    mov.l   #3, r1
    bra.w   _softkey_cb32_key

    .global _softkey_cb32_key4
_softkey_cb32_key4:
    mov.l   #4, r1
    bra.w   _softkey_cb32_key

/*
 * Hook at 0xFFEF2A05 (end of 0xFFEF292A menu/popup exit):
 *   executes original `mov.b r5, [r14, r15]` (ctx[0x21d7a] = 0),
 *   arms unused MAIN timer #41 for 350 ms to suppress trailing FUNC dial
 *   events right after BACK exits a menu, then returns via `rtsd #4`.
 */
    .global _softkey_menu_exit_hook
_softkey_menu_exit_hook:
    mov.b   r5, [r14, r15]
    mov.l   #41, r1
    mov.l   #350, r2
    bsr.a   stock_timer_set
    rtsd    #4

/*
 * Hook at 0xFFF2C864 (Home FUNC dial popup trigger):
 *   r1 = (int8_t)43[r0] (encoder delta).
 *   If a popup is already active (ctx[0x21d75] == 1), pass through.
 *   Otherwise only open a new popup when ctx[202] == 0 (Home) AND
 *   timer #41 has expired (0x8552 != 0).
 */
    .global _softkey_func_dial_hook
_softkey_func_dial_hook:
    mov.l   #0x83B1E0, r14
    mov.l   [r14], r14
    mov.l   #0x21D75, r15
    movu.b  [r14, r15], r15
    cmp     #1, r15
    beq.b   1f
    movu.b  202[r14], r14
    cmp     #0, r14
    bne.b   2f
    mov.l   #0x8552, r14
    movu.b  [r14], r14
    cmp     #0, r14
    beq.b   2f
1:
    bsr.a   stock_func_popup
2:
    rtsd    #44
