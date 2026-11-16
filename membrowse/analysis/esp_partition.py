#!/usr/bin/env python3
"""
ESP-IDF app partition accounting.

The ESP-IDF linker scripts describe the MMU windows through which the CPU sees
flash (``iram0_2_seg``/``drom0_0_seg`` on the ESP32, ``irom_seg``/``drom_seg``
on newer chips). Those windows are as large as the MMU can map, so measuring
flash use against them understates it: code and constants share one app
partition, and the IRAM code and ``.data`` initial values stored in the image
count only against RAM.

When the build's partition table is given, :func:`apply_app_partition`
replaces the window regions with one ``app_partition`` region: its limit is
the smallest app slot in the table, and its contents are the app image laid
out the way esptool writes it, so ``used_size`` equals the size of the
``.bin`` that is flashed (signed, when the app is signed).
"""

import logging
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..core.models import MemoryRegion

logger = logging.getLogger(__name__)

APP_PARTITION_REGION = 'app_partition'
OVERHEAD_SECTION = 'esp_image_overhead'
APP_DESC_SECTION = '.flash.appdesc'
SIGNING_PAD_SECTION = 'esp_signing_padding'
SIGNATURE_SECTION = 'esp_signature_sector'

_ENTRY = struct.Struct('<2sBBII16sI')
_ENTRY_MAGIC = b'\xaa\x50'
_TYPE_APP = 0x00

# esptool's ESP32-family image format (all chips with an extended header).
_IMAGE_HEADER_LEN = 24      # 8-byte common header + 16-byte extended header
_SEG_HEADER_LEN = 8         # load address + length before each segment
_CHECKSUM_ALIGN = 16
_DIGEST_LEN = 32            # SHA-256 appended by ESP-IDF builds
_FLASH_SEG_TAIL_MIN = 0x24  # see ImageParams.esp32_tail_pad
_SIGNATURE_SECTOR_LEN = 4096  # Secure Boot V2 signature sector
# Defined in ESP-IDF's secure_boot_v2/secure_boot_signatures_app.c, which is
# compiled only when CONFIG_SECURE_SIGNED_APPS selects the Secure Boot V2
# scheme (RSA or ECDSA V2). --gc-sections keeps only the ones something calls:
# the verifier is called from the OTA path alone, and an app without OTA is
# still signed when it lacks it. Either one marks a signed app.
_SBV2_SYMBOLS = frozenset((
    'esp_secure_boot_verify_sbv2_signature_block',
    'esp_secure_boot_get_signature_blocks_for_running_app',
))


class EspPartitionError(ValueError):
    """The partition table can't be used for this build (missing, unreadable,
    no app slot, or the ELF is not an ESP-IDF app)."""


@dataclass(frozen=True)
class Partition:
    """One entry of an ESP-IDF partition table."""
    name: str
    type: int
    subtype: int
    offset: int
    size: int


def parse_partition_table(path: str) -> List[Partition]:
    """Read a compiled partition table (``partitions.bin``).

    Entries are 32 bytes; the table ends at the first entry without the
    ``AA 50`` magic (the MD5 entry ``EB EB`` or ``FF`` padding).
    """
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        raise EspPartitionError(f"Partition table not found or unreadable: {path} ({e})") from e

    partitions = []
    for pos in range(0, len(data) - _ENTRY.size + 1, _ENTRY.size):
        magic, ptype, subtype, offset, size, name, _flags = _ENTRY.unpack_from(data, pos)
        if magic != _ENTRY_MAGIC:
            break
        partitions.append(Partition(
            name=name.split(b'\0', 1)[0].decode('ascii', 'replace'),
            type=ptype, subtype=subtype, offset=offset, size=size))
    if not partitions:
        raise EspPartitionError(
            f"No partition entries in {path}: expected a compiled ESP-IDF "
            "partition table (partitions.bin), not the CSV")
    return partitions


