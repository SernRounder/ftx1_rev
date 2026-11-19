#!/usr/bin/env python
# merge_display.py — 无源码向 DISPLAY 固件打包新功能(FT8 项目)
#
# 流程: 解包后的 display.bin ← 注入 payload 到 0xFF 空洞 + 可选钩子补丁
#       → decode_sfl.py pack 重编码(该工具写的头 CRC 有 bug, 本脚本重算覆盖)
#       → 输出可经官方 microSD 更新流程刷写的 .SFL
#
# 用法: python -I merge_display.py [--payload stage1.bin@0x12c670] [--hook file off orig... new...] -o out.sfl
# 安全: 拒绝覆盖原厂 SFL; 注入前校验目标区全为 0xFF; 钩子补丁前校验原字节; 产出后做往返复验。

import argparse, hashlib, pathlib, struct, subprocess, sys, tempfile, zlib

PATCH_DIR = pathlib.Path(__file__).resolve().parent
if str(PATCH_DIR) not in sys.path:
    sys.path.insert(0, str(PATCH_DIR))
from sq9pd_apply import apply_sq9pd_display_payload

ROOT = PATCH_DIR.parent
DEC = ROOT / 'work/dec'
DISPLAY_DIR = DEC / 'display'          # decode_sfl.py extract 的目录
PACKER = ROOT / 'work/tools/ft710-internals/decode_sfl.py'
SFL_MAGIC = bytes.fromhex('8f93c635')
CRC_FIELD = 0x220                       # 8 字节 ASCII 大写 hex
HOLE1 = (0x12c66c, 0x12f14a)            # FUNC 菜单白色像素，仅重定向绘制后可用
FUNC_TILE_CALL = 0x38868
TAIL_TILE_VECTOR = 0x2c3040
DISPLAY_COPY_LIMIT = 0x2d0000           # supported image window ends at 0x606d0000

