"""Cross-link the receiver for ARM without changing the menu SFL."""

import argparse
import math
import struct
import subprocess
from pathlib import Path

from elftools.elf.elffile import ELFFile

from build_ft8_menu import HOLE_OFFSET, IMAGE_BASE, TRACE_REGIONS, ZIG
from test_ft8_rx import CORE_SOURCES, LIB, PATCH


BUILD = PATCH / "build"
ARM_ADDRESS = 0x606C2FC0


def write_native_pulse(build):
    # The even GFSK pulse is sampled every 16 PCM samples and interpolated.
    samples = []
    for index in range(241):
        t = index / 160
        samples.append((math.erf(10.672892 * (t + 0.5)) -
                        math.erf(10.672892 * (t - 0.5))) / 2)
    # Elide constant bins without changing any float32 interpolation inputs.
    assert all(struct.pack("<f", value) == struct.pack("<f", 1.0) for value in samples[:23])
    assert not any(samples[168:])
    samples = samples[22:169]
    rows = [", ".join(f"{value:.9e}f" for value in samples[i:i + 8])
            for i in range(0, len(samples), 8)]
    (build / "ft8_native_pulse.h").write_text(",\n".join(rows) + "\n", encoding="ascii")


def write_native_decoder(build):
    # Keep the pinned library intact and bound its existing Costas search for native AUTO RX.
    source = (LIB / "ft8/decode.c").read_text(encoding="utf-8")
    changes = (
        ("ftx_find_candidates(const ftx_waterfall_t* wf, int num_candidates, ftx_candidate_t heap[], int min_score)",
         "ftx_find_candidates_in_band(const ftx_waterfall_t* wf, int num_candidates, ftx_candidate_t heap[], "
         "int min_score, int first_bin, int last_bin, int first_time, int last_time, "
         "int heap_size, int finish)"),
        ("    int heap_size = 0;", "    if (last_bin > wf->num_bins - num_tones)\n"
         "        last_bin = wf->num_bins - num_tones;"),
        ("candidate.time_offset = -10; candidate.time_offset < 20;",
         "candidate.time_offset = first_time; candidate.time_offset < last_time;"),
        ("candidate.freq_offset = 0; (candidate.freq_offset + num_tones - 1) < wf->num_bins;",
         "candidate.freq_offset = first_bin; candidate.freq_offset <= last_bin;"),
        ("                    candidate.score = sync_fun(wf, &candidate);",
         "                    if (!(candidate.freq_offset & 31) && ft8_radio_decode_expired())\n"
         "                        goto sort;\n"
         "                    if (finish && candidate.freq_offset && !(candidate.freq_offset & 255) &&\n"
         "                        ft8_radio_decode_pause(1))\n"
         "                        goto sort;\n"
         "                    candidate.score = sync_fun(wf, &candidate);"),
        ("    int len_unsorted = heap_size;", "sort:\n    if (!finish) return heap_size;\n    int len_unsorted = heap_size;"),
    )
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError(f"Unexpected ft8_lib decoder source around {old}")
        source = source.replace(old, new)
    stages = (
        ("        ft8_extract_likelihood(wf, cand, log174);",
         "        PROFILE_START(llr);\n        ft8_extract_likelihood(wf, cand, log174);\n"
         "        PROFILE_END(llr, PROF_LLR, 0);"),
        ("    ftx_normalize_logl(log174);",
         "    PROFILE_START(normalize);\n    ftx_normalize_logl(log174);\n"
         "    PROFILE_END(normalize, PROF_NORMALIZE, 0);"),
        ("    uint8_t a91[FTX_LDPC_K_BYTES];",
         "    PROFILE_START(crc);\n    uint8_t a91[FTX_LDPC_K_BYTES];"),
        ("    if (status->crc_extracted != status->crc_calculated)",
         "    PROFILE_END(crc, PROF_CRC, status->crc_extracted == status->crc_calculated);\n"
         "    if (status->crc_extracted != status->crc_calculated)"),
        ("    int len_unsorted = heap_size;",
         "    PROFILE_START(sort_time);\n    int len_unsorted = heap_size;"),
        ("    return heap_size;\n}",
         "    PROFILE_END(sort_time, PROF_SORT, heap_size);\n    return heap_size;\n}"),
    )
    for old, new in stages:
        if source.count(old) != 1:
            raise ValueError(f"Unexpected ft8_lib profiling entry around {old}")
        source = source.replace(old, new)
    path = build / "ft8_native_decode.c"
    path.write_text('#include "ft8_profile.h"\nint ft8_radio_decode_expired(void);\n'
                    "int ft8_radio_decode_pause(unsigned sleep);\n" + source, encoding="utf-8")
    return path