def select_app_partition(partitions: List[Partition],
                         name: Optional[str] = None) -> Partition:
    """Return the app slot to measure against.

    By default the smallest app partition (``factory``, ``ota_N``, ``test``),
    since the image must fit any slot it can be flashed to (ESP-IDF's
    ``check_sizes.py`` rule). ``name`` picks a slot explicitly. Tables whose
    app slots differ in size often keep a small slot for a separate app
    (meshtastic's ``flashApp`` OTA loader next to a 2.3 MB ``app``); the
    smallest is then the wrong limit, so that case is logged.
    """
    apps = [p for p in partitions if p.type == _TYPE_APP]
    if name:
        for part in apps:
            if part.name == name:
                return part
        raise EspPartitionError(
            f"No app partition named '{name}' in the partition table "
            f"(app partitions: {', '.join(p.name for p in apps) or 'none'})")
    if not apps:
        raise EspPartitionError("The partition table has no app partition")
    smallest = min(apps, key=lambda p: (p.size, p.offset))
    if len({p.size for p in apps}) > 1:
        logger.warning(
            "The app partitions differ in size (%s); measuring against the "
            "smallest, '%s'. If the firmware is flashed to another slot, set "
            "partition_name (--partition-name) to it.",
            ', '.join(f"{p.name} {p.size}" for p in apps), smallest.name)
    return smallest


@dataclass
class _Chunk:
    """A run of image bytes: ``length`` bytes of the ELF's address space from
    ``vaddr`` (None for padding) written at ``file_offset`` in the image.
    ``name`` labels padding reported as its own entry (signing)."""
    vaddr: Optional[int]
    length: int
    file_offset: int
    name: Optional[str] = None


@dataclass
class _Segment:
    addr: int
    length: int
    flash: bool


@dataclass(frozen=True)
class ImageParams:
    """Chip settings that change how esptool lays the image out."""
    # Flash segments start at the file offset matching their address within
    # an MMU page. 64 KB on most chips; C6, C5, H2 and others use smaller
    # pages on small flash chips.
    mmu_page_size: int = 0x10000
    # The original ESP32 pads a flash segment that ends less than 0x24 bytes
    # past a page boundary (a 2nd stage bootloader workaround).
    esp32_tail_pad: bool = False
    # Address of .flash.appdesc: its segment is written first, so the
    # bootloader finds the app descriptor at offset 0x20.
    app_desc_addr: Optional[int] = None
    # Signed with Secure Boot V2: esptool pads the image (``--secure-pad-v2``)
    # so it ends on an MMU page boundary, and signing appends a 4 KB
    # signature sector.
    signed_sbv2: bool = False


# Section types esptool copies into the image (it skips NOBITS, notes, ...).
_IMAGE_SECTION_TYPES = frozenset((
    'SHT_PROGBITS', 'SHT_INIT_ARRAY', 'SHT_FINI_ARRAY', 'SHT_PREINIT_ARRAY'))
# esp_app_desc_t.mmu_page_size: log2 of the MMU page size (ESP-IDF 5.1+;
# 0 in older descriptors, which means 64 KB).
_APP_DESC_MMU_PAGE_SIZE_OFFSET = 180
_ESP32_DROM = (0x3F400000, 0x3F800000)


def _image_sections(elffile) -> List[Tuple[str, int, int]]:
    """Sections esptool copies into the image: those with file contents
    (code and data, plus constructor arrays such as ``.flash.init_array``)
    at a nonzero address."""
    result = []
    for section in elffile.iter_sections():
        if (section.name and section['sh_type'] in _IMAGE_SECTION_TYPES
                and section['sh_addr'] != 0 and section['sh_size'] > 0):
            result.append((section.name, section['sh_addr'], section['sh_size']))
    return sorted(result, key=lambda s: s[1])


def _is_signed_sbv2(elffile) -> bool:
    """Whether the app is signed with Secure Boot V2, judged by the
    signature code ESP-IDF links into signed apps (any of _SBV2_SYMBOLS)."""
    symtab = elffile.get_section_by_name('.symtab')
    if symtab is None:
        return False
    return any(sym.name in _SBV2_SYMBOLS for sym in symtab.iter_symbols())


def image_params(elffile) -> ImageParams:
    """Read the layout settings from the ELF's app descriptor, and whether
    the app is signed."""
    desc = elffile.get_section_by_name(APP_DESC_SECTION)
    page_size = 0x10000
    data = desc.data()
    if len(data) > _APP_DESC_MMU_PAGE_SIZE_OFFSET:
        log2 = data[_APP_DESC_MMU_PAGE_SIZE_OFFSET]
        if 12 <= log2 <= 16:
            page_size = 1 << log2
    addr = desc['sh_addr']
    return ImageParams(
        mmu_page_size=page_size,
        esp32_tail_pad=_ESP32_DROM[0] <= addr < _ESP32_DROM[1],
        app_desc_addr=addr,
        signed_sbv2=_is_signed_sbv2(elffile))


