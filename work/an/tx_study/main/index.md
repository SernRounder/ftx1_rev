# MAIN TX 键控链反编译索引

| entry | name | size | 命中原因 | callers | callees |
|---|---|---|---|---|---|
| ffea12a3 | FUN_ffea12a3 | 119 | caller2-of-fff576bd | ffea1158 | fff5d91c,fff7eb73,fff3e84b,fff33ef5,fff5ca72,ffecef1c,fff516ff,fff3178e,fff53d8d,ffea5750,ffeeceac,ffec8820,ffea753f,ffe |
| ffea65fd | FUN_ffea65fd | 397 | callee-of-fff579c0<br>callee-of-fff5836e | ffef4ad8,fff37e33,fff40615,ffeedfc9,fff03b81,fff05eb4,fff588f2,ffed2934,ffef11c5,fff3fce3,fff80a19,ffef4c34,fff5f28a,ffe | ffec6ae0,ffec06f0,ffec0671,ffea51f5,ffea517c,ffec6639,ffec6ac3,ffec07ca,ffec07b2 |
| ffea678a | FUN_ffea678a | 10 | callee-of-ffed6966 | ffea5750,ffef0411,ffed2594,ffed6966,ffeaf5d4,ffecc23d,ffed6822,fff5f314,ffea8ea9,ffed04c3,ffed22ff |  |
| ffec08df | FUN_ffec08df | 57 | ref-0x8C02B(1) | ffea8ec4,ffed09e9,fff3789b,fff36595,fff386e4,fff36625,fff3642a,fff36729,fff38762,fff37237,fff373ba,fff36875,fff38657,ffe |  |
| ffeca60a | FUN_ffeca60a | 29 | callee-of-fff5836e | ffea873d,ffed09e9,ffeb48dc,ffea753f,fff5836e | ffec6639,ffec7253 |
| ffeced3b | FUN_ffeced3b | 481 | ref-0x17B54(1) | ffea1158 | ffed2f31,ffecdc0a,ffecaa9e,ffea517c,ffea4200,ffecc0de,fff425bb,ffec85cc,fff42706 |
| ffecf45a | FUN_ffecf45a | 15 | ref-0x17B54(1) | ffebb802,ffea8ec4,fff488be,ffeb726d,fff59043,ffec86cf,ffea7e71,fff5c898,ffeb8896 |  |
| ffed09e9 | FUN_ffed09e9 | 1148 | ref-0x17B54(2) | ffecf509 | ffec08cc,ffec06f0,ffeca85a,ffec080f,ffec092b,ffec7edc,ffec0a39,ffec0a20,fff5f1bc,ffed2594,ffea51f5,ffec08b4,ffec06d1,ffe |
| ffed101f | FUN_ffed101f | 731 | ref-0x17B54(4) | ffed09e9 | ffea8018,ffec6a72,ffec6639,ffed0e65,ffec7edc,ffea559f,ffed12fa,ffea55c5,ffea5545,ffea65fd,ffea51f5,ffea517c,ffec6db2,ffe |
| ffed12fa | FUN_ffed12fa | 171 | ref-0x17B54(1) | ffed101f | ffea56c7,ffecc06e,ffea56ba |
| ffed1906 | FUN_ffed1906 | 967 | ref-0x17B54(1) | ffecef1c | ffec6639,ffecdf26,ffea5208,ffec7edc,ffec6afb |
| ffed5bc9 | FUN_ffed5bc9 | 345 | caller2-of-ffed6046 | ffea1158,ffea12a3 | ffee4b50,ffea517c,ffed4f18,ffed6046,ffea51f5,ffeebd04,ffed557a,ffed532a,ffece1e6,ffea6d1e,ffed5d22,fff309a1,fff302d9,ffe |
| ffed6046 | FUN_ffed6046 | 186 | caller-of-ffed6966 | ffed5bc9 | ffed6100,ffed6742,ffed65a7,ffed6ddf,ffea5432,ffed67e3,ffed6966,ffed6a82,ffed67f6,ffed6822,ffed6a24,ffed6a53 |
| ffed6966 | FUN_ffed6966 | 190 | core | ffed6046 | ffea678a |
| ffedcd19 | FUN_ffedcd19 | 40 | callee-of-fff579c0 | fff05283,fff058ed,fff82016,fff579c0,fff055b8,ffec427a,fff5f56e,fff036fc,fff81c9e,fff04f20,ffed6ddf,fff04852,fff8059b,fff |  |
| ffef7979 | FUN_ffef7979 | 32 | caller-of-fff5836e |  | fff5836e,fff584fc,fff588f2 |
| ffef799f | FUN_ffef799f | 32 | caller-of-fff5836e |  | fff5836e,fff584fc,fff588f2 |
| ffef7a11 | FUN_ffef7a11 | 32 | caller-of-fff5836e |  | fff5836e,fff584fc,fff588f2 |
| fff576bd | FUN_fff576bd | 10 | caller-of-fff579c0 | ffea12a3 | fff57828,fff579c0,fff576c7 |
| fff579c0 | FUN_fff579c0 | 676 | core | fff576bd | fff58d18,ffedcd19,ffea65fd |
| fff5836e | FUN_fff5836e | 398 | core | ffef7a11,ffef7979,ffef799f | fff58e61,fff58e90,fff58a5e,ffea65fd,ffeca60a |
| fff58a5e | FUN_fff58a5e | 180 | callee-of-fff5836e | fff5836e | fff58b87,fff58bde,fff58b12,fff58cf2 |
| fff58d18 | FUN_fff58d18 | 91 | callee-of-fff579c0 | fff579c0 |  |
| fff58e61 | FUN_fff58e61 | 47 | callee-of-fff5836e | fff57c64,fff5836e,fff589ba | ffeddd2f |
| fff58e90 | FUN_fff58e90 | 37 | callee-of-fff5836e | fff57c64,ffeb48dc,fff5836e,ffeb1cdf,fff584fc,fff588f2 | ffeddd2f |
