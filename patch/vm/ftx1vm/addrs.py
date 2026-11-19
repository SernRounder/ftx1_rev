"""FTX-1 DISPLAY board constants (RZ/A1H, Cortex-A9).

All offsets are relative to IMAGE_BASE; every block carries the evidence
source (work/an/... decompilation or probe result) so the mapping stays
traceable.
"""

IMAGE_BASE = 0x60400000
IMAGE_SIZE = 0x2C3000          # stock display.bin 2,895,804 B rounded up

# --- guest RAM -----------------------------------------------------------
SRAM_BASE = 0x60000000
SRAM_SIZE = 0xA00000           # 10 MiB internal SRAM (preview_ft8.py layout)
FRAMEBUFFER = 0x60000000       # 800x480 RGB565, layer selected by *(u32*)0x607C4BB0
AUDIO_CTX = 0x607C0090         # display-funcs-audio.txt
LAYER_VAR = 0x607C4BB0         # stock framebuffer layer (3)
UI_STATE = 0x60935BB4          # radio-state mirror; page@+0, popup@+0x13B

# --- vector table (display.bin @0) ---------------------------------------
VBAR = IMAGE_BASE
RESET_ENTRY = IMAGE_BASE + 0x2C          # vector 0x00 -> 0x2C (probed)
UNDEF_VECTOR = IMAGE_BASE + 0x04         # -> 0x1EC
SVC_VECTOR = IMAGE_BASE + 0x08           # -> 0x160 dispatcher
IRQ_ENTRY = IMAGE_BASE + 0x1A4           # vector 0x18 -> 0x1A4 (dec_irq.txt)


# --- peripherals ---------------------------------------------------------
GICD_BASE = 0xE8201000         # kernel pool 0x16768 (PL390 / GICv1; R01UH0403EJ0700 p185)
GICC_BASE = 0xE8202000
GIC_INTIDS = 586               # dec_irq.txt FUN_00016468 bound (0x24A software table limit)

OSTM0_BASE = 0xFCFEC000        # kernel tick (P0phi clock), literal 0x167DC; GIC INTID 134
OSTM1_BASE = 0xFCFEC400        # secondary (P0phi clock), boot init 0x15A9C; GIC INTID 135

SCIF5_BASE = 0xE8009800        # SCIF5 (P1phi clock), report-display-tx-uart.md; INTIDs 241-244
SCIF5_BAUD = 345600            # 8 data, no parity, 2 stop ("345600 B8 PN S2")

RIIC0_BASE = 0xFCFEE000        # RIIC0..3 (touch IC is XPT7603 Q6008; tsc2007 is task name)
SPIBSC0_BASE = 0x3FEFA000      # SPIBSC NOR QSPI controller (R01UH0403EJ0700)
SPIBSC1_BASE = 0x3FEFB000
RSPI0_BASE = 0xE800C800        # RSPI0 factory SPI slave (0x800 stride, RSPI0..4)
RSPI2_BASE = 0xE800D800        # RSPI2 secondary stream (0x6A4 B; peer unverified)
RSPI4_BASE = 0xE800E800        # RSPI4 audio link (0x2260 B DMA; peer unverified, #118)
SDHI0_BASE = 0xE804E000        # SD card ("I:\FTX-1")
CPG_BASE = 0xFCFE0000          # system control / standby / pin mux block (0x400-0x470)
PORT_BASE = 0xFCFE3000         # port block (PSR7 +0x11C, PPR0 +0x200; BSC is 0x3FFFC000)
PL310_BASE = 0x3FFFF000        # L2 cache (report-display-tx-uart.md)
MTU2_BASE = 0xFCFF0000         # standby / peripheral block 0xFCFF0000 (unverified IP)
JCU_BASE = 0xE8017000          # JPEG codec unit (JCMOD/JCCMD; FUN_00022788 pool)

# --- firmware call points used by the VM ---------------------------------
DMA_DONE_CALL = IMAGE_BASE + 0x45170   # patched audio frame completion BL
DMA_DONE_END = IMAGE_BASE + 0x45174

# GIC INTIDs (SPI + 32)
IRQ_OSTM0 = 134                # OSTM0 SPI 102
IRQ_OSTM1 = 135                # OSTM1 SPI 103
IRQ_SCIF5_ERI = 241
IRQ_SCIF5_RXI = 242
IRQ_SCIF5_TXI = 243
IRQ_SCIF5_BRI = 244

ARM_SVC, ARM_UND, ARM_IRQ, ARM_FIQ, ARM_SYS, ARM_ABT = 0x13, 0x1B, 0x12, 0x11, 0x1F, 0x17
CPSR_I, CPSR_F, CPSR_T = 0x80, 0x40, 0x20