def write_native_ldpc(build):
    source = (LIB / "ft8/ldpc.c").read_text(encoding="utf-8")
    loop = "    for (int iter = 0; iter < max_iters; ++iter)\n    {\n"
    if source.count(loop) != 2:
        raise ValueError("Unexpected ft8_lib LDPC iteration loop")
    source = source.replace(loop, "    int iter = 0;\n    for (; iter < max_iters; ++iter)\n    {\n"
                            "        if (ft8_radio_decode_expired())\n"
                            "            break;\n", 1)
    source = source.replace("    int16_t channel[FTX_LDPC_N];",
                            "    PROFILE_START(ldpc);\n    int16_t channel[FTX_LDPC_N];", 1)
    source = source.replace("        if (!errors)\n            return;",
                            "        if (!errors)\n            break;", 1)
    source = source.replace("\n}\n#else\nvoid bp_decode", "\n"
                            "    PROFILE_END(ldpc, PROF_LDPC, (iter << 8) | *ok);\n"
                            "}\n#else\nvoid bp_decode", 1)
    path = build / "ft8_native_ldpc.c"
    path.write_text('#include "ft8_profile.h"\nint ft8_radio_decode_expired(void);\n' + source,
                    encoding="utf-8")
    return path


def write_native_message(build):
    source = (LIB / "ft8/message.c").read_text(encoding="utf-8")
    old = """        c11[i] = charn(n58 % 38, FT8_CHAR_TABLE_ALPHANUM_SPACE_SLASH);
        if (i == 0)
            break;
        n58 /= 38;"""
    # Long division in base 65536 keeps each limb within uint32_t and
    # avoids linking the generic 64-bit division runtime.
    new = """        const uint32_t high = (uint32_t)(n58 >> 32);
        const uint32_t middle = (high % 38 << 16) | ((uint32_t)n58 >> 16);
        const uint32_t low = (middle % 38 << 16) | (uint16_t)n58;
        c11[i] = charn(low % 38, FT8_CHAR_TABLE_ALPHANUM_SPACE_SLASH);
        if (i == 0)
            break;
        n58 = ((uint64_t)(high / 38) << 32) | ((middle / 38) << 16) | (low / 38);"""
    if source.count(old) != 1:
        raise ValueError("Unexpected nonstandard FT8 callsign decoder")
    path = build / "ft8_native_message.c"
    path.write_text(source.replace(old, new), encoding="utf-8")
    return path


