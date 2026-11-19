# MAIN TX 第二批反编译索引

| entry | name | size | 命中原因 | callers | callees |
|---|---|---|---|---|---|
| ffea1158 | FUN_ffea1158 | 331 | core2 | ffe9e9c3 | ffebaa26,ffec0656,ffea9250,ffeece06,fff3d830,fff7ea82,ffeb7fe7,ffeced3b,ffec0f43,fff7eaac,ffea517c,ffec0d01,fff33e74,fff |
| ffea12a3 | FUN_ffea12a3 | 119 | core2 | ffea1158 | fff3d8aa,fff35dfd,ffea9250,fff7eb73,fff3ee21,ffebab67,ffea5750,ffeeceac,fff297e2,fff527ee,fff53d8d,fff516ff,fff16f72,ffe |
| ffea678a | FUN_ffea678a | 10 | core2 | ffed04c3,ffea5750,ffed6822,ffecc23d,ffeaf5d4,ffed22ff,ffef0411,fff5f314,ffea8ea9,ffed2594,ffed6966 |  |
| ffea873d | FUN_ffea873d | 1415 | xref-0x801324(READ x1)<br>xref-0x822D62(READ x3) | ffea753f | ffea517c,ffec6639,ffea51b6,ffea8e57,ffea8ec4,ffec7edc,ffec66e9,ffea8e3d,ffeca60a,ffea8ea9,ffea51f5 |
| ffea8ec4 | FUN_ffea8ec4 | 155 | xref-0x801324(READ x1) | ffea873d | ffea7e71,ffecf45a,ffec08df |
| ffeab247 | FUN_ffeab247 | 495 | xref-0x8013D6(READ x8) | ffea95a5 | fff3eb59,ffea517c,fff3ea6d,ffeb7e41,fff3eb3b,ffeb7e6e,fff33340,fff3e6d1 |
| ffeac035 | FUN_ffeac035 | 343 | xref-0x8013D6(WRITE x3) | ffea9a91 | ffed3585,ffea4c78,ffea517c,ffea3f4a,ffea4170,ffea3f6f,ffea4c31 |
| ffeac3d9 | FUN_ffeac3d9 | 958 | xref-0x8013D6(WRITE x2) | ffea9a91 | ffec6639,ffec67e0,ffec67c3,ffea3ed8,ffec8399,fff2e975,fff2af3a |
| ffeb48dc | FUN_ffeb48dc | 487 | xref-0x8013C5(READ x5) | ffea9c5a | ffec8fa5,fff58e90,ffea3ed8,ffeca60a,ffea3e40 |
| ffeb8090 | FUN_ffeb8090 | 826 | xref-0x801324(READ x1) | ffeb83f4,ffea12a3 | ffeb849b,ffeb8dcb,ffeba159,ffeb89d6,ffeb9381,ffeb8cf6,ffeba5d8,ffea517c,ffeb874e,ffeba7dc,ffeb8d69,ffeb8a85,ffeb9ab4,ffe |
| ffeb84ab | FUN_ffeb84ab | 228 | xref-0x822D62(READ x1) | ffeb8090 | ffecdf26,ffec6639,ffec67c3,fff48dc6,ffece37e,ffeba6da,fff317bb |
| ffebab67 | FUN_ffebab67 | 2488 | xref-0x801324(READ x2) | ffebb539,ffea12a3 | ffebdb28,ffebc98d,ffebe722,ffebe8a5,ffebc1d8,ffebcb80,ffebda73,ffebbd2d,ffebc49d,ffebbe99,ffebc7db,ffebca7e,ffebd0e3,ffe |
| ffebc737 | FUN_ffebc737 | 164 | xref-0x822D62(READ x1) | ffebab67 | ffec7046,ffec6639,ffec6a72,ffecc24a,ffebfdaf,ffec6db2 |
| ffec08df | FUN_ffec08df | 57 | core2 | ffed09e9,ffed2594,fff36729,fff37237,fff36595,fff36625,fff3789b,ffea8ec4,fff373ba,fff3642a,fff38657,fff38762,fff36875,fff |  |
| ffec092b | FUN_ffec092b | 221 | xref-0x801324(READ x4) | ffed09e9,ffec0656,ffed246b,ffecef1c,ffecf887 | ffec8cd1,ffea51f5 |
| ffec0f4d | FUN_ffec0f4d | 1298 | xref-0x801324(READ x2) | ffea12a3 | ffecdf26,ffea74aa,ffea517c,fff85df3,ffecc467,ffea74cd,ffedcd19,ffea74e9,ffea65fd,ffea74c3,ffea750f,ffea51f5,ffec23df,ffe |
| ffec6562 | FUN_ffec6562 | 215 | xref-0x8013D6(READ x4) | ffec0f4d,ffec5ed7,ffec58ff | ffea517c,fff04852,ffea51f5,fff5eb38 |
| ffec6639 | FUN_ffec6639 | 176 | core2<br>xref-0x822D62(READ x1) | ffee18a5,fff524f0,ffeb0e4a,fff02600,ffeb7037,ffedad91,fff3531d,ffef32b1,ffeb2796,ffeedfc9,fff140ec,fff1414c,ffeb8896,fff |  |
| ffec7253 | FUN_ffec7253 | 72 | core2 | ffeae34d,ffee2b7f,ffedad91,ffede38c,fff452b9,ffef2c77,ffeca60a | ffec670f,ffec76f9 |
| ffec7edc | FUN_ffec7edc | 913 | xref-0x8013C5(WRITE x1) | ffed101f,ffed09e9,ffea873d,fff2a9d9,ffed1906,ffefaff3,fff5dc8a,fff38657,fff36378,fff5ca72 | ffec6b9b,ffec6639,ffec7a59,ffec85cc,ffece1e6 |
| ffec8cd1 | FUN_ffec8cd1 | 724 | xref-0x8013D6(READ x3) | ffec00ba,ffecf80f,ffed1ccd,fff32769,ffec092b,ffebb96f,ffecf887,ffec0442,ffebb8f3 | ffea7e71,ffec670f,ffec6639,fff48dc6,ffea6794 |
| ffec8fa5 | FUN_ffec8fa5 | 4695 | xref-0x8013D6(READ x5) | ffeb20c5,ffeb1cdf,ffeb1fe9,ffeb7037,ffeafb97,ffeeceac,fff026a7,ffeb2796,ffeb7c28,fff02918,ffeafa33,fff2af3a,ffeb75be,fff | ffeebd04,fff305e1,ffec69e1,ffec6b9b,ffec6639,fff5e98c,ffea65fd,fff3050f,fff303c8,ffef038e,ffec6e44,ffef3b62 |
| ffeca60a | FUN_ffeca60a | 29 | core2 | ffed09e9,ffea873d,ffea753f,ffeb48dc,fff5836e | ffec7253,ffec6639 |
| ffeca627 | FUN_ffeca627 | 214 | xref-0x822D62(READ x3) | ffec00ba,ffebbdc9 | ffea51f5,ffec670f,ffec6639,ffecc0ce,ffeca6fd,ffeca7e5,ffec86cf |
| ffece02e | FUN_ffece02e | 184 | xref-0x801324(READ x1) | ffed93c8,ffed9ee1,ffec63c5,ffedbd55,ffec145f,fff5ca72,fff5d5be | ffecdf26,ffec6639,ffebb529 |
| ffece2ab | FUN_ffece2ab | 211 | xref-0x8013D6(READ x4) | fff59043,ffed04c3,ffed0814 | ffec0708 |
| ffeced3b | FUN_ffeced3b | 481 | xref-0x17B54(WRITE x1)<br>xref-0x801324(WRITE x1) | ffea1158 | ffea517c,ffed2f31,fff425bb,ffecc0de,ffec85cc,ffea4200,ffecdc0a,ffecaa9e,fff42706 |
| ffecef1c | FUN_ffecef1c | 1342 | core2<br>xref-0x801324(READ x1) | ffea12a3 | ffea517c,ffed286d,ffed2934,ffed2f31,ffece120,ffecf504,ffed246b,ffed1ccd,ffed290e,ffed2696,ffec0a08,ffed1906,ffecf509,ffe |
| ffecf45a | FUN_ffecf45a | 15 | core2<br>xref-0x17B54(READ x1) | ffeb8896,ffea7e71,fff5c898,ffebb802,ffea8ec4,fff59043,ffeb726d,fff488be,ffec86cf |  |
| ffecf546 | FUN_ffecf546 | 713 | xref-0x801324(READ x1) | ffecf509 | ffea51f5,ffea517c,ffec69e1,ffec1ad8,ffec157b,ffec6afb,ffec6db2 |
| ffecf80f | FUN_ffecf80f | 120 | xref-0x801324(READ x2) | ffecf509 | ffec8cd1,ffed01ef,ffecfb7f |
| ffecf887 | FUN_ffecf887 | 760 | xref-0x801324(READ x2) | ffecf509 | ffecdf26,ffea517c,ffecfe1a,ffec8cd1,ffec17a9,ffec6639,fff5f904,ffed0357,fff5180d,ffec6a72,ffec0a08,ffec180b,ffec6db2,ffe |
| ffed09e9 | FUN_ffed09e9 | 1148 | xref-0x17B54(READ x2)<br>xref-0x801324(DATA x24) | ffecf509 | ffed101f,ffea517c,ffeca85a,ffec08cc,ffec080f,ffec0a20,ffec7edc,ffec06f0,ffec06d1,ffec0a08,ffeca60a,ffed2594,ffea51f5,ffe |
| ffed0e65 | FUN_ffed0e65 | 442 | xref-0x8013C5(READ x1) | ffed101f | ffea517c,ffea7e71,ffec670f,ffec6639,ffea5432,ffecc23d |
| ffed101f | FUN_ffed101f | 731 | xref-0x17B54(READ x4)<br>xref-0x801324(DATA x5)<br>xref-0x822D62(READ x4) | ffed09e9 | ffeeca18,ffea517c,ffec6639,ffea559f,ffea8018,ffed0e65,ffec7edc,ffea65fd,ffec6a72,ffec6db2,ffed12fa,ffea51f5,ffea7e71,ffe |
| ffed12fa | FUN_ffed12fa | 171 | xref-0x17B54(READ x1)<br>xref-0x822D62(READ x3) | ffed101f | ffea56ba,ffecc06e,ffea56c7 |
| ffed1906 | FUN_ffed1906 | 967 | xref-0x17B54(READ x1)<br>xref-0x8013D6(READ x3) | ffecef1c | ffecdf26,ffec6639,ffea5208,ffec7edc,ffec6afb |
| ffed2594 | FUN_ffed2594 | 258 | xref-0x801324(READ x1) | ffed09e9 | ffec07e9,ffea678a,ffea65fd,ffec07fc,ffec08df,ffec06b9 |
| ffed2934 | FUN_ffed2934 | 790 | xref-0x822D62(READ x3) | ffecef1c | ffea6d1e,ffec0b18,ffea5650,ffea51f5,ffec0b4b,ffec0cb0,ffea65fd,ffea5536,ffea562a,ffea4794,ffec0c76,ffec880b,ffea517c,fff |
| ffed2f31 | FUN_ffed2f31 | 1619 | xref-0x801324(READ x1) | ffecef1c,ffeced3b | fff190bc,ffea4bb5,ffea4a41,ffea4abd,ffea491e,fff85df3,ffea4add,ffea4a7f,ffea4b5a,ffea480e,ffea4afd,ffea4a9e,ffea4b3b,ffe |
| ffed5bc9 | FUN_ffed5bc9 | 345 | core2 | ffea1158,ffea12a3 | ffea6d1e,fff302d9,ffea51f5,ffee4b50,fff309b0,ffed4f18,fff309a1,ffed5d76,ffed70d8,ffed532a,ffeec11b,ffea517c,fff159f5,ffe |
| ffed6046 | FUN_ffed6046 | 186 | core2 | ffed5bc9 | ffed6a24,ffed6100,ffed65a7,ffed6822,ffed67f6,ffed6a82,ffed6ddf,ffea5432,ffed67e3,ffed6966,ffed6742,ffed6a53 |
| ffed93c8 | FUN_ffed93c8 | 2841 | xref-0x8013D6(READ x5) | ffed7a49 | ffec6639,ffece3b9,ffec69e1,ffedb227,ffedad6e,ffedbbbc,ffecb5f5,ffee4d82,ffec670f,ffedb32c,ffedb0b4,ffedb36e,ffece430,ffe |
| ffed9ee1 | FUN_ffed9ee1 | 3201 | xref-0x8013D6(READ x5)<br>xref-0x822D62(READ x2) | ffed7a49 | ffec6639,ffece3b9,ffec69e1,ffedb227,ffedad6e,ffedbbbc,ffecb5f5,ffee4d82,ffec670f,ffedb32c,ffedb0b4,ffedb36e,ffece430,ffe |
| ffedbbbc | FUN_ffedbbbc | 409 | xref-0x801324(READ x2) | ffed93c8,ffed9ee1 | fff283d5,ffea51f5,ffec6639,fff3f15e,fff3f17e,fff2838c,fff283e4,fff3f19e,fff2837d,fff28430,ffea517c,fff3f18e,fff28421,fff |
| ffeddd2f | FUN_ffeddd2f | 39 | core2 | ffefb8b2,fff57828,ffef2b21,ffeee205,fff585a7,fff58e90,fff58e61 | ffec670f,ffec6639 |
| ffee45e0 | FUN_ffee45e0 | 91 | xref-0x822D62(READ x1) | ffedda46,fff2d580 | ffec6639,ffec67c3,ffec7bdd |
| ffeec11b | FUN_ffeec11b | 438 | xref-0x8013D6(READ x3) | ffed5bc9 | ffec82e2,ffec67c3 |
| ffeed3de | FUN_ffeed3de | 169 | xref-0x8013C5(READ x2) | ffeeceac |  |
| ffef292a | FUN_ffef292a | 224 | xref-0x8013D6(READ x8) | fff00291,ffef48eb,ffef4983,ffef4c34,ffefb8b2,ffefdd98,ffefc688,ffeef934,ffefd18f,fff00196,fff56e1d,ffefc7b9,ffef1331,fff |  |
| ffef7979 | FUN_ffef7979 | 32 | core2 |  | fff588f2,fff584fc,fff5836e |
| ffef799f | FUN_ffef799f | 32 | core2 |  | fff588f2,fff584fc,fff5836e |
| ffef7a11 | FUN_ffef7a11 | 32 | core2 |  | fff588f2,fff584fc,fff5836e |
| ffef7add | FUN_ffef7add | 408 | xref-0x8013C5(READ x2) | ffefd18f | fff58c1c,ffea65fd |
| ffefc688 | FUN_ffefc688 | 305 | xref-0x8013D6(READ x3) |  | ffef038e,fff3050f,ffec670f,fff303c8,ffeed781,fff5175e,ffef0b9e,fff58125,fff305e1,ffefdba1,ffef3b3d,ffef292a |
| ffefd18f | FUN_ffefd18f | 1685 | xref-0x8013D6(WRITE x9) | fff02f1a,ffefcd01,ffef9083,fff00029,ffefba57,ffefb6a8,ffed70d8,fff00138,fff03acb,ffefdf89,fff0187b,fff000ce,ffefb8b2,fff | fff1bfa8,fff5f251,ffec6639,fff3f1ce,fff01c4d,ffefad33,ffef292a,ffef9b15,ffef9469,ffec67e0,ffeff42a,ffef3d11,ffef9bdb,ffe |
| ffefdd98 | FUN_ffefdd98 | 497 | xref-0x8013D6(READ x4) | fff026a7,fff02918,ffeb50c2,ffeb50c9 | fff303c8,ffeed781,ffec6639,ffecb2f8,ffecb818,ffea65fd,ffec6e44,fff58125,ffec6e65,fff5175e,fff3607b,ffef13f2,ffef292a,ffe |
| ffefdf89 | FUN_ffefdf89 | 3987 | xref-0x8013D6(READ x3) | fff06563,ffea9250 | fff337c4,fff0627a,ffec6639,fff024a7,ffef7803,ffef292a,ffeff42a,ffefef1c,fff33e36,fff3ea6d,ffece120,ffefd18f,ffef8949,fff |
| fff02600 | FUN_fff02600 | 91 | xref-0x822D62(READ x1) | fff0265b | ffec6639,ffec6a49,ffec69e1 |
| fff02f1a | FUN_fff02f1a | 1647 | xref-0x8013D6(WRITE x4) | ffefdf89,ffefef1c,fff5ee5d,ffefd18f,fff851b2 | ffee8fce,ffee8ee6,ffea65fd,fff5f144,ffefd18f |
| fff2847f | FUN_fff2847f | 708 | xref-0x822D62(READ x1) | fff28319 | ffea5208,fff86542,ffec7a59,fff28ee9,fff864bc,fff28e78,fff86090 |
| fff2936f | FUN_fff2936f | 574 | xref-0x822D62(READ x2) | fff28319 | ffec084d,ffec0b18,ffea65fd,ffea568d,ffecc06e,ffea5683 |
| fff31b8f | FUN_fff31b8f | 1241 | xref-0x801324(READ x1) | fff3178e | ffecdf26,ffece205,ffec7a59,ffea51f5,ffec6c2b,ffec6b4b,ffec08cc,ffea69e6,fff332e8 |
| fff386e4 | FUN_fff386e4 | 78 | xref-0x822D62(READ x1) | fff382d5 | fff283a9,ffea51f5,ffea517c,ffec08df |
| fff387fa | FUN_fff387fa | 107 | xref-0x822D62(READ x1) | fff382d5 | fff283a9,ffea51f5,ffea517c |
| fff4b6f6 | FUN_fff4b6f6 | 124 | xref-0x8013D6(READ x3) | fff48deb,fff48df2 |  |
| fff51882 | FUN_fff51882 | 760 | xref-0x822D62(READ x3) | fff516ff | fff51cb0,fff51b7a,fff51c51,fff5237e,fff51cd2,ffea51f5,fff51b9b,fff51c73,fff5231a,fff525a5,fff522e5,ffea517c,fff526bf,fff |
| fff527ee | FUN_fff527ee | 1225 | xref-0x8013D6(READ x2)<br>xref-0x822D62(READ x1) | ffea12a3 | fff53273,fff5334b,ffec6639,fff52ef1,ffeb83d4,ffea419e,ffea51f5,ffec67a0,ffea65fd,fff53c21,ffea517c,fff53beb,ffecb7e2,fff |
| fff576c7 | FUN_fff576c7 | 353 | xref-0x8013C5(READ x2)<br>xref-0x83B2C8(READ x12) | fff576bd | ffec0708 |
| fff57828 | FUN_fff57828 | 408 | xref-0x83B2C8(READ x14) | fff576bd | fff58cf2,ffeddd2f,ffea7fc8,ffeb7f9c,ffeb7fab |
| fff579c0 | FUN_fff579c0 | 676 | xref-0x8013C5(READ x4)<br>xref-0x83B2C8(READ x25) | fff576bd | fff58d18,ffea65fd,ffedcd19 |
| fff57c64 | FUN_fff57c64 | 579 | xref-0x83B2C8(READ x18) | ffef872f | ffea7fc8,fff58e90,ffea65fd,fff5175e,ffea517c,fff58e61,ffef292a |
| fff58125 | FUN_fff58125 | 291 | xref-0x83B2C8(READ x11) | ffefdd98,ffefc7b9,ffefc688,ffefcb12,ffefbc6c |  |
| fff58248 | FUN_fff58248 | 137 | xref-0x83B2CC(READ x7) | ffea12a3 | ffea51f5 |
| fff5836e | FUN_fff5836e | 398 | xref-0x8013C5(READ x3)<br>xref-0x83B2CC(READ x15) | ffef7979,ffef799f,ffef7a11 | fff58a5e,fff58e90,ffea65fd,ffeca60a,fff58e61 |
| fff584fc | FUN_fff584fc | 171 | core2<br>xref-0x83B2CC(READ x6) | ffef7979,ffef799f,ffef7a11 | fff589ba,fff58c1c,fff58e90 |
| fff585a7 | FUN_fff585a7 | 843 | xref-0x8013C5(READ x4)<br>xref-0x83B2CC(READ x27) |  | ffeddd2f,fff58c1c,ffea65fd,fff58b12 |
| fff588f2 | FUN_fff588f2 | 200 | core2<br>xref-0x83B2CC(READ x6) | ffef7979,ffef799f,ffef7a11 | fff589ba,fff58c1c,fff58e90,ffea65fd |
| fff589ba | FUN_fff589ba | 164 | xref-0x83B2CC(READ x4) | fff588f2,fff584fc | fff58c1c,fff58cf2,fff58d73,fff58bde,fff58e61 |
| fff58a5e | FUN_fff58a5e | 180 | xref-0x83B2CC(READ x7) | fff5836e | fff58b87,fff58cf2,fff58b12,fff58bde |
| fff58b12 | FUN_fff58b12 | 30 | xref-0x83B2CC(READ x1) | fff58a5e,fff585a7,ffeb1cdf | ffea517c |
| fff58b30 | FUN_fff58b30 | 87 | xref-0x83B2CC(READ x4) |  | ffea7ff2,ffea65fd,ffea7fc8 |
| fff58b87 | FUN_fff58b87 | 87 | xref-0x83B2CC(READ x4) | fff58a5e | ffee3484,fff58bde |
| fff58bde | FUN_fff58bde | 62 | xref-0x83B2CC(READ x3) | fff589ba,fff58a5e,fff58b87,ffeb1a6b |  |
| fff58c1c | FUN_fff58c1c | 85 | xref-0x83B2CC(READ x5) | fff589ba,fff585a7,ffeb1a6b,fff588f2,ffef7add,fff58d73,fff584fc |  |
| fff58d18 | FUN_fff58d18 | 91 | core2<br>xref-0x83B2CC(READ x5) | fff579c0 |  |
| fff58d73 | FUN_fff58d73 | 189 | xref-0x83B2CC(READ x6) | fff589ba | fff58e30,fff58c1c,fff58c71,ffea65fd |
| fff58e30 | FUN_fff58e30 | 49 | xref-0x83B2CC(READ x1) | ffeb1a6b,fff58d73 |  |
| fff58e61 | FUN_fff58e61 | 47 | core2 | fff589ba,fff57c64,fff5836e | ffeddd2f |
| fff58e90 | FUN_fff58e90 | 37 | core2 | fff57c64,ffeb1cdf,ffeb48dc,fff588f2,fff584fc,fff5836e | ffeddd2f |
| fff58eb5 | FUN_fff58eb5 | 207 | xref-0x83B2CC(READ x1) | ffee30a5 | fff58f84 |
| fff59043 | FUN_fff59043 | 2102 | xref-0x822D62(READ x3) | ffea12a3 | ffec69e1,ffec6639,fff59e26,ffea4c11,ffec18de,ffea51f5,fff48deb,ffec670f,ffea74e9,fff59a49,ffea5723,ffea569d,ffea41d6,fff |
| fff5c898 | FUN_fff5c898 | 464 | xref-0x801324(READ x4) | fff59043 | fff59890,ffec6639,ffea74e9,ffecc108,ffec0b7e,ffecf45a,ffea517c,ffea51f5,ffec0b99 |
| fff5ca72 | FUN_fff5ca72 | 625 | xref-0x822D62(READ x3) | ffea12a3 | fff5cd3e,ffec670f,ffece02e,ffec145f,fff5d469,ffea5723,ffec7edc,ffea65fd,fff5cce3,ffea51f5,ffea517c |
| fff5f979 | FUN_fff5f979 | 757 | xref-0x822D62(READ x3) | fff516ff | fff5fc6e,fff5fda4,fff60726,fff5fcc5,fff602e1,fff60460,ffea51f5,fff5fdc6,fff60669,fff6048f,fff60783,fff603fc,fff5fd45,fff |
| fff80681 | FUN_fff80681 | 717 | xref-0x8013D6(READ x3) | fff8059b | ffec670f,ffefb1b2,ffea65fd,ffea517c,ffea51f5,fff85867 |