def _merge_segments(sections, is_flash) -> List[_Segment]:
    """Merge address-contiguous sections of the same kind, as esptool does.

    esptool pads each section's data to 4 bytes first, which closes the
    alignment gaps between consecutive sections.
    """
    segments: List[_Segment] = []
    for _name, addr, size in sections:
        flash = is_flash(addr)
        padded = (size + 3) & ~3
        last = segments[-1] if segments else None
        if last and last.flash == flash and last.addr + last.length == addr:
            last.length += padded
        else:
            segments.append(_Segment(addr, padded, flash))
    return segments


def _flash_pad_needed(pos: int, segment: _Segment, align: int) -> int:
    """Bytes to write before ``segment`` so its data lands at the file offset
    that maps to its virtual address within an MMU page (esptool's
    ``get_alignment_data_needed``)."""
    align_past = (segment.addr % align) - _SEG_HEADER_LEN
    pad_len = (align - (pos % align)) + align_past
    if pad_len in (0, align):
        return 0
    pad_len -= _SEG_HEADER_LEN
    if pad_len < 0:
        pad_len += align
    return pad_len


def _split_segments(sections, is_flash, params: ImageParams):
    """Flash-mapped and RAM segments in the order esptool writes them: by
    address, with the app descriptor's flash segment first."""
    segments = _merge_segments(sections, is_flash)
    flash_segs = [s for s in segments if s.flash]
    ram_segs = [s for s in segments if not s.flash]
    for i, segment in enumerate(flash_segs):
        if segment.addr == params.app_desc_addr:
            flash_segs.insert(0, flash_segs.pop(i))
            break
    return flash_segs, ram_segs


def layout_image(sections, is_flash,
                 params: ImageParams = ImageParams()) -> Tuple[List[_Chunk], int]:
    """Lay the image out as esptool's ``elf2image`` does for ESP32-family
    chips: flash-mapped segments at the offsets their MMU pages need (the
    app descriptor's first), the gaps before them filled with RAM segments,
    the remaining RAM segments after, then the checksum byte and the SHA-256
    digest. A Secure Boot V2 signed image gets esptool's padding segment
    before the checksum, so it ends on a page boundary, and the signature
    sector after the digest. Secure Boot V1 (ESP32 only) is not modelled.

    Returns the data chunks and the total image size.
    """
    align = params.mmu_page_size
    flash_segs, ram_segs = _split_segments(sections, is_flash, params)
    chunks: List[_Chunk] = []
    pos = _IMAGE_HEADER_LEN

    def write(vaddr, length, name=None):
        nonlocal pos
        pos += _SEG_HEADER_LEN
        chunks.append(_Chunk(vaddr, length, pos, name))
        pos += length

    while flash_segs:
        segment = flash_segs[0]
        pad_len = _flash_pad_needed(pos, segment, align)
        if pad_len > 0:
            if ram_segs and pad_len > _SEG_HEADER_LEN:
                ram = ram_segs[0]
                take = min(pad_len, ram.length)
                write(ram.addr, take)
                ram.addr += take
                ram.length -= take
                if ram.length == 0:
                    ram_segs.pop(0)
            else:
                write(None, pad_len)
            continue
        write(segment.addr, segment.length)
        tail = pos % align
        if params.esp32_tail_pad and tail < _FLASH_SEG_TAIL_MIN:
            chunks.append(_Chunk(None, _FLASH_SEG_TAIL_MIN - tail, pos))
            pos += _FLASH_SEG_TAIL_MIN - tail
        flash_segs.pop(0)

    for ram in ram_segs:
        write(ram.addr, ram.length)

    if params.signed_sbv2:
        # esptool's secure_pad "2": a zero segment sized so that the 16-byte
        # checksum block and the digest end exactly on a page boundary.
        align_past = (pos + _SEG_HEADER_LEN) % align
        write(None, (align - align_past - _CHECKSUM_ALIGN - _DIGEST_LEN) % align,
              SIGNING_PAD_SECTION)

    pos += (_CHECKSUM_ALIGN - 1) - (pos % _CHECKSUM_ALIGN) + 1  # checksum byte
    pos += _DIGEST_LEN
    if params.signed_sbv2:
        chunks.append(_Chunk(None, _SIGNATURE_SECTOR_LEN, pos, SIGNATURE_SECTION))
        pos += _SIGNATURE_SECTOR_LEN
    return chunks, pos


