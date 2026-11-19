    .section .text.ft8_hooks,"ax"
    .equ stock_power_report, 0x1b49c
    .global ft8_main_command_hook
ft8_main_command_hook:
    bsr.a _ft8_main_command
    bra.a stock_e8_return

    .global ft8_main_status_hook
ft8_main_status_hook:
    /* The common builder also supplies stock popup headers. Its frame is
       28 bytes plus saved r6. Check its return and the 0x62 copy caller. */
    mov.l 36[r0],r1
    cmp #0xffee401d,r1            /* 0x20 builder */
    beq.b 1f
    cmp #0xffed7999,r1            /* 0x60 setup builder */
    beq.b 1f
    cmp #0xffedcc3d,r1            /* common header copy */
    bne.b 2f
    mov.l 40[r0],r1
    cmp #0xffee4074,r1            /* 0x62 builder */
    beq.b 1f
    cmp #0xffee43e6,r1            /* alternate 0x62 builder */
    beq.b 1f
2:
    movu.w 16[r0],r1              /* replay the displaced stock zero store */
    mov.l #0x1b47c,r14
    mov.l #0,r15
    mov.b r15,[r14,r1]
    rts
1:
    pushm r2-r5
    /* CAT PC's power source. The field head reports tenths of watts,
       the SPA-1 whole watts. Both bytes are reserved in the stock packet. */
    mov.l #0x50f4,r1
    movu.b [r1],r1
    and #1,r1
    push.l r1
    bsr.a _stock_tx_power
    mov.l #stock_power_report,r3
    mov.b r1,[r3]
    pop r1
    mov.l #0x3f870,r5
    movu.b 15[r5],r2               /* UI mode and revision share the SPA byte */
    bset #7,r2                     /* tag the initial inactive state too */
    or r2,r1
    mov.b r1,1[r3]
    bsr.w _ft8_main_rf_state
    mov.l #0x3f870,r5
    movu.b 12[r5],r3               /* phase */
    cmp #1,r3
    bne.s 1f
    cmp r3,r1
    stnz #2,r1                     /* active and not keyed: PENDING */
    bra.b 3f
1:
    or r1,r3
    bne.b 2f
    push.l r5
    bsr.w _ft8_main_tx_mode
    pop r5
    cmp #0,r1
    mov.l #0,r1                    /* MOV leaves the compare flags intact */
    bne.s 3f
2:
    mov.l #3,r1
3:
    movu.b 13[r5],r3               /* token */
    bset #7,r3                     /* link tag; token only occupies bits 2-4 */
    or r3,r1
    mov.w [r5],r3                  /* heartbeat toggles every 512 ticks */
    btst #9,r3
    bmne #5,r1
    mov.l #0x1b485,r3
    mov.b r1,[r3]
    popm r2-r5
    rts

    /* Keep the internal voice route but hide its file playback request
       from DISPLAY for the duration of the FT8 lease. */
    .global ft8_main_voice_status_hook
ft8_main_voice_status_hook:
    mov.l #0x3f87c,r1
    movu.b [r1],r1
    sub #1,r1
    beq.s 1f
    movu.b [r14,r15],r1
    shll #4,r1
1:
    rts

    /* Read the stock TX state once. BUSY means another source holds TX.
       PENDING covers a transitional or inconsistent state. */
    .global _ft8_main_rf_state
_ft8_main_rf_state:
    mov.l #0x17b54,r14             /* TX_REASON */
    movu.b [r14],r2
    mov.l #3,r1                    /* FT8_LINK_BUSY */
    cmp #0,r2
    beq.s 2f
    cmp #10,r2                     /* VOICE_REASON */
    bne.b 4f
2:
    mov.l #0x822d62,r14            /* TX_ACCEPTED */
    movu.b [r14],r3
    mov.l #0x801324,r14            /* TX_SEQUENCE */
    movu.b [r14],r4
    mov.l #0x8c02b,r14             /* SEND_A_PORT */
    movu.b [r14],r14
    and #8,r14                     /* SEND_A */
    mov.l #2,r1                    /* FT8_LINK_PENDING */
    cmp #0,r2
    beq.b 3f
    cmp #3,r4                      /* TX_SEQUENCE_ON */
    bne.b 4f
    shlr #3,r14
    and r3,r14
    beq.b 4f
    mov.l #1,r1                    /* FT8_LINK_KEYED */
    rts
3:
    or r14,r3
    bne.s 4f
    cmp #8,r4                      /* TX_SEQUENCE_RX */
    bne.s 4f
    mov.l #0,r1                    /* FT8_LINK_IDLE */
4:
    rts

    .section .c2_text,"ax"
    .global ft8_custom_key_by_id_hook
ft8_custom_key_by_id_hook:
    cmp #0xee,r1
    bne.b 1f
    mov.l #_ft8_custom_key_ft8,r1
    rts
1:
    cmp #0xef,r1
    bne.b 2f
    mov.l #_ft8_custom_key_cw,r1
    rts
2:
    cmp #224,r1
    bra.a _sq9pd_key_by_id_fb

    .global ft8_custom_key_by_code_hook
ft8_custom_key_by_code_hook:
    cmp #0x0596,r1
    bne.b 1f
    mov.l #_ft8_custom_key_ft8,r1
    rts
1:
    cmp #0x0597,r1
    bne.b 2f
    mov.l #_ft8_custom_key_cw,r1
    rts
2:
    cmp #0x58b,r1
    bra.a _sq9pd_key_by_code_fb

    .global ft8_custom_softkey_enable_hook
ft8_custom_softkey_enable_hook:
    movu.b r1,r1
    cmp #0xee,r1
    beq.b 1f
    cmp #0xef,r1
    beq.b 1f
    bra.a _sq9pd_softkey_enable
1:
    mov.l #0x84c6,r14
    movu.b [r14],r14
    mov.l #0,r1
    cmp #0,r14
    stz #1,r1
    rts

    .global ft8_custom_softkey_fmt_hook
ft8_custom_softkey_fmt_hook:
    cmp #0xee,r1
    beq.b 1f
    cmp #0xef,r1
    beq.b 1f
    cmp #224,r1
    bra.a _sq9pd_softkey_fmt_fb
1:
    mov.l #0x84c6,r14
    movu.b [r14],r14
    cmp #0,r14
    beq.b 2f
    mov.l 20[r0],r14
    mov.b #0,[r14]
    mov.l 24[r0],r1
    mov.l #0,r2
    mov.l #11,r3
    sstr.b
    mov.l #1,r1
    rtsd #32
2:
    bra.a _sq9pd_softkey_fmt_e9