# 数据地址 xref 汇总

## 0x8013C5 (9 funcs)
- ffeb48dc FUN_ffeb48dc x5 READ
- fff579c0 FUN_fff579c0 x4 READ
- fff585a7 FUN_fff585a7 x4 READ
- fff5836e FUN_fff5836e x3 READ
- fff576c7 FUN_fff576c7 x2 READ
- ffeed3de FUN_ffeed3de x2 READ
- ffef7add FUN_ffef7add x2 READ
- ffed0e65 FUN_ffed0e65 x1 READ
- ffec7edc FUN_ffec7edc x1 WRITE

## 0x801324 (19 funcs)
- ffed09e9 FUN_ffed09e9 x24 DATA
- ffed101f FUN_ffed101f x5 DATA
- ffec092b FUN_ffec092b x4 READ
- fff5c898 FUN_fff5c898 x4 READ
- ffec0f4d FUN_ffec0f4d x2 READ
- ffebab67 FUN_ffebab67 x2 READ
- ffedbbbc FUN_ffedbbbc x2 READ
- ffecf887 FUN_ffecf887 x2 READ
- ffecf80f FUN_ffecf80f x2 READ
- ffea873d FUN_ffea873d x1 READ
- ffed2594 FUN_ffed2594 x1 READ
- ffeb8090 FUN_ffeb8090 x1 READ
- ffece02e FUN_ffece02e x1 READ
- ffed2f31 FUN_ffed2f31 x1 READ
- ffecef1c FUN_ffecef1c x1 READ
- ffea8ec4 FUN_ffea8ec4 x1 READ
- ffeced3b FUN_ffeced3b x1 WRITE
- ffecf546 FUN_ffecf546 x1 READ
- fff31b8f FUN_fff31b8f x1 READ