def _section_entries(sections, chunks, base: int) -> List[Dict]:
    """Place each section's bytes at their physical address in the partition,
    and the signing padding and signature sector when the image is signed.

    A section whose bytes the image splits (a RAM segment cut to fill the gap
    before a flash segment) gets one entry per piece.
    """
    entries = []
    for chunk in chunks:
        if chunk.name and chunk.length:
            entries.append(_entry(chunk.name, base + chunk.file_offset,
                                  chunk.length, 'unknown'))
        if chunk.vaddr is None:
            continue
        chunk_end = chunk.vaddr + chunk.length
        for name, addr, size in sections:
            start = max(addr, chunk.vaddr)
            end = min(addr + size, chunk_end)
            if start < end:
                entries.append(_entry(
                    name, base + chunk.file_offset + (start - chunk.vaddr),
                    end - start, 'unknown'))
    return entries


def _overhead_entry(entries, base: int, image_size: int) -> Optional[Dict]:
    """One entry for the image bytes no section accounts for: the image and
    segment headers, alignment padding, the checksum and the digest.

    They are spread through the image in many small pieces, so they are
    reported once, at the image start where the header is, rather than as
    dozens of 1-8 byte entries that would clutter the region and PR diffs.
    """
    overhead = image_size - sum(e['size'] for e in entries)
    if overhead <= 0:
        return None
    return _entry(OVERHEAD_SECTION, base, overhead, 'unknown')


def _entry(name: str, address: int, size: int, sec_type: str) -> Dict:
    return {'name': name, 'address': address, 'size': size,
            'type': sec_type, 'end_address': address + size}


def _flash_windows(memory_regions: Dict[str, MemoryRegion],
                   sections) -> Dict[str, MemoryRegion]:
    """The regions covering the MMU flash windows: those containing the
    address of one of the ELF's ``.flash.*`` image sections, plus any region
    declared over the same address range. On C5, C6 and P4 ``irom_seg`` and
    ``drom_seg`` share one window; on the S3, ``extern_ram_seg`` (PSRAM) is
    declared over the constants window.

    ``sections`` are the unfiltered image sections, not the report's, so a
    window is still found when ``--skip-section`` removed all of its
    sections from the report.
    """
    flash_addrs = [addr for name, addr, _size in sections
                   if name.startswith('.flash.')]
    mapped = {name for name, region in memory_regions.items()
              if any(region.address <= addr < region.address + region.limit_size
                     for addr in flash_addrs)}
    ranges = {(memory_regions[n].address, memory_regions[n].limit_size)
              for n in mapped}
    return {name: region for name, region in memory_regions.items()
            if name in mapped or (region.address, region.limit_size) in ranges}


def _is_writable(region: MemoryRegion) -> bool:
    """Whether the linker script declares the region writable (RAM)."""
    return 'W' in (region.type or '').upper()


def _is_placeholder(section_name: str) -> bool:
    """An ESP-IDF NOLOAD section that reserves the addresses of a flash
    window (named ``*dummy``)."""
    return section_name.endswith('dummy')


def _drop_windows(memory_regions: Dict[str, MemoryRegion],
                  windows: Dict[str, MemoryRegion], image_names) -> List[str]:
    """Take the flash windows out of the layout. Returns the removed names.

    Read-only window regions are removed. A writable region over a window
    (PSRAM, ``extern_ram_seg`` on the S3) is kept for the RAM sections in it,
    without the flash sections; RAM sections the mapper put in a removed
    twin region move to it. Placeholder sections that only reserve the
    window's addresses (``.flash_rodata_dummy``, ``.ext_ram.dummy`` on the
    S3) are dropped: they take no flash and no PSRAM.
    """
    def is_flash_entry(entry):
        return (entry['name'] in image_names or entry['name'].startswith('.flash.')
                or _is_placeholder(entry['name']))

    kept = {(r.address, r.limit_size): r for r in windows.values() if _is_writable(r)}
    removed = []
    for name, region in windows.items():
        others = [e for e in region.sections if not is_flash_entry(e)]
        if _is_writable(region):
            region.sections = others
            continue
        twin = kept.get((region.address, region.limit_size))
        if twin is not None:
            twin.sections.extend(others)
        del memory_regions[name]
        removed.append(name)
    return removed