def crc_ascii(payload: bytes) -> bytes:
    return f'{zlib.crc32(payload + SFL_MAGIC) & 0xFFFFFFFF:08X}'.encode('ascii')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--payload', default=None, help='payload.bin@fileoff')
    ap.add_argument('--s2', default=None, help='stage2.bin(镜像尾追加, 实验性: 需先验证加载机制)')
    ap.add_argument('--hook', action='append', default=[], help='off:orig_hex:new_hex (原字节校验+替换)')
    ap.add_argument('--no-sq9pd', action='store_true', help='跳过 sq9pd SWR/自定义按钮基础补丁')
    ap.add_argument('-o', '--out', required=True)
    args = ap.parse_args()

    img = bytearray((DISPLAY_DIR / 'display.bin').read_bytes())
    base_len = len(img)
    pristine = bytes(img)
    print(f'[*] 原像 {base_len} 字节  sha256 {hashlib.sha256(img).hexdigest()[:16]}...')

    # 0) 应用 sq9pd DISPLAY 基础补丁 (SWR SCAN + 自定义按钮框架)
    if not args.no_sq9pd:
        apply_sq9pd_display_payload(img)
        print(f'[+] 已应用 sq9pd DISPLAY 补丁  sha256 {hashlib.sha256(img).hexdigest()[:16]}...')

    # 1) payload 注入到空洞
    if args.payload:
        ppath, off = args.payload.split('@')
        off = int(off, 0)
        data = pathlib.Path(ppath).read_bytes()
        lo, hi = HOLE1
        assert lo <= off and off + len(data) <= hi, f'payload 越出空洞 [{lo:#x},{hi:#x})'
        payload_start, payload_end = off, off + len(data)
        hole = img[off:off + len(data)]
        assert all(b == 0xFF for b in hole), '目标区非全 0xFF, 拒绝注入(空洞定位可能失效)'
        img[off:off + len(data)] = data
        print(f'[+] payload {len(data)} 字节 @ {off:#x} (运行时 {0x60400000+off:#x})')

    # 2) Stage2 镜像尾追加(实验路径: 更新器/boot 是否跟随新长度未验证)
    if args.s2:
        s2 = pathlib.Path(args.s2).read_bytes()
        img += s2
        if len(img) > DISPLAY_COPY_LIMIT:
            ap.error(f'DISPLAY payload exceeds the stock boot copy limit {DISPLAY_COPY_LIMIT:#x}')
        print(f'[+] stage2 {len(s2)} 字节追加至镜像尾(总长 {len(img)}, 实验性)')

    # 3) 钩子补丁(先校验原字节)
    for h in args.hook:
        off_s, orig_s, new_s = h.split(':')
        off, orig, new = int(off_s, 0), bytes.fromhex(orig_s), bytes.fromhex(new_s)
        assert len(orig) == len(new), '钩子补丁长度不一致'
        cur = bytes(img[off:off + len(orig)])
        assert cur == orig, f'钩子 {off:#x} 原字节不符: 期望 {orig.hex()} 实际 {cur.hex()}'
        img[off:off + len(orig)] = new
        print(f'[+] hook {off:#x}: {orig.hex()} -> {new.hex()}')

    if args.payload:
        call, = struct.unpack_from('<I', img, FUNC_TILE_CALL)
        displacement = ((call & 0xffffff) ^ 0x800000) - 0x800000
        target = FUNC_TILE_CALL + 8 + 4 * displacement
        in_tail = False
        if args.s2 and target == TAIL_TILE_VECTOR and target + 4 <= len(img):
            branch, = struct.unpack_from('<I', img, target)
            delta = ((branch & 0xffffff) ^ 0x800000) - 0x800000
            in_tail = branch >> 24 == 0xea and TAIL_TILE_VECTOR < target + 8 + 4 * delta < len(img)
        if call >> 24 != 0xeb or not (payload_start <= target < payload_end or in_tail):
            ap.error('FUNC tile pixels can only be reused with the stock draw call redirected to a payload entry')

    assert bytes(img) != pristine or not (args.payload or args.s2 or args.hook), '无任何改动?'

    # 4) 重封包(在临时目录副本上进行, 不污染 work/dec/display 原始解包)
    out = pathlib.Path(args.out).resolve()
    assert out != (ROOT / 'work/fw/FTX-1_DISPLAY_V0110.SFL').resolve(), '禁止覆盖原厂文件'
    env = dict(__import__('os').environ, PYTHONIOENCODING='utf-8')
    with tempfile.TemporaryDirectory() as workdir:
        wd = pathlib.Path(workdir)
        candidate = wd / 'candidate.sfl'
        for f in DISPLAY_DIR.iterdir():
            if f.is_file():
                (wd / f.name).write_bytes(f.read_bytes())
        # The stock extractor rstrips trailing 0x0D/0x0A from the ciphertext, so
        # an unlucky last byte silently shortens the round-trip by one. Pad the
        # image with harmless zeros and repack until the round-trip is exact.
        for attempt in range(4):
            if len(img) > DISPLAY_COPY_LIMIT:
                ap.error('SFL round-trip padding would exceed the stock DISPLAY boot copy limit')
            (wd / 'display.bin').write_bytes(bytes(img))
            r = subprocess.run([sys.executable, '-I', str(PACKER), 'pack', '--rebuild', str(wd), str(candidate)],
                               capture_output=True, text=True, env=env)
            if r.returncode:
                print(r.stdout, r.stderr); sys.exit('pack 失败')
            rr = subprocess.run([sys.executable, '-I', str(PACKER), 'extract', str(candidate), str(wd / 'verify')],
                                capture_output=True, text=True, env=env)
            if rr.returncode:
                print(rr.stdout, rr.stderr); sys.exit('复验解包失败')
            rb = (wd / 'verify' / 'display.bin').read_bytes()
            if rb == bytes(img):
                break
            if len(rb) < len(img) and len(img) - len(rb) <= 2:
                img += bytes(len(img) - len(rb))  # zero-pad and retry
                continue
            assert False, '往返不一致!'
        else:
            sys.exit('往返复验多次失败')
        # 工具写的头 CRC 有 bug(对 DISPLAY), 重算覆盖
        blob = bytearray(candidate.read_bytes())
        good = crc_ascii(bytes(blob[0x240:]))
        bad = bytes(blob[CRC_FIELD:CRC_FIELD + 8])
        blob[CRC_FIELD:CRC_FIELD + 8] = good
        out.write_bytes(bytes(blob))
        print(f'[*] 头 CRC 工具值 {bad.decode(errors="replace")} -> 正确值 {good.decode()} (crc32(载荷+8F93C635))')

        # 5) 往返复验已在上方重试循环内完成
    final = out.read_bytes()
    print(f'[OK] {out.name}: {len(final)} 字节  sha256 {hashlib.sha256(final).hexdigest()}')
    print('[OK] 往返复验通过')

if __name__ == '__main__':
    main()