## 0x822D62 (53 funcs)
- ffed101f FUN_ffed101f x4 READ
- ffea873d FUN_ffea873d x3 READ
- ffeca627 FUN_ffeca627 x3 READ
- fff5ca72 FUN_fff5ca72 x3 READ
- ffed2934 FUN_ffed2934 x3 READ
- ffed12fa FUN_ffed12fa x3 READ
- fff59043 FUN_fff59043 x3 READ
- fff5f979 FUN_fff5f979 x3 READ
- fff51882 FUN_fff51882 x3 READ
- fff2936f FUN_fff2936f x2 READ
- ffed9ee1 FUN_ffed9ee1 x2 READ
- fff527ee FUN_fff527ee x1 READ
- fff387fa FUN_fff387fa x1 READ
- ffebc737 FUN_ffebc737 x1 READ
- fff386e4 FUN_fff386e4 x1 READ
- ffec6639 FUN_ffec6639 x1 READ
- fff02600 FUN_fff02600 x1 READ
- ffee45e0 FUN_ffee45e0 x1 READ
- ffeb84ab FUN_ffeb84ab x1 READ
- fff2847f FUN_fff2847f x1 READ
- ffed246b FUN_ffed246b x1 READ
- ffec0442 FUN_ffec0442 x1 READ
- ffed22ff FUN_ffed22ff x1 READ
- ffeb022d FUN_ffeb022d x1 READ
- fff4812c FUN_fff4812c x1 READ
- ffecc108 FUN_ffecc108 x1 READ
- ffeb8090 FUN_ffeb8090 x1 READ
- fff3ee21 FUN_fff3ee21 x1 READ
- ffeced3b FUN_ffeced3b x1 WRITE
- ffee4d02 FUN_ffee4d02 x1 READ
- ffec8cd1 FUN_ffec8cd1 x1 READ
- ffed2c4a FUN_ffed2c4a x1 READ
- ffec8ba2 FUN_ffec8ba2 x1 READ
- ffebab67 FUN_ffebab67 x1 READ
- ffec092b FUN_ffec092b x1 READ
- fff34887 FUN_fff34887 x1 READ
- fff5c898 FUN_fff5c898 x1 READ
- fff317bb FUN_fff317bb x1 READ
- ffec51d4 FUN_ffec51d4 x1 READ
- ffecdf26 FUN_ffecdf26 x1 READ
- ffedbf0f FUN_ffedbf0f x1 READ
- ffebbe99 FUN_ffebbe99 x1 READ
- ffedbe73 FUN_ffedbe73 x1 READ
- ffebdcba FUN_ffebdcba x1 READ
- ffedbbbc FUN_ffedbbbc x1 READ
- fff31b8f FUN_fff31b8f x1 READ
- fff45b73 FUN_fff45b73 x1 READ
- fff5dafb FUN_fff5dafb x1 READ
- ffed7a49 FUN_ffed7a49 x1 READ
- fff49a1a FUN_fff49a1a x1 READ
- ffed1906 FUN_ffed1906 x1 READ
- ffebb802 FUN_ffebb802 x1 READ
- fff05eb4 FUN_fff05eb4 x1 READ