def _apply_report_sizes(entries: List[Dict],
                        reported: Dict[str, Tuple[int, str]]) -> List[Dict]:
    """Make the entries follow the report's sections: drop sections the
    report skipped (``--skip-section``) and trim the padding it excluded
    (``--exclude-alignment``) off the end of each section.

    The layout itself is worked out from the whole ELF, since the file
    offsets depend on every byte, so the remaining entries keep their real
    addresses.
    """
    kept = []
    for entry in sorted(entries, key=lambda e: e['address'], reverse=True):
        name = entry['name']
        if name in (OVERHEAD_SECTION, SIGNING_PAD_SECTION, SIGNATURE_SECTION):
            kept.append(entry)
            continue
        if name not in reported:
            continue  # skipped
        size, sec_type = reported[name]
        entry['type'] = sec_type
        # Bytes of this section still placed in lower-addressed pieces.
        lower = sum(e['size'] for e in entries
                    if e['name'] == name and e['address'] < entry['address'])
        keep = min(entry['size'], max(0, size - lower))
        if keep == 0:
            continue
        if keep < entry['size']:
            entry.update(size=keep, end_address=entry['address'] + keep)
        kept.append(entry)
    return kept


def apply_app_partition(memory_regions: Dict[str, MemoryRegion],
                        elffile,
                        report_sections,
                        partition: Partition) -> None:
    """Replace the ESP-IDF flash window regions with an ``app_partition``
    region measured against ``partition``.

    The window regions are found by content, not by name: the regions the
    image's ``.flash.*`` sections were mapped to (see :func:`_flash_windows`).
    Sections in those windows are flash-mapped; everything else in the
    image (IRAM code, ``.data`` initial values, RTC data) is copied from
    flash to RAM at boot but still takes space in the partition.

    ``report_sections`` are the report's sections (``MemorySection``), after
    ``--skip-section`` and ``--exclude-alignment``: skipped sections and
    excluded padding don't count in the partition either.

    Raises:
        EspPartitionError: If the ELF is not an ESP-IDF app or no window
            region contains its flash sections.
    """
    if elffile.get_section_by_name(APP_DESC_SECTION) is None:
        raise EspPartitionError(
            f"--partition-table is set but the ELF has no {APP_DESC_SECTION} "
            "section, so it is not an ESP-IDF app")

    sections = _image_sections(elffile)
    windows = _flash_windows(memory_regions, sections)
    if not windows:
        raise EspPartitionError(
            "--partition-table needs the ESP-IDF linker scripts (memory.ld): "
            "no memory region contains the ELF's .flash.* sections")

    def is_flash(addr: int) -> bool:
        return any(r.address <= addr < r.address + r.limit_size
                   for r in windows.values())

    params = image_params(elffile)
    chunks, image_size = layout_image(sections, is_flash, params)
    entries = _section_entries(sections, chunks, partition.offset)
    overhead = _overhead_entry(entries, partition.offset, image_size)
    if overhead:
        entries.append(overhead)
    entries = _apply_report_sizes(
        entries, {s.name: (s.size, s.type) for s in report_sections})
    entries.sort(key=lambda e: e['address'])
    not_counted = image_size - sum(e['size'] for e in entries)
    if not_counted:
        logger.info("app_partition: %d bytes of the image not counted "
                    "(--skip-section / --exclude-alignment)", not_counted)

    removed = _drop_windows(memory_regions, windows,
                            {name for name, _addr, _size in sections})
    memory_regions[APP_PARTITION_REGION] = MemoryRegion(
        address=partition.offset,
        limit_size=partition.size,
        type='R',
        sections=entries,
    )
    logger.info(
        "ESP-IDF app image: %d bytes%s in partition '%s' (0x%x, %d bytes); "
        "replaced flash window region(s): %s",
        image_size, ' (signed, Secure Boot V2)' if params.signed_sbv2 else '',
        partition.name, partition.offset, partition.size,
        ', '.join(sorted(removed)))
    if image_size > partition.size:
        logger.warning(
            "ESP-IDF app image (%d bytes) is larger than partition '%s' "
            "(%d bytes)", image_size, partition.name, partition.size)