def build_vfp_fft(zig, build):
    # Deliberately emit native object files, with no LTO across this boundary.
    names = ("kiss_fft", "kiss_fft_alloc", "kiss_fft_stride", "kiss_fft_cleanup",
             "kiss_fft_next_fast_size", "kiss_fftr", "kiss_fftr_alloc", "kiss_fftr_packed", "kiss_fftri")
    renames = [f"-D{name}=ft8_hw_{name[5:]}" for name in names]
    objects = []
    for name in ("kiss_fft", "kiss_fftr"):
        obj = build / f"ft8_hw_fft_{name}.o"
        subprocess.run([str(zig), "cc", "-target", "thumb-linux-musleabi", "-mthumb", "-mcpu=cortex_a9",
                        "-mfpu=vfpv3-d16", "-mfloat-abi=softfp", "-Oz", "-ffp-contract=off", "-ffreestanding",
                        "-ffunction-sections", "-fdata-sections", "-fno-unwind-tables", "-fno-stack-protector",
                        "-DFT8_RADIO", "-Dmalloc=ft8_arm_malloc", "-Dfree=ft8_arm_free",
                        "-Dfprintf=ft8_arm_fprintf", "-Dexit=ft8_arm_exit", *renames,
                        "-c", str(LIB / f"fft/{name}.c"), "-o", str(obj)], check=True)
        objects.append(obj)
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", type=Path, default=ZIG)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--soft-float", action="store_true",
                        help="Build a Thumb-2 payload for testing with VFP disabled")
    parser.add_argument("--radio", action="store_true", help="Include the native radio adapter")
    parser.add_argument("--tx-hooks", action="store_true", help="Link the native TX DMA hooks for the VM")
    parser.add_argument("--custom-modes", action="store_true", help="Include the combined FT8 and CW menu")
    parser.add_argument("--vectors", action="store_true", help="Link the native menu and hook vectors")
    parser.add_argument("--sd-plugin", action="store_true", help="Enable the experimental SD queue formatter")
    parser.add_argument("--vfp", action="store_true", help="Enable native worker FFT acceleration with software fallback")
    parser.add_argument("--vfp-only", action="store_true", help="Require VFP and accelerate the entire spectrum update")
    parser.add_argument("--cw-debounce", action="store_true", help="Use consecutive hops for CW key detection")
    parser.add_argument("--profile", action="store_true", help="Log native decoder timing to SD")
    parser.add_argument("--grid", help="Fallback locator for the native menu")
    args = parser.parse_args()
    if args.tx_hooks and not args.radio:
        parser.error("--tx-hooks requires --radio")
    if args.profile and not args.vfp_only:
        parser.error("--profile requires --vfp-only")
    if args.custom_modes and not args.tx_hooks:
        parser.error("--custom-modes requires --radio --tx-hooks")
    if args.vectors and not args.radio:
        parser.error("--vectors requires --radio")
    if args.sd_plugin and not args.vectors:
        parser.error("--sd-plugin requires --vectors")
    args.vfp |= args.vfp_only
    if args.cw_debounce and not (args.custom_modes and args.vfp):
        parser.error("--cw-debounce requires --custom-modes and --vfp")
    if args.vfp and (not args.vectors or args.sd_plugin):
        parser.error("--vfp requires --vectors and the built-in queue formatter")
    build = args.build_dir or (BUILD / "radio" if args.radio else
                               BUILD / "soft-float" if args.soft_float else BUILD)
    build.mkdir(parents=True, exist_ok=True)
    elf_path = build / "ft8_rx.elf"
    bin_path = build / "ft8_rx.bin"
    payload = PATCH / "payload"
    if args.soft_float or args.radio:
        target = ("-target", "thumb-linux-musleabi", "-mthumb", "-flto", "-DFTX_LDPC_FIXED_POINT")
    else:
        target = ("-target", "arm-linux-musleabihf", "-marm")
    radio_flags = ("-DFT8_RADIO", "-DFT8_DMA_TX_SLOTS=2", "-DFTX_FT8_ONLY") if args.radio else ()
    radio_sources = (payload / "ft8_radio.c", payload / "ft8_dma_tx.c",
                     payload / "ft8_radio_tasks.S") if args.radio else ()
    if args.profile:
        radio_sources += (payload / "ft8_profile.c",)
        radio_flags += ("-DFT8_PROFILE",)
    if args.tx_hooks:
        radio_sources += (payload / "ft8_radio_dma_hooks.S",)
        radio_flags += ("-DFT8_RADIO_TX_HOOKS",)
    if args.custom_modes:
        radio_sources += (payload / "cw_panel.c",)
        radio_flags += ("-DFT8_CUSTOM_MODES",)
        if args.vfp:
            radio_flags += ("-DCW_VFP",)
            cw = build / "cw_decode_vfp.o"
            detector = ["-DCW_DEBOUNCE"] if args.cw_debounce else []
            subprocess.run([str(args.zig), "cc", "-target", "thumb-linux-musleabi", "-mthumb",
                            "-mcpu=cortex_a9", "-mfpu=vfpv3-d16", "-mfloat-abi=softfp",
                            "-Oz", "-ffp-contract=off", "-ffreestanding", "-fno-builtin",
                            "-fno-unwind-tables", "-ffunction-sections", "-fdata-sections",
                            "-DCW_VFP", "-DFT8_HOOK_VECTORS", *detector, "-c", str(payload / "cw_decode.c"),
                            "-o", str(cw)], check=True)
            radio_sources += (cw,)
        else:
            radio_sources += (payload / "cw_decode.c",)
    if args.vectors:
        radio_flags += ("-DFT8_LIVE", "-DFT8_HOOK_VECTORS")
        if args.grid:
            radio_flags += (f'-DFT8_DEFAULT_GRID="{args.grid}"',)
        radio_sources += tuple(payload / name for name in (
            "ft8_menu.c", "ft8_live.c", "ft8_touch.S", "func_menu_tile.S",
            "ft8_radio_hooks.S", "ft8_vectors.S",
        ))
    if args.sd_plugin:
        radio_flags += ("-DFT8_SD_PLUGIN",)
        radio_sources += (payload / "ft8_plugin.c",)
    linker = "ft8_radio.ld" if args.vectors else "ft8_arm.ld"
    core_sources = CORE_SOURCES
    if args.radio:
        write_native_pulse(build)
        decoder = write_native_decoder(build)
        ldpc = write_native_ldpc(build)
        native = {"decode.c": decoder, "ldpc.c": ldpc, "message.c": write_native_message(build)}
        core_sources = [native.get(p.name, p) for p in CORE_SOURCES]
    if args.vfp:
        radio_flags += ("-DFT8_VFP",)
        radio_sources += (payload / "ft8_fft.c", payload / "ft8_vfp.S", *build_vfp_fft(args.zig, build))
        monitor = build / "ft8_native_monitor.c"
        source = (LIB / "common/monitor.c").read_text(encoding="utf-8")
        original = "        kiss_fftr_packed(me->fft_cfg, freqdata, freqdata);"
        if source.count(original) != 1:
            raise ValueError("Unexpected monitor FFT call")
        if args.vfp_only:
            radio_flags += ("-DFT8_VFP_ONLY",)
            marker = "void monitor_process(monitor_t* me, const float* frame)"
            init, process = source.split(marker)
            process = process.split("\n#ifdef WATERFALL_USE_PHASE\nvoid monitor_resynth", 1)[0]
            hw = build / "ft8_hw_monitor.c"
            hw.write_text('#include <common/monitor.h>\n#include <math.h>\n'
                          'void ft8_hw_fftr_packed(kiss_fftr_cfg, const kiss_fft_cpx *, kiss_fft_cpx *);\n'
                          'void ft8_hw_monitor(monitor_t* me, const int16_t* frame)' +
                          process.replace(original, original.replace("kiss_fftr_packed", "ft8_hw_fftr_packed"))
                          .replace("frame[frame_pos];", "frame[frame_pos] * (1.0f / 32768.0f);"),
                          encoding="utf-8")
            hard_decode = build / "ft8_hw_decode.c"
            hard_decode.write_text(decoder.read_text(encoding="utf-8")
                                   .replace("ftx_find_candidates_in_band(", "ft8_hw_unused_search(")
                                   .replace("ftx_decode_candidate(", "ft8_hw_candidate("), encoding="utf-8")
            for unit in (hw, hard_decode):
                obj = unit.with_suffix(".o")
                subprocess.run([str(args.zig), "cc", "-target", "thumb-linux-musleabi", "-mthumb",
                                "-mcpu=cortex_a9", "-mfpu=vfpv3-d16", "-mfloat-abi=softfp",
                                "-Oz", "-ffp-contract=off", "-ffunction-sections", "-fdata-sections",
                                "-DFTX_FT8_ONLY", "-I", str(LIB), "-I", str(LIB / "ft8"), "-I", str(payload),
                                *(["-DFT8_PROFILE"] if args.profile else []),
                                "-c", str(unit), "-o", str(obj)], check=True)
                radio_sources += (obj,)
            monitor.write_text(init, encoding="utf-8")
        else:
            monitor.write_text('#include <fft/kiss_fftr.h>\n'
                           'void ft8_rx_fft(kiss_fftr_cfg, const kiss_fft_cpx *, kiss_fft_cpx *);\n' +
                           source.replace(original, original.replace("kiss_fftr_packed", "ft8_rx_fft")),
                           encoding="utf-8")
        core_sources = [monitor if p == LIB / "common/monitor.c" else p for p in core_sources]
    subprocess.run([
        str(args.zig), "cc", *target, *radio_flags, "-mcpu=cortex_a9",
        "-Oz", "-g", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-fno-unwind-tables", "-ffunction-sections", "-fdata-sections",
        "-nostartfiles", "-static", "-Wl,--gc-sections", "-Wl,--no-undefined",
        "-Wl,-e,ft8_arm_api", f"-Wl,-T,{payload / linker}",
        *(f"-D{name}=ft8_arm_{name}" for name in ("malloc", "calloc", "free", "fprintf", "exit")),
        "-DLOG_PRINTF(...)=((void)0)", "-D_GNU_SOURCE", "-I", str(LIB), "-I", str(LIB / "ft8"),
        "-I", str(payload), "-I", str(build), "-I", str(LIB / "common"),
        str(payload / "ft8_arm.c"), str(payload / "ft8_ui.c"), str(payload / "ft8_adif.c"),
        *map(str, radio_sources), *map(str, core_sources),
        "-lm", "-o", str(elf_path),
    ], check=True)
    subprocess.run([str(args.zig), "objcopy", "-O", "binary", "-j", ".payload",
                    str(elf_path), str(bin_path)], check=True)
    stage1 = build / "ft8_radio.bin"
    if args.vectors:
        subprocess.run([str(args.zig), "objcopy", "-O", "binary", "-j", ".stage1",
                        str(elf_path), str(stage1)], check=True)
    with elf_path.open("rb") as file:
        elf = ELFFile(file)
        payload_section = elf.get_section_by_name(".payload")
        if (payload_section["sh_addr"] != ARM_ADDRESS or
                payload_section.data() != bin_path.read_bytes() or
                payload_section.data()[:4] != b"FT8R"):
            raise ValueError("Unexpected ARM receiver image or entry table")
        allowed_sections = {".payload"}
        if args.vectors:
            hole = elf.get_section_by_name(".stage1")
            if hole["sh_addr"] != IMAGE_BASE + HOLE_OFFSET or hole.data() != stage1.read_bytes():
                raise ValueError("Unexpected native live region")
            allowed_sections.add(".stage1")
        if args.profile:
            allowed_sections.update(f".trace_{name}" for name, _, _ in TRACE_REGIONS)
        for section in elf.iter_sections():
            if section["sh_flags"] & 2 and section["sh_size"] and section.name not in allowed_sections:
                raise ValueError(f"Unexpected loadable section: {section.name}")
    print(f"{bin_path.name}: {bin_path.stat().st_size} bytes @ {ARM_ADDRESS:#x}")


if __name__ == "__main__":
    main()