## 0x17B54 (6 funcs)
- ffed101f FUN_ffed101f x4 READ
- ffed09e9 FUN_ffed09e9 x2 READ
- ffeced3b FUN_ffeced3b x1 WRITE
- ffecf45a FUN_ffecf45a x1 READ
- ffed12fa FUN_ffed12fa x1 READ
- ffed1906 FUN_ffed1906 x1 READ

## 0x8013D6 (123 funcs)
- ffefd18f FUN_ffefd18f x9 WRITE
- ffef292a FUN_ffef292a x8 READ
- ffeab247 FUN_ffeab247 x8 READ
- ffec8fa5 FUN_ffec8fa5 x5 READ
- ffed93c8 FUN_ffed93c8 x5 READ
- ffed9ee1 FUN_ffed9ee1 x5 READ
- ffec6562 FUN_ffec6562 x4 READ
- ffece2ab FUN_ffece2ab x4 READ
- fff02f1a FUN_fff02f1a x4 WRITE
- ffefdd98 FUN_ffefdd98 x4 READ
- fff80681 FUN_fff80681 x3 READ
- ffeec11b FUN_ffeec11b x3 READ
- ffeac035 FUN_ffeac035 x3 WRITE
- ffec8cd1 FUN_ffec8cd1 x3 READ
- fff4b6f6 FUN_fff4b6f6 x3 READ
- ffefdf89 FUN_ffefdf89 x3 READ
- ffed1906 FUN_ffed1906 x3 READ
- ffefc688 FUN_ffefc688 x3 READ
- fff527ee FUN_fff527ee x2 READ
- ffeac3d9 FUN_ffeac3d9 x2 WRITE
- fff58125 FUN_fff58125 x2 READ
- ffec0f4d FUN_ffec0f4d x2 READ
- fff48ed0 FUN_fff48ed0 x2 READ
- ffefcd01 FUN_ffefcd01 x2 READ
- fff7eaac FUN_fff7eaac x2 WRITE
- ffea95a5 FUN_ffea95a5 x2 READ
- ffef9469 FUN_ffef9469 x2 READ
- fff57c64 FUN_fff57c64 x2 WRITE
- fff579c0 FUN_fff579c0 x2 WRITE
- fff49889 FUN_fff49889 x2 WRITE
- ffefd824 FUN_ffefd824 x2 READ
- fff047aa FUN_fff047aa x1 WRITE
- ffefc7b9 FUN_ffefc7b9 x1 READ
- ffeb2796 FUN_ffeb2796 x1 READ
- ffec670f FUN_ffec670f x1 READ
- ffed2696 FUN_ffed2696 x1 READ
- fff5a603 FUN_fff5a603 x1 READ
- ffec23df FUN_ffec23df x1 READ
- ffec8399 FUN_ffec8399 x1 READ
- ffee6337 FUN_ffee6337 x1 READ
- fff4a2c1 FUN_fff4a2c1 x1 READ
- fff00291 FUN_fff00291 x1 READ
- ffece1e6 FUN_ffece1e6 x1 READ
- fff04165 FUN_fff04165 x1 READ
- ffec413e FUN_ffec413e x1 READ
- ffed6100 FUN_ffed6100 x1 WRITE
- ffece0e6 FUN_ffece0e6 x1 READ
- fff3efc5 FUN_fff3efc5 x1 READ
- fff48f6a FUN_fff48f6a x1 READ
- ffeeaf77 FUN_ffeeaf77 x1 READ
- ffed0e65 FUN_ffed0e65 x1 READ
- ffefce30 FUN_ffefce30 x1 READ
- ffeaed94 FUN_ffeaed94 x1 READ
- fff16cc7 FUN_fff16cc7 x1 WRITE
- fff02bdb FUN_fff02bdb x1 READ
- fff7eb73 FUN_fff7eb73 x1 READ
- ffefcb12 FUN_ffefcb12 x1 READ
- ffeb8a85 FUN_ffeb8a85 x1 READ
- fff349e1 FUN_fff349e1 x1 READ
- fff2e975 FUN_fff2e975 x1 READ
- ffed2934 FUN_ffed2934 x1 READ
- fff34932 FUN_fff34932 x1 READ
- ffed08e7 FUN_ffed08e7 x1 READ
- ffeb48dc FUN_ffeb48dc x1 READ
- fff1682b FUN_fff1682b x1 WRITE
- ffed0814 FUN_ffed0814 x1 READ
- fff297e2 FUN_fff297e2 x1 READ
- fff35705 FUN_fff35705 x1 READ
- ffefb6a8 FUN_ffefb6a8 x1 READ
- ffea753f FUN_ffea753f x1 READ
- ffeed487 FUN_ffeed487 x1 READ
- ffefb3c2 FUN_ffefb3c2 x1 READ
- ffef33af FUN_ffef33af x1 READ
- fff85376 FUN_fff85376 x1 WRITE
- fff332e8 FUN_fff332e8 x1 READ
- ffead25e FUN_ffead25e x1 READ
- fff291cb FUN_fff291cb x1 READ
- ffefb1b2 FUN_ffefb1b2 x1 READ
- ffec311d FUN_ffec311d x1 READ
- ffed70d8 FUN_ffed70d8 x1 READ
- ffef3085 FUN_ffef3085 x1 READ
- fff59043 FUN_fff59043 x1 READ
- ffeb9fc2 FUN_ffeb9fc2 x1 READ
- ffedbf0f FUN_ffedbf0f x1 READ
- ffedbec3 FUN_ffedbec3 x1 READ
- fff81ea6 FUN_fff81ea6 x1 WRITE
- ffeb9e8a FUN_ffeb9e8a x1 READ
- ffed1ccd FUN_ffed1ccd x1 READ
- ffefbc6c FUN_ffefbc6c x1 READ
- ffeb9c2d FUN_ffeb9c2d x1 READ
- ffeadc15 FUN_ffeadc15 x1 READ
- fff03be8 FUN_fff03be8 x1 WRITE
- ffec3bb8 FUN_ffec3bb8 x1 READ
- ffefbba0 FUN_ffefbba0 x1 READ
- ffefdba1 FUN_ffefdba1 x1 READ
- fff03b81 FUN_fff03b81 x1 READ
- ffeb1a6b FUN_ffeb1a6b x1 READ
- ffefba57 FUN_ffefba57 x1 READ
- fff358ce FUN_fff358ce x1 READ
- ffefb8b2 FUN_ffefb8b2 x1 READ
- ffecf887 FUN_ffecf887 x1 READ
- ffeed84a FUN_ffeed84a x1 READ
- fff19c9a FUN_fff19c9a x1 READ
- nofunc@fff14692 ? x1 READ
- nofunc@fff146c3 ? x1 WRITE
- nofunc@fff01cf4 ? x1 WRITE
- nofunc@ffefd097 ? x1 READ
- nofunc@ffefd16d ? x1 READ
- nofunc@ffefae6a ? x1 READ
- nofunc@ffefaee4 ? x1 READ
- nofunc@ffef952a ? x1 READ
- nofunc@ffef913e ? x1 READ
- nofunc@ffef91e2 ? x1 READ
- nofunc@ffef9288 ? x1 READ
- nofunc@ffef932e ? x1 READ
- nofunc@ffef93d4 ? x1 READ
- nofunc@ffef9629 ? x1 READ
- nofunc@ffef986f ? x1 READ
- nofunc@ffef990c ? x1 READ
- nofunc@ffef994b ? x1 READ
- nofunc@ffef998a ? x1 READ
- nofunc@ffef99c9 ? x1 READ
- nofunc@ffef9a08 ? x1 READ

## 0x83B2C8 (5 funcs)
- fff579c0 FUN_fff579c0 x25 READ
- fff57c64 FUN_fff57c64 x18 READ
- fff57828 FUN_fff57828 x14 READ
- fff576c7 FUN_fff576c7 x12 READ
- fff58125 FUN_fff58125 x11 READ

## 0x83B2CC (16 funcs)
- fff585a7 FUN_fff585a7 x27 READ
- fff5836e FUN_fff5836e x15 READ
- fff58248 FUN_fff58248 x7 READ
- fff58a5e FUN_fff58a5e x7 READ
- fff584fc FUN_fff584fc x6 READ
- fff588f2 FUN_fff588f2 x6 READ
- fff58d73 FUN_fff58d73 x6 READ
- fff58d18 FUN_fff58d18 x5 READ
- fff58c1c FUN_fff58c1c x5 READ
- fff589ba FUN_fff589ba x4 READ
- fff58b30 FUN_fff58b30 x4 READ
- fff58b87 FUN_fff58b87 x4 READ
- fff58bde FUN_fff58bde x3 READ
- fff58eb5 FUN_fff58eb5 x1 READ
- fff58e30 FUN_fff58e30 x1 READ
- fff58b12 FUN_fff58b12 x1 READ
