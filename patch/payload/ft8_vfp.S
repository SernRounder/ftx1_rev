.syntax unified
.arm
.fpu vfpv3-d16
.section .ft8_vfp_text,"ax",%progbits

.global ft8_vfp_probe
.type ft8_vfp_probe,%function
ft8_vfp_probe:
    push {r3-r11,lr}
    mov r11,sp
    mrs r4,cpsr
    cpsid if
    mrc p15,0,r0,c12,c0,0
    ldr r5,=0x60400004
    add r0,r0,#4
    cmp r0,r5
    bne .Ldone_false
    ldr r6,[r5]
    ldr r0,=0xea000078
    cmp r6,r0
    bne .Ldone_false
    ldr r0,=ft8_vfp_undef
    sub r0,r0,r5
    sub r0,r0,#8
    lsl r0,r0,#6
    lsr r0,r0,#8
    orr r0,r0,#0xea000000
    str r0,[r5]
    bl .Lsync_vector
    mov r7,#0                 @ state: 0 untouched, 1 CPACR saved, 2 FPEXC saved
    mov r8,#0                 @ FPEXC saved
    mov r9,#0                 @ result
.Lguard_begin:
    mrc p15,0,r10,c1,c0,2
    mov r7,#1
    orr r0,r10,#0x00f00000
    mcr p15,0,r0,c1,c0,2
    isb
    mrc p15,0,r1,c1,c0,2
    and r1,r1,#0x00f00000
    cmp r1,#0x00f00000
    bne .Lrestore
    vmrs r8,fpexc
    mov r7,#2
    mov r0,#0x40000000
    vmsr fpexc,r0
    vmrs r1,fpscr
    vpush {d0}
    mov r0,#0x3f800000
    vmov s0,r0
    vadd.f32 s1,s0,s0
    vmov r0,s1
    vpop {d0}
    vmsr fpscr,r1
    cmp r0,#0x40000000
    moveq r9,#1
.Lguard_end:
.Lrestore:
    @ An exception may have occurred between vpush and vpop.
    mov sp,r11
    cmp r7,#2
    vmsreq fpexc,r8
    cmp r7,#0
    mcrne p15,0,r10,c1,c0,2
    isb
    str r6,[r5]
    bl .Lsync_vector
    mov r0,r9
    b .Ldone
.Ldone_false:
    mov r0,#0
.Ldone:
    msr cpsr_c,r4
    pop {r3-r11,pc}
.size ft8_vfp_probe,.-ft8_vfp_probe

.Lsync_vector:
    push {r3,lr}
    mov r0,r5
    mov r1,#4
    ldr r3,=0x60402fa8
    blx r3
    mov r0,r5
    mov r1,#4
    ldr r3,=0x60402efc
    blx r3
    pop {r3,pc}

.global ft8_vfp_undef
.type ft8_vfp_undef,%function
ft8_vfp_undef:
    ldr r0,=.Lguard_begin+4
    cmp lr,r0
    blo .Lstock_undef
    ldr r0,=.Lguard_end
    cmp lr,r0
    ldrls lr,=.Lrestore
    movsls pc,lr
.Lstock_undef:
    ldr pc,=0x604001ec
.size ft8_vfp_undef,.-ft8_vfp_undef

/* The RTOS does not switch VFP state. Only the RX worker enters here.
   Preserve the prior FP environment and use the normal IRQ scheduler. */
.macro guarded_vfp name, target, fifth=0
.global \name
.type \name,%function
\name:
    push {r4-r8,lr}
.if \fifth
    ldr r7,[sp,#24]
    mov r8,r3
.endif
    mrc p15,0,r4,c1,c0,2
    orr r3,r4,#0x00f00000
    mcr p15,0,r3,c1,c0,2
    isb
    vmrs r5,fpexc
    mov r3,#0x40000000
    vmsr fpexc,r3
    vmrs r6,fpscr
    vpush {d0-d15}
    mov r3,#0
    vmsr fpscr,r3
.if \fifth
    push {r7,r8}
    mov r3,r8
.endif
    bl \target
.if \fifth
    add sp,sp,#8
.endif
    vpop {d0-d15}
    vmsr fpscr,r6
    vmsr fpexc,r5
    mcr p15,0,r4,c1,c0,2
    isb
    pop {r4-r8,pc}
.size \name,.-\name
.endm

#ifdef CW_VFP
.text
guarded_vfp cw_feed, cw_feed_vfp
guarded_vfp cw_discontinuity, cw_discontinuity_vfp
.section .ft8_vfp_text,"ax",%progbits
#endif

#ifdef FT8_VFP_ONLY
guarded_vfp ft8_vfp_fft, ft8_hw_monitor
.text
guarded_vfp ft8_vfp_candidate, ft8_hw_candidate, 1
guarded_vfp ft8_vfp_sqrt, .Lhw_sqrt
.Lhw_sqrt:
    vmov s0,r0
    vsqrt.f32 s0,s0
    vmov r0,s0
    bx lr
#else
guarded_vfp ft8_vfp_fft, ft8_hw_fftr_packed
#endif
