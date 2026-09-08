"""Gran Turismo 1 (PS1) course importer -- `COURSE.DAT`.

Executable used: SCUS-94194 (GT1 NTSC-U v1.0)

GT1 keeps every track in one archive at the disc root. `COURSE.DAT` is an
`@(#)GT-ARC` container (the same family as GT2's `crstim.arc`) holding 126
entries, which are 63 tracks x 2:

    entry 2i      the track's texture bundle -- a small named archive of PS1 TIMs
    entry 2i + 1  the track model, magic `@(#)GT-PS`, **version 0x001C0000**

That magic is the same one GT2's `.tro` files carry; GT2 is version 0x001F0000.
The two formats are the same lineage and most of this module's decode is GT2's,
imported from `gt2.py` rather than restated. What differs is set out below.

The second TIM in each bundle is named after its own track, so the 63 names come
out of the data rather than a table.

`arcade_rev_outba`, is 18 characters in a 16-byte field, so the archive
physically cannot hold it and 62 is the most that can agree.

The names are not descriptions: `circuit` is Grand Valley Speedway, `testline`
is High Speed Ring, `highway` is Special Stage Route 5.

DIFFERENCE 1 -- THE HEADER IS 8 BYTES SHORTER.
GT2 has five u32 section pointers at +0x10..+0x20 before a `3` and a magic
triple; GT1 has three at +0x10..+0x18 and the `3` lands at +0x1C. Every later
structure shifts down by the same 8: GT2's instance-placement count sits at
+0x19C, GT1's at +0x194.

DIFFERENCE 2 -- **GT1 BAKES NO POINTERS AT ALL**; the loader patches them in.
All three header pointers are zero in all 63 tracks, and so is every internal
one: the chunk pointer array, each ShapeData's vertex and list pointers, the
prop shape pointers. Nothing in the file says where anything is. This is why
`GTTrackViewer` shipped with a hand-written offset per track and a "search
forward for a block of zeroes" fallback for the rest.

Everything is still reachable, because the file is laid out in the order the
pointers would have pointed and every section's length is a function of its own
counts. This module walks it:

    0x194   33 instanced-object groups, `{u32 count; count x 28-byte placement}`
            laid end to end.  (Confirmed on GT2, where the pointers DO exist:
            all 126 files have 33 groups whose sizes chain exactly, the last
            ending on the TrackChunkTable.)
    then    TrackChunkTable: `u16 a, b; u16 numChunks; u16 c; u32 texTable;
            u32 chunkPtrs[numChunks]` -- the last two fields zeroed.
    then    numChunks TrackChunks, end to end, each sized by `chunk_size()`.
    then    the texture-descriptor table, `(highest referenced id + 1) x 32`.
    then    a 4-byte pad, the prop LOD chains, and the prop shapes.

`chunk_size()` is the load-bearing part, and it was derived on GT2 rather than
guessed here: a TrackChunk is its 0xA4 header, ShapeData 1 in place at +0xA4,
ShapeData 2, and three trailing sections, and GT2 stores a pointer to each of
the last four at +0x94..+0xA0. Predicting all four from the chunk's own counts
and comparing against those pointers is exact on **14,261 of 14,261** retail GT2
chunks, so the same arithmetic can be trusted where GT1 gives nothing to check
against. Applied to GT1 it agrees with an independent signature search on
`circuit` for 219 of 219 chunks, and reproduces all eight of the offsets
`GTTrackViewer` hard-codes (`testline` 0x8A8, `test_in2` 0x77C, `speed` 0x564,
`maxspeed` 0x580, `2p_testline` 0x3A0, `2p_test_in2` 0x69C, `2p_mountain` 0x4F4,
`end` 0x32C) -- 8 of 8, from the format instead of by hand.

DIFFERENCE 3 -- THE TEXTURE DESCRIPTOR IS ROTATED.
Both games use a 32-byte descriptor holding two 12-byte UV blocks and a LOD
threshold. GT2 puts the threshold between the blocks at +0x0C; GT1 puts it
first, at +0x00, and the blocks at +0x04 and +0x10. The 12 bytes themselves are
identical, and `circuit`'s first descriptor carries the same threshold (0x7C0)
and the same tpage (0x0E) in both games.

DIFFERENCE 4 -- TEXTURES COME AS A NAMED BUNDLE, NOT A VRAM REPLAY.
GT2's `.trp` is `u32 count` then TIMs. GT1's bundle is `u32 count`, then
`count x {char name[16]; u32 offset}`, then the TIMs. Each TIM still carries its
own destination VRAM coordinates, so replaying them reproduces the texture
memory that the descriptors' tpage/clut fields address -- and it checks out:
across all 63 tracks, **4,097 of 4,097** CLUT ids referenced by a descriptor are
provided by that track's own bundle, and tpage stays in 11..31, GT2's exact
range.

WHAT IS THE SAME.
The primitive encoding is GT2's, unchanged: four 9-bit pool indices at bits 0,
9, 18 and 32, the slot index selecting the primitive type, and the GP0 command
byte at record byte 11. Over all 63 tracks and **539,554** primitives, 100% of
indices resolve inside their own chunk's vertex pool and 100% of command bytes
match their slot. The texel-centre UV convention and the corner ordering are
likewise GT2's. The pool's SCALE and ORIGIN are not, and neither is its
handedness -- see DIFFERENCE 5.

Slots 8 and 9 are present too -- 5,764 billboards and 2,857 lamp glares -- and
the glare keeps the property that identified it in GT2: `highway` (Special Stage
Route 5, a night race in GT1 as well) has 246 while daytime tracks have none.

NOT YET DECODED -- the instanced props. Their placements read fine (33 groups,
28-byte records of rotation, scale and a 16.16 position) and their shapes are
located: GT1 stores a sequential shape INDEX where GT2 stores a pointer, the
indices form a dense 0..N-1 run in all 63 tracks, and the shapes follow with a
24-byte trailer each (GT2's is 20), giving 2,226 shapes and 123,154 vertices
over 61 tracks -- the other two have no props at all. What does NOT carry over
is the prop primitive record: GT2's layout puts the GP0 command at byte 11 and
that matches 0.85% of GT1's records, so the record was rearranged the way the
texture descriptor was. The lead is that the quad and textured slots want byte 7
instead (85-95%). Until that is settled the props are parsed and counted but not
built, rather than guessed at.
"""

import os
import struct
from typing import Dict, List, Optional, Tuple

from . import gt2
from .gt2 import Tro, TroChunk, TroPrim, TroSprite, TroGlare

ARC_MAGIC = b"@(#)GT-ARC"
GT1_VERSION = 0x001C0000

# Primitive strides by ShapeData slot. Slots 0-7 are GT2's chunk strides; 8 is
# the billboard record and 9 the lamp glare, both unchanged from GT2.
_CHUNK_STRIDES = (12, 12, 20, 24, 12, 12, 20, 24, 16, 20)
# The prop stream uses wider records because a prop carries UVs inline.
_PROP_STRIDES = (12, 12, 20, 24, 24, 24, 32, 36, 0x1C, 20)

# DIFFERENCE 5 -- THE CHUNK POOL IS FOUR TIMES FINER, ON A FOUR TIMES TIGHTER
# GRID. GT2 stores pool vertices in 1/64 of a world unit and derives the pool
# origin as `(Center & 0xFFC00000) >> 10` -- a 2^22 mask, so the origin snaps to
# 64 world units and the pool holds a remainder of up to 4096 units. GT1 stores
# them in 1/256 and uses `(Center & 0xFFF00000) >> 8`: a 2^20 mask, a 16
# world-unit grid, and the same 4096-unit box for the remainder. The two games
# spend the same 12 bits, just split differently between grid and remainder.
#
# Measured, not assumed, and against the chunk's own header rather than anything
# external: a chunk's Center at +0x30 is an absolute 16.16 world position, so a
# correct origin puts the pool's centroid on top of it. Sweeping every mask from
# 2^20 to 2^24 (and none) against pool scales from 1/32 to 1/512 -- 60
# combinations -- this one wins outright at a median 3.08 world units, where
# GT2's own settings score 2.78 on GT2 and the runner-up here scores 7.42.
#
# It is corroborated on the one course both games ship. Reading GT1's `circuit`
# (Grand Valley Speedway) at GT2's 1/64 gives a median face span of 2,269 pool
# units against GT2's 573 -- a factor of 3.96; at 1/256 that is 8.9 world units
# against GT2's 8.95. The path through the chunk Centers is 4942.5 world units
# in BOTH games with a median chunk step of 19.65, which also fixes the world
# unit at roughly a metre -- Grand Valley is 4.9 km.
#
# GT1's world also runs the OTHER WAY along component 2: the chunk origins match
# GT2's 219 of 219 on that shared circuit once component 2 is negated. The
# importer cancels that by negating both X and Y, which is a rotation rather
# than a mirror -- see the chunk loop in import_gt1_course().
_GT1_POOL_SCALE = 1.0 / 256.0
_GT1_ORIGIN_SHIFT = 8
_ORIGIN_MASK = 0xFFF00000

_N_INSTANCE_GROUPS = 33          # same group count as GT2, see instance_groups()
# A PROP ShapeData's header is 0x58 bytes, twenty longer than the 0x44 the
# track chunks use, and its vertex pool starts after it. GT2 states this
# outright and unanimously -- its stored vertexPtr is shapeStart + 88 on all
# 5,708 retail prop shapes, against + 68 on all 5,508 chunk ShapeData -- but the
# figure never has to be noticed there, because GT2 also stores where the lists
# begin. Here it does have to be, and reading a prop pool at +0x44 like a
# chunk's is why this stream first looked undecodable: with the header right the
# command byte matches its slot on 100% of GT1's 59,577 prop primitives and
# every 10-bit index resolves inside its own vertexCount, and 20 bytes early
# those figures are 0.85% and 19.6%.
#
# The extra twenty bytes are not padding: the per-shape scale exponent
# lod_shape_scale() reads at +0x54 sits in them, and GT1's values there follow
# the same 19..24 distribution as GT2's.
_PROP_HEADER = 0x58
# GT1 then pads each shape out by a further four bytes; GT2 does not.
_PROP_SHAPE_PAD = 4

# The prop stream's own command bytes. The flat untextured types differ from the
# roadway's: measured over 20 retail GT2 courses, slot 0 carries 0x21 on 100% of
# its records and slot 1 carries 0x29, not the 0x20/0x28 the chunks use. The
# textured slots also turn up a 1.3% minority with bit 0 set, so the comparison
# ignores that bit.
_PROP_CODES = {0: 0x20, 1: 0x28, 2: 0x30, 3: 0x38,
               4: 0x24, 5: 0x2C, 6: 0x34, 7: 0x3C}


def chunk_origin(center_raw: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """The chunk's pool origin, in the pool's own 1/256 world units."""
    out = []
    for v in center_raw:
        m = (v & 0xFFFFFFFF) & _ORIGIN_MASK
        if m & 0x80000000:
            m -= 1 << 32
        out.append(m >> _GT1_ORIGIN_SHIFT)
    return tuple(out)


# --- LZSS, and the `@(#)GT-ARC` container ----------------------------------
# Both are GT1's own. A flag byte covers the next eight chunks, LSB first; a
# clear bit is a literal, a set bit is `length byte + 3` then a distance that is
# one byte, or two when the top bit of the first is set (a 32K window).

def lzss_decompress(src: bytes, limit: int = 0) -> bytes:
    """`limit` stops early once that many bytes are out, so a caller that only
    wants a header (the name table, say) need not inflate a quarter-megabyte.
    A truncated input then runs off the end, which is not an error here."""
    out = bytearray()
    p, n, flags = 0, len(src), 1
    while p < n:
        if flags == 1:
            flags = src[p] | 0x100
            p += 1
            if p >= n:
                break
        if flags & 1:
            if p + 1 >= n:
                break
            length = src[p] + 3
            p += 1
            d0 = src[p]
            p += 1
            if d0 & 0x80:
                if p >= n:
                    break
                dist = ((d0 & 0x7F) << 8) | src[p]
                p += 1
            else:
                dist = d0
            start = len(out) - (dist + 1)
            if start < 0:
                break
            for i in range(length):
                out.append(out[start + i])
        else:
            out.append(src[p])
            p += 1
        flags >>= 1
        if limit and len(out) >= limit:
            break
    return bytes(out)


def arc_index(data: bytes) -> List[Tuple[int, int, int]]:
    """`(offset, stored size, uncompressed size)` for each entry, or []."""
    if data[:len(ARC_MAGIC)] != ARC_MAGIC or len(data) < 0x10:
        return []
    count = struct.unpack_from("<H", data, 0x0E)[0]
    if 0x10 + count * 12 > len(data):
        return []
    return [struct.unpack_from("<3I", data, 0x10 + i * 12) for i in range(count)]


def arc_entry(data: bytes, index: int) -> bytes:
    """One entry, decompressed if it was stored compressed."""
    off, size, usize = arc_index(data)[index]
    raw = data[off:off + size]
    if size != usize:
        raw = lzss_decompress(raw)
    return raw


# --- The texture bundle -----------------------------------------------------

def bundle_names(bundle: bytes) -> List[Tuple[str, int]]:
    """`(name, offset)` for each TIM. The table is what carries the track name."""
    if len(bundle) < 4:
        return []
    count = struct.unpack_from("<I", bundle, 0)[0]
    if not (0 < count < 4000) or 4 + count * 20 > len(bundle):
        return []
    out = []
    for i in range(count):
        rec = 4 + i * 20
        name = bundle[rec:rec + 16].split(b"\0")[0].decode("ascii", "replace")
        out.append((name, struct.unpack_from("<I", bundle, rec + 16)[0]))
    return out


def track_entries(course_dat: bytes) -> List[Tuple[int, Optional[int], str]]:
    """`(model entry, texture bundle entry, name)` for every track in an archive.

    Retail `COURSE.DAT` alternates bundle, model, bundle, model for 63 tracks,
    but nothing is assumed about that here: each entry is classified by looking
    at its own first bytes, and a model is paired with the most recent bundle
    before it. A build that ships a different number of tracks, or orders them
    differently, enumerates just as well -- which is the point, since the demo
    discs do not carry the retail 126.

    Only the first few bytes of an entry are inflated, so this stays cheap
    enough to call while the file browser is redrawing.
    """
    out: List[Tuple[int, Optional[int], str]] = []
    pending_bundle: Optional[int] = None
    pending_name: Optional[str] = None
    for i, (off, size, usize) in enumerate(arc_index(course_dat)):
        head = course_dat[off:off + min(size, 4096)]
        if size != usize:
            head = lzss_decompress(head, limit=64)
        if head[:len(gt2.TRO_MAGIC)] == gt2.TRO_MAGIC:
            name = pending_name or f"track_{len(out):02d}"
            out.append((i, pending_bundle, name))
            pending_bundle = pending_name = None
        else:
            nm = _bundle_name_at(head)
            if nm:
                pending_bundle, pending_name = i, nm
    return out


def track_names(course_dat: bytes, course_path: str = "") -> List[str]:
    """Track names, read out of the archive rather than hard-coded.

    A bundle's SECOND image is named after its own track (the first is the
    shared `refrect.tim`).
    """
    names = [nm for _m, _b, nm in track_entries(course_dat)]
    # The prototype's bundles are named after TEXTURES, not tracks, so its 14
    # entries come out as `1kabe1` three times over. SYSTEM.ENV beside the
    # archive has the real names and is preferred when its count agrees.
    if course_path:
        env = system_env_beside(course_path)
        if env is not None:
            better = env_course_names(env, len(names))
            if better:
                return better
    return names


def _bundle_name_at(head: bytes) -> Optional[str]:
    """The track name from a texture bundle's own name table, or None."""
    if len(head) < 44:
        return None
    count = struct.unpack_from("<I", head, 0)[0]
    if not (1 < count < 4000):
        return None
    # record 1 is the track's own image; record 0 is the shared reflection map
    name = head[24:40].split(b"\x00")[0].decode("ascii", "replace")
    if not name or any(c < " " for c in name):
        return None
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


def load_bundle_vram(bundle: bytes):
    """Replay a texture bundle into a PS1 VRAM image: 512 rows x 1024 halfwords.

    Same replay as GT2's `.trp` -- each TIM carries its own destination
    coordinates -- only the file has a name table in front of the images.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    entries = bundle_names(bundle)
    if not entries:
        return None
    vram = np.zeros((512, 1024), dtype=np.uint16)
    for _name, off in entries:
        if off + 8 > len(bundle):
            continue
        magic, flag = struct.unpack_from("<2I", bundle, off)
        if magic != 0x10:
            continue
        o = off + 8
        for _block in range(2 if (flag & 8) else 1):   # CLUT block, then image
            if o + 12 > len(bundle):
                break
            blen = struct.unpack_from("<I", bundle, o)[0]
            x, y, w, h = struct.unpack_from("<4H", bundle, o + 4)
            if w and h and o + 12 + w * h * 2 <= len(bundle) \
                    and y + h <= 512 and x + w <= 1024:
                px = np.frombuffer(bundle, dtype="<u2", count=w * h,
                                   offset=o + 12).reshape(h, w)
                vram[y:y + h, x:x + w] = px
            if blen <= 0:
                break
            o += blen
    return vram


# --- Walking a pointerless file ---------------------------------------------

def shapedata_size(data: bytes, sd: int, strides=_CHUNK_STRIDES) -> int:
    """Bytes occupied by one ShapeData: its header, vertex pool and ten lists."""
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    counts = (struct.unpack_from("<8H", data, sd + 0x30)
              + struct.unpack_from("<2H", data, sd + 0x40))
    return 0x44 + vcount * 8 + sum(n * strides[i] for i, n in enumerate(counts))


def chunk_sections(data: bytes, chunk: int,
                   header: int = 0xA4) -> Tuple[int, int, int]:
    """`(ShapeData 1, ShapeData 2, next chunk)` for one TrackChunk.

    The three sections after ShapeData 2 are skipped rather than decoded, since
    only their lengths are needed here:

        a `{u32 count; count x 8}` list,
        a `{u16 hdr[4]; u16 counts[16]; u32 ptrs[16]; u32 items[sum]}` table of
            per-list primitive groupings -- 104 bytes plus four per item,
        a `{u16 count; u16 chunk[count]}` visibility list, padded to 4.

    Exact on all 14,261 GT2 chunks against GT2's own stored pointers.
    """
    o = chunk + header
    sd1 = o
    o += shapedata_size(data, o)
    sd2 = o
    o += shapedata_size(data, o)
    k = struct.unpack_from("<I", data, o)[0]
    o += 4 + k * 8
    groups = struct.unpack_from("<16H", data, o + 8)
    o += 104 + 4 * sum(groups)
    m = struct.unpack_from("<H", data, o)[0]
    o += (2 + 2 * m + 3) & ~3
    return sd1, sd2, o


def instance_groups(data: bytes, base=None) -> Tuple[List[List[bytes]], int]:
    """The 33 instanced-object groups, and the offset just past them.

    Each is `{u32 count; count x 28}`: `s16 rot[2]; s16 pad[2]; s16 scale[4];
    s32 pos[3]` in 16.16. GT2 keeps an offset array at +0x118 pointing at these;
    GT1 has the array zeroed and the groups simply follow one another.
    """
    o = 0x194 if base is None else base
    groups: List[List[bytes]] = []
    for _ in range(_N_INSTANCE_GROUPS):
        if o + 4 > len(data):
            break
        count = struct.unpack_from("<I", data, o)[0]
        o += 4
        if count > 4096 or o + count * 28 > len(data):
            return groups, o
        groups.append([data[o + i * 28:o + (i + 1) * 28] for i in range(count)])
        o += count * 28
    return groups, o


def _read_tex_descriptor(data: bytes, table: int, tex_id: int, corners: int):
    """GT1's rotated descriptor: the LOD threshold leads, the UV block follows.

    Identical 12 bytes to GT2's, shifted up by four -- see DIFFERENCE 3.
    """
    off = table + tex_id * 32 + 4
    if off < 0 or off + 12 > len(data):
        return None
    u0, v0 = data[off], data[off + 1]
    clut = struct.unpack_from("<H", data, off + 2)[0]
    u1, v1 = data[off + 4], data[off + 5]
    tpage = struct.unpack_from("<H", data, off + 6)[0]
    u2, v2 = data[off + 8], data[off + 9]
    u3, v3 = data[off + 10], data[off + 11]
    uv = [(u0, v0), (u1, v1), (u2, v2), (u3, v3)][:corners]
    return ([gt2._texel_uv(u, v) for u, v in uv], tpage, clut)


def _list_offsets(data: bytes, sd: int, strides=_CHUNK_STRIDES) -> List[int]:
    """Where each of the ten primitive lists starts.

    GT2 reads these from the ShapeData's own pointer fields. GT1 zeroes them, so
    they are accumulated: the pool follows the 0x44 header, and each list
    follows the one before it.
    """
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    counts = (struct.unpack_from("<8H", data, sd + 0x30)
              + struct.unpack_from("<2H", data, sd + 0x40))
    o = sd + 0x44 + vcount * 8
    out = []
    for slot in range(10):
        out.append(o)
        o += counts[slot] * strides[slot]
    return out


def _decode_shapedata(data: bytes, sd: int, tex_table: int,
                      verts: List[Tuple[int, int, int]]) -> List[TroPrim]:
    """GT1's eight primitive lists. Same record encoding as GT2's chunks."""
    nv = len(verts)
    prims: List[TroPrim] = []
    offsets = _list_offsets(data, sd)
    counts = struct.unpack_from("<8H", data, sd + 0x30)
    for slot, (_code, stride, corners, textured, gouraud) in gt2._SLOTS.items():
        ptr, count = offsets[slot], counts[slot]
        if count <= 0 or ptr + count * stride > len(data):
            continue
        for i in range(count):
            off = ptr + i * stride
            w0, w1 = struct.unpack_from("<2I", data, off)
            idx = gt2._prim_indices(w0, w1, corners)
            if any(k >= nv for k in idx) or len(set(idx)) < 3:
                continue
            base = (data[off + 8] / 255.0, data[off + 9] / 255.0,
                    data[off + 10] / 255.0)
            if gouraud:
                cols = [base]
                for c in range(1, corners):
                    o = off + 8 + c * 4
                    cols.append((data[o] / 255.0, data[o + 1] / 255.0,
                                 data[o + 2] / 255.0))
            else:
                cols = [base] * corners
            uvs = None
            tpage = clut = 0
            if textured and tex_table > 0:
                got = _read_tex_descriptor(data, tex_table,
                                           (w1 >> 9) & 0x3FFF, corners)
                if got is not None:
                    uvs, tpage, clut = got
            prims.append(TroPrim(slot, tuple(idx), cols, uvs, tpage, clut))
    return prims


def parse_sprites(data: bytes, sd: int, tex_table: int) -> List[TroSprite]:
    """Slot 8 billboards. Same 16-byte record as GT2, found by walking."""
    out: List[TroSprite] = []
    count = struct.unpack_from("<H", data, sd + 0x40)[0]
    ptr = _list_offsets(data, sd)[8]
    if count <= 0 or ptr + count * 16 > len(data):
        return out
    for i in range(count):
        o = ptr + i * 16
        x, y = struct.unpack_from("<2h", data, o)
        z, tex_id = struct.unpack_from("<hH", data, o + 4)
        width, height = struct.unpack_from("<2H", data, o + 8)
        col = (data[o + 12] / 255.0, data[o + 13] / 255.0, data[o + 14] / 255.0)
        got = _read_tex_descriptor(data, tex_table, tex_id, 4) if tex_table else None
        uvs, tpage, clut = got if got else ([(0, 0)] * 4, 0, 0)
        out.append(TroSprite((x, y, z), width, height, col, uvs, tpage, clut))
    return out


def parse_glares(data: bytes, sd: int) -> List[TroGlare]:
    """Slot 9 lamp glare. Same 20-byte record as GT2, found by walking."""
    out: List[TroGlare] = []
    count = struct.unpack_from("<H", data, sd + 0x42)[0]
    ptr = _list_offsets(data, sd)[9]
    if count <= 0 or ptr + count * 20 > len(data):
        return out
    for i in range(count):
        o = ptr + i * 20
        x, y = struct.unpack_from("<2h", data, o)
        z, size = struct.unpack_from("<2h", data, o + 4)
        nx, ny, nz = struct.unpack_from("<3h", data, o + 8)
        col = (data[o + 16] / 255.0, data[o + 17] / 255.0, data[o + 18] / 255.0)
        out.append(TroGlare((x, y, z), size, (nx, ny, nz), col))
    return out


# --- BUILD LAYOUTS ----------------------------------------------------------
# Retail is not the only shape this file comes in. The July 29 1997 prototype
# writes the same format with a SHORTER header in two places, and reading it
# with retail's offsets walks off the end of the buffer
#
# Two fields retail has and the prototype does not:
#
#   * the model header's 33-entry instance-group offset array. GT2 keeps it at
#     +0x118 and points it at the groups; retail GT1 keeps it and zeroes it;
#     the prototype simply does not have it. 33 x 4 = 132 bytes, which is
#     exactly the 0x194 -> 0x110 difference in where the groups start.
#   * per chunk, a u32 at +0x0C and a second block of ten u32s at +0x6C. That
#     is 44 bytes, and 0xA4 - 0x2C = 0x78. Everything from +0x0C on shifts down
#     by the first four, so `world` moves 0x18 -> 0x14 and `Center` 0x30 ->
#     0x2C.
#
# The prototype also carries ONE instance group where retail carries 33.
#
# The layout is chosen by WALKING, not by the version word (retail 0x001C0000,
# prototype 0x001A0000). The instance groups are counted lists of unknown
# length, so the only test that actually settles it is whether the chunk table
# after them walks all its chunks and lands inside the file -- and that is a
# strong signature: on the prototype only 0x78 walks, with 0x74 and 0x7C both
# failing on the first chunk. Structural detection also means a build nobody
# has looked at yet works if it shares one of these shapes, rather than needing
# its version number added to a list.


class _Layout:
    __slots__ = ("name", "group_base", "chunk_header", "world_off", "center_off")

    def __init__(self, name, group_base, chunk_header, world_off, center_off):
        self.name = name
        self.group_base = group_base
        self.chunk_header = chunk_header
        self.world_off = world_off
        self.center_off = center_off


_LAYOUTS = (
    _Layout("retail", 0x194, 0xA4, 0x18, 0x30),
    _Layout("Jul 1997 prototype", 0x110, 0x78, 0x14, 0x2C),
)


def _walk_chunks(data: bytes, tct: int, lay: "_Layout"):
    """`(chunk offsets, texture table)` if `tct` really is the chunk table.

    Every chunk is located by walking the previous one, so a wrong guess fails
    within a chunk or two; a right one walks all of them and stops inside the
    file. Nothing here trusts a stored size.
    """
    if tct + 0x0C > len(data):
        return None
    try:
        n = struct.unpack_from("<H", data, tct + 4)[0]
    except struct.error:
        return None
    if not (1 <= n <= 8192):
        return None
    c = tct + 0x0C + n * 4
    out = []
    for _ in range(n):
        if c + lay.chunk_header > len(data):
            return None
        try:
            sd1, sd2, nxt = chunk_sections(data, c, lay.chunk_header)
        except (struct.error, ValueError, IndexError):
            return None
        if not (c < nxt <= len(data)):
            return None
        out.append((c, sd1, sd2))
        c = nxt
    return out, c


def model_layout(data: bytes):
    """`(layout, chunk offsets, texture table)` for one GT1 model, or Nones.

    Every offset the group walk passes through is tried, and the BEST result
    wins rather than the first. That matters: an offset in the middle of the
    instance groups can read as a one-chunk table that happens to walk, and
    retail `highway` does exactly that -- taking the first hit gave it 1 chunk
    instead of 194. Walking N chunks is a strong signature precisely because N
    is large, so the candidate that explains the most of the file is the real
    one.
    """
    best = (0, None, None, None)
    for lay in _LAYOUTS:
        o = lay.group_base
        for _ in range(_N_INSTANCE_GROUPS + 1):
            got = _walk_chunks(data, o, lay)
            if got is not None and len(got[0]) > best[0]:
                best = (len(got[0]), lay, got[0], got[1])
            if o + 4 > len(data):
                break
            count = struct.unpack_from("<I", data, o)[0]
            o += 4
            if count > 4096 or o + count * 28 > len(data):
                break
            o += count * 28
    return best[1], best[2], best[3]


def parse_gt1_model(data: bytes) -> Optional[Tro]:
    """Parse one GT1 track model into the same `Tro` the GT2 path produces.

    Returns None rather than raising for anything it cannot read. A course
    archive is not necessarily retail -- prototypes and demos put the same
    format together differently -- and an unreadable model has to come back as
    a message, not as a traceback out of the operator.
    """
    try:
        return _parse_gt1_model(data)
    except (struct.error, ValueError, IndexError, KeyError, OverflowError):
        return None


def _parse_gt1_model(data: bytes) -> Optional[Tro]:
    if data[:len(gt2.TRO_MAGIC)] != gt2.TRO_MAGIC:
        return None
    version = struct.unpack_from("<I", data, 0x0C)[0]
    lay, walked, tex_table = model_layout(data)
    if lay is None:
        return None
    chunks: List[TroChunk] = []
    highest_tex = -1
    for i, (c, sd1, sd2) in enumerate(walked):
        prev_i, next_i = struct.unpack_from("<2H", data, c)
        world_raw = struct.unpack_from("<3i", data, c + lay.world_off)
        center_raw = struct.unpack_from("<3i", data, c + lay.center_off)
        chunk = TroChunk(i, c, prev_i, next_i, world_raw, center_raw)
        chunk.verts = _read_pool(data, sd1)
        # The two ShapeData blocks share one vertex pool index space only within
        # themselves, so the second block's geometry is appended with its own
        # pool and its indices shifted to match.
        chunk._sd = (sd1, sd2)
        chunks.append(chunk)
    # The descriptor table runs exactly to the highest id any primitive cites:
    # on all 126 GT2 files its stored length is (highest + 1) * 32 with nothing
    # to spare, which is what makes the following sections findable here.
    for ch in chunks:
        for sd in ch._sd:
            counts = struct.unpack_from("<8H", data, sd + 0x30)
            offs = _list_offsets(data, sd)
            for slot in (4, 5, 6, 7):
                stride = _CHUNK_STRIDES[slot]
                for r in range(counts[slot]):
                    w1 = struct.unpack_from("<I", data, offs[slot] + r * stride + 4)[0]
                    highest_tex = max(highest_tex, (w1 >> 9) & 0x3FFF)
    # The two ShapeData blocks are kept apart rather than merged. The second is
    # a LOW-DETAIL COPY of the same ground: it covers the first's bounding box in
    # every chunk that has one (95/95 on `testline`, 206/206 on `outbahn`) while
    # carrying about 15% of the vertices and 10% of the faces, with a median face
    # span 2.5 to 3.7 times larger. Merged into the roadway it simply
    # z-fights with it, which is what a doubled track surface in the viewport is.
    for ch in chunks:
        sd1, sd2 = ch._sd
        ch.prims = _decode_shapedata(data, sd1, tex_table, ch.verts)
        ch.lod_verts = _read_pool(data, sd2)
        ch.lod_prims = (_decode_shapedata(data, sd2, tex_table, ch.lod_verts)
                        if ch.lod_verts else [])
    tro = Tro(version, 0, tex_table, chunks)
    tro.tex_count = highest_tex + 1
    tro.layout = lay
    return tro


def _read_pool(data: bytes, sd: int) -> List[Tuple[int, int, int]]:
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    if not (0 < vcount <= 20000):
        return []
    return gt2._read_s16_verts(data, sd + 0x44, vcount)


def prop_shapes(data: bytes, tro: Tro) -> List[int]:
    """Offsets of the prop LOD shapes, or [] when a track has no props.

    GT1 stores a sequential shape index where GT2 stores a pointer, and the
    indices form a dense 0..N-1 run in every track that has any, so the shapes
    can be walked in order. Not yet built -- see the module docstring.
    """
    base = tro.tex_table + getattr(tro, "tex_count", 0) * 32
    for pad in range(0, 65, 4):
        try:
            lod = base + pad
            n_chain = struct.unpack_from("<I", data, lod)[0]
            if not (0 < n_chain < 4000):
                continue
            p = lod + 4 + n_chain * 4
            idx = []
            for _ in range(n_chain):
                k = struct.unpack_from("<I", data, p)[0]
                p += 4
                if k > 32:
                    raise ValueError
                for _ in range(k):
                    _dist, shape = struct.unpack_from("<2I", data, p)
                    p += 8
                    idx.append(shape)
            if not idx or sorted(set(idx)) != list(range(max(idx) + 1)):
                continue
            n_shapes = struct.unpack_from("<I", data, p)[0]
            if n_shapes != max(idx) + 1:
                continue
            q = p + 4 + n_shapes * 4
            out = []
            for _ in range(n_shapes):
                if q + _PROP_HEADER > len(data):
                    raise ValueError
                vcount = struct.unpack_from("<i", data, q + 0x2C)[0]
                if not (0 <= vcount < 20000):
                    raise ValueError
                out.append(q)
                q += prop_shape_size(data, q)
            if q <= len(data):
                return out
        except (struct.error, ValueError):
            continue
    return []


def prop_shape_size(data: bytes, sd: int) -> int:
    """Bytes one prop shape occupies, including GT1's four bytes of padding."""
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    counts = (struct.unpack_from("<8H", data, sd + 0x30)
              + struct.unpack_from("<2H", data, sd + 0x40))
    return (_PROP_HEADER + max(vcount, 0) * 8
            + sum(n * _PROP_STRIDES[i] for i, n in enumerate(counts))
            + _PROP_SHAPE_PAD)


def _prop_list_offsets(data: bytes, sd: int) -> List[int]:
    """Where each of a prop shape's ten primitive lists starts."""
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    counts = (struct.unpack_from("<8H", data, sd + 0x30)
              + struct.unpack_from("<2H", data, sd + 0x40))
    o = sd + _PROP_HEADER + max(vcount, 0) * 8
    out = []
    for slot in range(10):
        out.append(o)
        o += counts[slot] * _PROP_STRIDES[slot]
    return out


def _decode_prop_shapedata(data: bytes, sd: int,
                           verts: List[Tuple[int, int, int]]) -> List[TroPrim]:
    """One prop ShapeData's eight lists: 10-bit indices, UVs inline.

    Record layout is GT2's unchanged -- only the way the lists are located
    differs, since GT1 zeroes the pointers.
    """
    nv = len(verts)
    prims: List[TroPrim] = []
    offsets = _prop_list_offsets(data, sd)
    counts = struct.unpack_from("<8H", data, sd + 0x30)
    for slot, (_code, _cs, corners, textured, gouraud) in gt2._SLOTS.items():
        stride = _PROP_STRIDES[slot]
        ptr, count = offsets[slot], counts[slot]
        if count <= 0 or ptr + count * stride > len(data):
            continue
        for i in range(count):
            off = ptr + i * stride
            w0, w1 = struct.unpack_from("<2I", data, off)
            idx = [w0 & 0x3FF, (w0 >> 10) & 0x3FF,
                   (w0 >> 20) & 0x3FF, w1 & 0x3FF][:corners]
            if any(k >= nv for k in idx) or len(set(idx)) < 3:
                continue
            base = (data[off + 8] / 255.0, data[off + 9] / 255.0,
                    data[off + 10] / 255.0)
            uvs = None
            tpage = clut = 0
            if textured:
                u = off + 12
                clut = struct.unpack_from("<H", data, u + 2)[0]
                tpage = struct.unpack_from("<H", data, u + 6)[0]
                pairs = [(data[u], data[u + 1]), (data[u + 4], data[u + 5]),
                         (data[u + 8], data[u + 9]),
                         (data[u + 10], data[u + 11])][:corners]
                uvs = [gt2._texel_uv(uu, vv) for uu, vv in pairs]
            if gouraud:
                cb = off + (24 if textured else 12)
                cols = [base]
                for c in range(corners - 1):
                    o = cb + c * 4
                    cols.append((data[o] / 255.0, data[o + 1] / 255.0,
                                 data[o + 2] / 255.0))
            else:
                cols = [base] * corners
            prims.append(TroPrim(slot, tuple(idx), cols, uvs, tpage, clut))
    return prims


def parse_prop_sprites(data: bytes, sd: int) -> List[TroSprite]:
    """Slot 8 of a prop shape: the distant stand-in billboards, UVs inline."""
    out: List[TroSprite] = []
    count = struct.unpack_from("<H", data, sd + 0x40)[0]
    ptr = _prop_list_offsets(data, sd)[8]
    stride = _PROP_STRIDES[8]
    if count <= 0 or ptr + count * stride > len(data):
        return out
    for i in range(count):
        o = ptr + i * stride
        x, y = struct.unpack_from("<2h", data, o)
        z, _flags = struct.unpack_from("<hH", data, o + 4)
        width, height = struct.unpack_from("<2H", data, o + 8)
        col = (data[o + 12] / 255.0, data[o + 13] / 255.0, data[o + 14] / 255.0)
        u = o + 16
        clut = struct.unpack_from("<H", data, u + 2)[0]
        tpage = struct.unpack_from("<H", data, u + 6)[0]
        uvs = [gt2._texel_uv(data[u], data[u + 1]),
               gt2._texel_uv(data[u + 4], data[u + 5]),
               gt2._texel_uv(data[u + 8], data[u + 9]),
               gt2._texel_uv(data[u + 10], data[u + 11])]
        out.append(TroSprite((x, y, z), width, height, col, uvs, tpage, clut))
    return out


def parse_prop_shape(data: bytes, sd: int):
    """`(verts, prims, scale, sprites)` for one prop shape, or None.

    A shape with no vertices is not necessarily empty -- that is how a distant
    object is swapped for a single billboard.
    """
    if not (0 < sd < len(data) - 0x56):
        return None
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    if not (0 <= vcount <= 100000):
        return None
    verts = (gt2._read_s16_verts(data, sd + _PROP_HEADER, vcount)
             if vcount > 0 else [])
    sprites = parse_prop_sprites(data, sd)
    if not verts and not sprites:
        return None
    return (verts, _decode_prop_shapedata(data, sd, verts),
            gt2.lod_shape_scale(data, sd), sprites)


def parse_instances(data: bytes, base=None) -> List[gt2.TroInstance]:
    """The 33 instanced-object groups, as placements.

    Record is GT2's 28 bytes unchanged: `s16 flags, yaw, unk, lodIndex;
    s16 scale[4]; s32 pos[3]` in 16.16, ordered (X, height, Z).
    """
    out: List[gt2.TroInstance] = []
    for group, records in enumerate(instance_groups(data, base)[0]):
        for rec in records:
            flags, yaw, _unk, lidx = struct.unpack_from("<4h", rec, 0)
            sx, sy, sz, _sw = struct.unpack_from("<4h", rec, 8)
            px, py, pz = struct.unpack_from("<3i", rec, 0x10)
            out.append(gt2.TroInstance(group, flags, yaw, lidx,
                                       (sx, sy, sz), (px, py, pz)))
    return out


def prop_lod_chains(data: bytes, tro: Tro):
    """`lod_index -> [(max distance, shape offset), ...]`, nearest first.

    GT1 stores a sequential shape INDEX where GT2 stores a pointer, so the
    chain's entries are resolved through the shape list that `prop_shapes()`
    walks.
    """
    shapes = prop_shapes(data, tro)
    if not shapes:
        return []
    base = tro.tex_table + getattr(tro, "tex_count", 0) * 32
    for pad in range(0, 65, 4):
        try:
            lod = base + pad
            n_chain = struct.unpack_from("<I", data, lod)[0]
            if not (0 < n_chain < 4000):
                continue
            p = lod + 4 + n_chain * 4
            chains = []
            for _ in range(n_chain):
                k = struct.unpack_from("<I", data, p)[0]
                p += 4
                if k > 32:
                    raise ValueError
                levels = []
                for _ in range(k):
                    dist, shape = struct.unpack_from("<2I", data, p)
                    p += 8
                    if shape >= len(shapes):
                        raise ValueError
                    levels.append((dist, shapes[shape]))
                chains.append(levels)
            if chains and any(chains):
                return chains
        except (struct.error, ValueError):
            continue
    return []


# --- Skydomes: `BG.DAT` and `SYSTEM.DAT` -----------------------------------
# A course's sky is not in COURSE.DAT. It lives beside it in **BG.DAT**, another
# `@(#)GT-ARC` with the same alternation the tracks use: 20 entries = 10 skies x
# {texture bundle, model}. The model's magic is `@(#)GT-SKY`, a sixth member of
# the `@(#)GT-` family, version 2.
#
#     +0x00  char magic[10] "@(#)GT-SKY" ; u16 pad
#     +0x0C  u32 version                  0x00020000
#     +0x10  u8 r, g, b ; u8 0x28         background colour A
#     +0x14  u8 r, g, b ; u8 0x28         background colour B
#     +0x18  12 bytes, always zero
#     +0x24  u32 vertexCount
#     +0x28  u16 listCounts[8]            F3 F4 G3 G4 FT3 FT4 GT3 GT4
#     +0x38  vertexCount x 8              s16 x, y, z, pad -- pad always zero
#     then   the eight primitive lists
#     then   THE SAME BLOCK AGAIN
#     then   u32 count ; char name[16][count]   the textures the sky uses
#
# That colour pair is GT2's `.bso` header exactly, 0x28 terminator and all, and
# a record is the same shape too: 8 bytes of indices then a PS1 GPU packet, with
# the packet starting at record+12. Two differences. GT2 stores TWO copies of
# `[OT tag][packet]` inside each record for double buffering; GT1 stores one and
# then repeats the entire primitive block -- verified byte-for-byte identical on
# all ten skies. And the indices are the `.bso`'s FOUR 12-BIT FIELDS at bits
# 0-11 and 12-23 of the two words: over 1,238 sky primitives every one resolves
# inside its own vertexCount, against 32.6% for the roadway's 9-bit reading,
# and decoded faces span a median 1,174 units against 7,090 for random triples.
# The OT tag's length byte matches its slot's packet size on 100% of them, which
# is what pins the strides.
SKY_MAGIC = b"@(#)GT-SKY"
_SKY_WORDS = {0: 4, 1: 5, 2: 6, 3: 8, 4: 7, 5: 9, 6: 8, 7: 12}
# 8 index bytes + a 4-byte OT tag + the packet
_SKY_STRIDES = {k: 12 + w * 4 for k, w in _SKY_WORDS.items()}


class Sky:
    """One decoded skydome."""

    def __init__(self, colour_a, colour_b, verts, prims, textures):
        self.colour_a = colour_a
        self.colour_b = colour_b
        self.verts = verts
        self.prims = prims
        self.textures = textures


def parse_sky(data: bytes) -> Optional[Sky]:
    if len(data) < 0x38 or data[:len(SKY_MAGIC)] != SKY_MAGIC:
        return None
    ca = (data[0x10] / 255.0, data[0x11] / 255.0, data[0x12] / 255.0)
    cb = (data[0x14] / 255.0, data[0x15] / 255.0, data[0x16] / 255.0)
    vcount = struct.unpack_from("<I", data, 0x24)[0]
    counts = struct.unpack_from("<8H", data, 0x28)
    if not (0 < vcount < 20000) or 0x38 + vcount * 8 > len(data):
        return None
    verts = [struct.unpack_from("<3h", data, 0x38 + i * 8) for i in range(vcount)]
    prims: List[TroPrim] = []
    off = 0x38 + vcount * 8
    for slot in range(8):
        stride = _SKY_STRIDES[slot]
        count = counts[slot]
        if count and off + count * stride > len(data):
            break
        _code, _cs, corners, textured, gouraud = gt2._SLOTS[slot]
        for i in range(count):
            o = off + i * stride
            a, b = struct.unpack_from("<2I", data, o)
            idx = [a & 0xFFF, (a >> 12) & 0xFFF,
                   b & 0xFFF, (b >> 12) & 0xFFF][:corners]
            if any(k >= vcount for k in idx) or len(set(idx)) != len(idx):
                continue
            w = o + 12                      # past the indices and the OT tag
            base = gt2._bso_packet_colour(data, w)
            uvs = None
            tpage = clut = 0
            if textured:
                step = 12 if gouraud else 8
                u0 = w + 8
                clut = struct.unpack_from("<H", data, u0 + 2)[0]
                tpage = struct.unpack_from("<H", data, u0 + step + 2)[0]
                uvs = [gt2._texel_uv(data[u0 + step * c], data[u0 + step * c + 1])
                       for c in range(corners)]
            if gouraud:
                step = 12 if textured else 8
                cols = [gt2._bso_packet_colour(data, w + step * c)
                        for c in range(corners)]
            else:
                cols = [base] * corners
            prims.append(TroPrim(slot, tuple(idx), cols, uvs, tpage, clut))
        off += count * stride
    off += off - (0x38 + vcount * 8)        # skip the duplicate block
    names = []
    if off + 4 <= len(data):
        n = struct.unpack_from("<I", data, off)[0]
        if 0 <= n < 500 and off + 4 + n * 16 <= len(data):
            names = [data[off + 4 + k * 16:off + 20 + k * 16].split(b"\x00")[0]
                     .decode("ascii", "replace") for k in range(n)]
    return Sky(ca, cb, verts, prims, names)


# `SYSTEM.DAT` is `@(#)GTENV` -- GT1's course environment table, and the answer
# to which sky a track uses. `u16 count` at +0x0C is 63, the track count; from
# +0x48 come that many length-prefixed names (a leading byte counting the
# characters AND the terminator), and a 16-byte record per track follows them.
#
# Byte 2 of that record is the sky: the low seven bits index BG.DAT and bit 7 is
# set for a night course. It checks out completely -- all 63 tracks resolve to a
# sky that exists, and the only two values carrying bit 7 (0x83 for the `highway`
# family, 0x85 for `outbahn`) point at two of the three skies whose background
# colour is pure black. Special Stage Route 5 and Special Stage Route 11 are
# exactly GT1's night races.
GTENV_MAGIC = b"@(#)GTENV"
_GTENV_NAMES = 0x48
_GTENV_RECORD = 16


def parse_gtenv(data: bytes) -> List[Tuple[str, int, bool]]:
    """`(track name, sky index, is night)` for every course, or []."""
    if data[:len(GTENV_MAGIC)] != GTENV_MAGIC or len(data) < 0x50:
        return []
    count = struct.unpack_from("<H", data, 0x0C)[0]
    if not (0 < count < 500):
        return []
    names, p = [], _GTENV_NAMES
    for _ in range(count):
        if p >= len(data):
            return []
        n = data[p]
        if n == 0 or p + n > len(data):
            return []
        names.append(data[p + 1:p + n].decode("ascii", "replace"))
        p += 1 + n
    out = []
    for i, nm in enumerate(names):
        rec = p + i * _GTENV_RECORD
        if rec + _GTENV_RECORD > len(data):
            break
        b = data[rec + 2]
        out.append((nm, b & 0x7F, bool(b & 0x80)))
    return out


# --- SYSTEM.ENV: the prototype's course table -------------------------------
# Retail keeps its course table in SYSTEM.DAT as a binary `@(#)GTENV` block.
# The July 1997 prototype has no SYSTEM.DAT at all; it ships **SYSTEM.ENV**, a
# plain `key=value` text file, and that file holds the same three things:
#
#     course=14
#     course.name.0=GRAND VALLEY SPEEDWAY      <- real names, where COURSE.DAT
#     course.name.7=HIGH SPEEDRING                only has texture names
#     course.bg.0=BG noon                      <- which sky each course uses
#     sky=10
#     sky.name.7=BG noon                       <- and which BG.DAT entry that is
#
# So a course's sky is resolved by NAME through two hops, where retail resolves
# it by index in one. It checks out on all 14: every `course.bg` names a
# `sky.name`, and the skies it picks carry the same textures as the retail
# entries for the same course -- High Speed Ring gets kumo2/tubo4d1 in both,
# Deep Forest kumo2/tubo1a1 in both.
#
# Two of the prototype's ten skies are unused by any course: `BG Test`
# (bga1/bga5) and `BG c1_bg` (bg_ab1/bg_ab2), the latter presumably for the
# Tokyo C1 loop that never shipped. They import if asked for by index.
#
# SYSTEM.ENV carries no night flag, so night is reported as unknown (False)
# rather than guessed; retail's GTENV bit has no counterpart here.

def parse_system_env(raw: bytes) -> dict:
    """`SYSTEM.ENV` as a dict. Last value wins, as the game's own reader does."""
    out = {}
    for line in raw.decode("latin-1").splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def _read_beside(course_path: str, name: str) -> Optional[bytes]:
    folder = os.path.dirname(course_path)
    for cand in (name, name.lower(), name.upper()):
        try:
            with open(os.path.join(folder, cand), "rb") as fh:
                return fh.read()
        except OSError:
            continue
    return None


def system_env_beside(course_path: str) -> Optional[dict]:
    raw = _read_beside(course_path, "SYSTEM.ENV")
    if raw is None:
        return None
    env = parse_system_env(raw)
    return env if "course" in env else None


def env_course_names(env: dict, count: int) -> Optional[List[str]]:
    """`course.name.N` for N in range, only if the table matches the archive."""
    try:
        n = int(env.get("course", "0"))
    except ValueError:
        return None
    if n != count:
        return None
    names = [env.get(f"course.name.{i}", "") for i in range(n)]
    return names if all(names) else None


def env_sky_index(env: dict, track: int) -> Optional[int]:
    """The BG.DAT entry `course.bg.<track>` names, via the `sky.name` list."""
    want = env.get(f"course.bg.{track}")
    if not want:
        return None
    try:
        n = int(env.get("sky", "0"))
    except ValueError:
        return None
    for i in range(n):
        if env.get(f"sky.name.{i}") == want:
            return i
    return None


def sky_for_track(course_path: str, track: int, track_name: str = ""):
    """`(Sky, texture bundle, index, night)` for one track, or None.

    `BG.DAT` and `SYSTEM.DAT` sit beside `COURSE.DAT` at the disc root.

    Keyed by POSITION, not by name. Both files enumerate the same 63 courses in
    the same order, but COURSE.DAT's name field is a fixed 16 bytes while
    GTENV's strings are length-prefixed, so `arcade_rev_outbahn` is truncated in
    one and not the other and a name lookup silently loses that course its sky.
    `track_name`, when given, is only a sanity check on the ordering.
    """
    folder = os.path.dirname(course_path)

    def _read(name):
        for cand in (name, name.lower()):
            try:
                return open(os.path.join(folder, cand), "rb").read()
            except OSError:
                continue
        return None

    env_raw, bg_raw = _read("SYSTEM.DAT"), _read("BG.DAT")
    if bg_raw is None:
        return None
    index = night = None
    table = parse_gtenv(env_raw) if env_raw is not None else []
    if 0 <= track < len(table):
        nm, index, night = table[track]
        if track_name and not (nm.startswith(track_name)
                               or track_name.startswith(nm)):
            index = None
    if index is None:
        # No GTENV, or this build's table does not cover the track: the
        # prototype's SYSTEM.ENV answers the same question in text.
        env = system_env_beside(course_path)
        if env is None:
            return None
        index = env_sky_index(env, track)
        if index is None:
            return None
        night = False
    ents = arc_index(bg_raw)
    if len(ents) < 2 * index + 2:
        return None
    sky = parse_sky(arc_entry(bg_raw, 2 * index + 1))
    if sky is None:
        return None
    return sky, arc_entry(bg_raw, 2 * index), index, night


def _build_sky_mesh(name, sky, scale, make_material, report, tex=None):
    """The dome as one mesh.

    Corner order is the `.bso`'s, not the roadway's: a sky primitive stores
    literal PS1 packet operands, so a quad is the console's Z-order and the
    polygon loop is (0, 1, 3, 2).

    Axis mapping follows GT1's ROADWAY. GT2 maps a sky vertex `(x, y, z)` to
    `(-x, z, y)`; GT1's world is the mirror of GT2's along that Blender Y, so it
    is `(-x, -z, y)` here -- the same extra negation the roadway takes. That is a
    mirror rather than a rotation, so the stored winding is reversed to keep the
    dome's faces consistent.
    """
    import bpy  # noqa
    bverts = [(-v[0] * scale, -v[2] * scale, v[1] * scale) for v in sky.verts]
    faces, loop_colors, loop_uvs, face_keys = [], [], [], []
    for pr in gt2.usable_prims(sky.prims):
        f = pr.indices
        order = (0, 1, 3, 2) if len(f) == 4 else (0, 1, 2)
        order = tuple(reversed(order))
        faces.append(tuple(f[k] for k in order))
        loop_colors.append([pr.colors[k] for k in order])
        loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
        face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)
    if not faces:
        return None
    return _build_chunk_mesh(name, bverts, faces, loop_colors, loop_uvs,
                             face_keys, make_material, report, tex)


# --- Blender ----------------------------------------------------------------

def import_gt1_course(filepath: str, data: bytes, context, *,
                      track: int = 0, report=None,
                      import_textures: bool = True,
                      import_sprites: bool = True,
                      import_glare: bool = True,
                      import_lod_world: bool = True,
                      import_props: bool = True,
                      import_sky: bool = True,
                      sky_radius: float = 1500.0,
                      prop_depth_bias: float = 0.0,
                      texture_mode: str = "PAGE") -> Tuple[int, int, int, int]:
    """Import one GT1 track out of `COURSE.DAT`.

    `data` is the whole archive; `track` is an index into `track_entries()`,
    which enumerates the archive rather than assuming retail's 63. Returns the
    add-on's usual `(objects, vertices, faces, shapes)` tally.
    """
    import bpy  # noqa

    def _report(msg):
        if report:
            report(msg)

    tracks = track_entries(data)
    if not (0 <= track < len(tracks)):
        _report(f"archive holds {len(tracks)} tracks; no track {track}")
        return 0, 0, 0, 0
    model_entry, bundle_entry, name = tracks[track]
    model = arc_entry(data, model_entry)
    tro = parse_gt1_model(model)
    if tro is None:
        _report(f"track {track} ({name}) is not a GT-PS model")
        return 0, 0, 0, 0
    _report(f"GT1 {name}: version 0x{tro.version:08X}, {len(tro.chunks)} chunks, "
            f"{getattr(tro, 'tex_count', 0)} texture descriptors")

    vram = None
    if import_textures:
        vram = (load_bundle_vram(arc_entry(data, bundle_entry))
                if bundle_entry is not None else None)
        if vram is None:
            _report("textures: numpy unavailable or bundle unreadable; "
                    "importing untextured")
    # PAGE hands (tpage, clut) straight to the shared GT2 factory, exactly as
    # before; the other two modes recover individual textures out of the pages
    # first and rewrite every UV to match. See TextureMapper.
    tex = TextureMapper(texture_mode, vram, _report, tag="GT1")
    tex.build(collect_tex_refs(model, tro, sprites=import_sprites,
                               lod=import_lod_world, props=import_props))
    make_material = tex.material

    root = bpy.data.collections.new(f"GT1 {name}")
    context.scene.collection.children.link(root)
    lod_root = None

    n_face = n_sprite = n_chunk = n_vert = n_lod = n_lod_face = 0
    for ch in tro.chunks:
        if not ch.verts:
            continue
        ox, oy, oz = chunk_origin(ch.center_raw)
        s = _GT1_POOL_SCALE
        # Pool order is GT2's -- (X, Z, height) -- but GT1's world runs the
        # OTHER WAY along component 2. Feeding it through GT2's mapping, which
        # mirrors X alone, therefore applies one net mirror and turns every face
        # inside out: only 18.4% of near-horizontal textured faces end up
        # pointing upward, and the course renders as black backfaces. Negating
        # BOTH X and Y is a rotation rather than a mirror, so handedness is
        # preserved and the same faces come out 81.6% up, against 90.4% for GT2
        # read with its own settings. It also lands GT1's shared circuits in the
        # same orientation as GT2's, which is what makes them comparable.
        # Chunk-LOCAL, with the origin carried on the object below. Baking the
        # origin into these instead works for the solid geometry and then
        # silently drops every billboard on the world origin, because the
        # sprite corners are built separately.
        bverts = [(-v[0] * s, -v[1] * s, v[2] * s) for v in ch.verts]
        faces, loop_colors, loop_uvs, face_keys = [], [], [], []
        n_sprite_here = 0
        for pr in gt2.usable_prims(ch.prims):
            f = list(pr.indices)
            order = (0, 1, 2, 3) if len(f) == 4 else (0, 1, 2)
            faces.append(tuple(f[k] for k in order))
            loop_colors.append([pr.colors[k] for k in order])
            loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
            face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)

        if import_sprites:
            sd1, sd2 = ch._sd
            sprites = parse_sprites(model, sd1, tro.tex_table)
            if sprites:
                cx = sum(v[0] for v in ch.verts) / len(ch.verts)
                cy = sum(v[1] for v in ch.verts) / len(ch.verts)
                for sp in sprites:
                    corners = gt2._billboard_corners(sp, (0, 1), 2, (cx, cy))
                    first = len(bverts)
                    bverts.extend((-c[0] * s, -c[1] * s, c[2] * s)
                                  for c in corners)   # same local frame
                    faces.append((first + 0, first + 1, first + 3, first + 2))
                    loop_colors.append([sp.color] * 4)
                    loop_uvs.append(gt2._sprite_uv_order(sp.uvs))
                    face_keys.append((sp.tpage, sp.clut))
                    n_sprite += 1
                    n_sprite_here += 1
        if not faces:
            continue

        mesh = _build_chunk_mesh(f"gt1_chunk_{ch.index:03d}", bverts, faces,
                                 loop_colors, loop_uvs, face_keys,
                                 make_material, _report, tex)
        obj = bpy.data.objects.new(f"gt1_chunk_{ch.index:03d}", mesh)
        obj.location = (-ox * s, -oz * s, oy * s)
        obj["gt1_chunk_index"] = ch.index
        obj["gt1_origin_raw"] = (ox, oy, oz)
        obj["gt1_sprite_faces"] = n_sprite_here
        root.objects.link(obj)
        n_face += len(faces)
        n_vert += len(bverts)
        n_chunk += 1

    # The second ShapeData, as its own collection. Same world transform, so it
    # lands on top of the roadway -- which is exactly why it is not merged.
    if import_lod_world:
        for ch in tro.chunks:
            if not getattr(ch, "lod_prims", None):
                continue
            ox, oy, oz = chunk_origin(ch.center_raw)
            s = _GT1_POOL_SCALE
            bverts = [(-v[0] * s, -v[1] * s, v[2] * s) for v in ch.lod_verts]
            faces, loop_colors, loop_uvs, face_keys = [], [], [], []
            for pr in gt2.usable_prims(ch.lod_prims):
                f = list(pr.indices)
                order = (0, 1, 2, 3) if len(f) == 4 else (0, 1, 2)
                faces.append(tuple(f[k] for k in order))
                loop_colors.append([pr.colors[k] for k in order])
                loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
                face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)
            if not faces:
                continue
            if lod_root is None:
                lod_root = bpy.data.collections.new("GT1 Low-detail World")
                root.children.link(lod_root)
            mesh = _build_chunk_mesh(f"gt1_lod_{ch.index:03d}", bverts, faces,
                                     loop_colors, loop_uvs, face_keys,
                                     make_material, _report, tex)
            obj = bpy.data.objects.new(f"gt1_lod_{ch.index:03d}", mesh)
            obj.location = (-ox * s, -oz * s, oy * s)
            obj["gt1_chunk_index"] = ch.index
            obj["gt1_lod_world"] = True
            lod_root.objects.link(obj)
            n_lod += 1
            n_lod_face += len(faces)
        if lod_root is not None:
            _exclude_from_view_layer(context, lod_root)
            _report(f"low-detail world: {n_lod} chunks, {n_lod_face} faces "
                    f"(second ShapeData; collection unticked, it sits on top of "
                    f"the roadway)")

    if import_glare:
        glares = []
        for ch in tro.chunks:
            ox, oy, oz = chunk_origin(ch.center_raw)
            for g in parse_glares(model, ch._sd[0]):
                glares.append((g, (ox, oy, oz)))
        if glares:
            n = _build_glares(glares, root, _report)
            _report(f"lamp glare: {n} orbs (ShapeData slot 9)")

    if import_sky:
        got = sky_for_track(filepath, track, name)
        if got is None:
            _report("sky: no BG.DAT / SYSTEM.DAT beside COURSE.DAT, or this "
                    "track is not in the environment table")
        else:
            sky, bundle, index, night = got
            svram = load_bundle_vram(bundle) if import_textures else None
            # The dome carries its own bundle, so it gets its own mapper -- and
            # in ATLAS mode its own atlas, rather than being packed with a
            # course it shares no VRAM with.
            stex = TextureMapper(texture_mode, svram, _report, tag="GT1_sky")
            stex.build(sky_tex_refs(sky))
            smat = stex.material
            radius = max((max(abs(c) for c in v) for v in sky.verts), default=0)
            scale = float(sky_radius) / radius if radius else 1.0
            mesh = _build_sky_mesh(f"gt1_sky_{index:02d}", sky, scale, smat,
                                   _report, stex)
            if mesh is not None:
                obj = bpy.data.objects.new(f"gt1_sky_{index:02d}", mesh)
                obj["gt1_sky_index"] = index
                obj["gt1_sky_night"] = night
                obj["gt1_sky_colour_a"] = sky.colour_a
                obj["gt1_sky_colour_b"] = sky.colour_b
                coll = bpy.data.collections.new("GT1 Sky")
                root.children.link(coll)
                coll.objects.link(obj)
                _report(f"sky: BG.DAT index {index}"
                        f"{' (night)' if night else ''}, "
                        f"{len(sky.verts)} verts, {len(mesh.polygons)} faces, "
                        f"{len(sky.textures)} textures, radius {sky_radius:g}")

    n_prop = n_prop_face = 0
    if import_props:
        n_prop, n_prop_face = _build_props(model, tro, root, make_material,
                                           _report, context, prop_depth_bias,
                                           tex)
    tex.finish()
    _report(f"GT1 {name}: {n_chunk} chunks, {n_face} faces, {n_sprite} "
            f"billboards, {n_prop} props")
    return (n_chunk + n_prop, n_vert, n_face + n_prop_face,
            len(tro.chunks) + n_prop)


# Yaw sign, measured rather than reasoned about. Each placed prop's principal
# horizontal axis is compared against the heading of the nearest roadway chunk,
# over all 63 tracks, restricted to shapes elongated enough for that axis to
# mean something. Negating the stored angle -- the same sign GT2 uses -- gives a
# median error of 12.9 degrees with 51.1% inside 15; leaving it positive gives
# 28.6 and 34.9% (427 samples at 8:1 elongation; 615 at 3:1 say the same).
#
# Worth recording that the stored value itself is unchanged from GT2: of 325
# props that match a GT2 prop to within 2 world units across the five circuits
# both games ship, ALL 325 carry an identical yaw.
_PROP_YAW_SIGN = -1.0


def _build_prop_mesh(name, verts, prims, scale, make_material, sprites,
                     report, tex=None):
    """One prop LOD shape as a mesh, in its own local space.

    This is GT2's mapping unchanged -- vertex `(x, y, z)` to Blender
    `(-x, -z, y)`, with the winding reversed because that mapping flips
    handedness. The roadway needed an extra negation for GT1 and props do not:
    a prop's LOCAL space is not mirrored between the games, only the world
    positions those props are placed at, and those are already handled by
    negating both horizontal axes of the instance position. Reading a prop's own
    texture settles it, the same way it settled GT2's: with the extra negation
    the "Bridgestone" sign beside High Speed Ring's main straight renders
    back to front.
    """
    import bpy  # noqa
    bverts = [(-v[0] * scale, -v[2] * scale, v[1] * scale) for v in verts]
    faces, loop_colors, loop_uvs, face_keys = [], [], [], []
    for pr in gt2.usable_prims(prims):
        f = pr.indices
        order = (0, 1, 2, 3) if len(f) == 4 else (0, 1, 2)
        order = tuple(reversed(order))
        faces.append(tuple(f[k] for k in order))
        loop_colors.append([pr.colors[k] for k in order])
        loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
        face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)
    n_sprite = 0
    for sp in sprites:
        # Prop vertices are (X, height, Z), so a billboard spreads across axes
        # 0 and 2 and rises along 1, turned toward its own shape origin.
        corners = gt2._billboard_corners(sp, (0, 2), 1, (0, 0))
        first = len(bverts)
        bverts.extend((-c[0] * scale, -c[2] * scale, c[1] * scale)
                      for c in corners)
        loop = (first + 0, first + 1, first + 3, first + 2)
        faces.append(tuple(reversed(loop)))
        loop_colors.append([sp.color] * 4)
        loop_uvs.append(list(reversed(gt2._sprite_uv_order(sp.uvs))))
        face_keys.append((sp.tpage, sp.clut))
        n_sprite += 1
    if not faces:
        return None
    mesh = _build_chunk_mesh(name, bverts, faces, loop_colors, loop_uvs,
                             face_keys, make_material, report, tex)
    mesh["gt1_sprite_faces"] = n_sprite
    return mesh


# --- texture modes ----------------------------------------------------------
# The machinery is shared with GT2 and lives in gt2.py, which cannot import
# this module. These are the names the GT1 side and its tests use.
_uv_texel = gt2._uv_texel
_uv_box = gt2._uv_box
_merge_rects = gt2._merge_rects
_shelf_pack = gt2._shelf_pack
TextureMapper = gt2.TextureMapper


def collect_tex_refs(model, tro, sprites=True, lod=True, props=True):
    """Every (tpage, clut) and texel box the course is going to draw.

    A separate walk rather than a hook in the build, because the atlas has to be
    packed before the first UV is written and the pack needs the whole set. It
    re-parses the prop shapes, which is pure Python and costs a fraction of the
    time spent building the meshes.
    """
    refs = []
    for ch in tro.chunks:
        for pr in ch.prims:
            if pr.uvs:
                refs.append(((pr.tpage, pr.clut), _uv_box(pr.uvs)))
        if lod:
            for pr in getattr(ch, "lod_prims", None) or []:
                if pr.uvs:
                    refs.append(((pr.tpage, pr.clut), _uv_box(pr.uvs)))
        if sprites:
            for sp in parse_sprites(model, ch._sd[0], tro.tex_table):
                refs.append(((sp.tpage, sp.clut), _uv_box(sp.uvs)))
    if props:
        seen = set()
        for chain in prop_lod_chains(model, tro):
            for _d, sd in chain:
                if sd in seen:
                    continue
                seen.add(sd)
                got = parse_prop_shape(model, sd)
                if not got:
                    continue
                _v, prims, _s, sprs = got
                for pr in prims:
                    if pr.uvs:
                        refs.append(((pr.tpage, pr.clut), _uv_box(pr.uvs)))
                for sp in sprs:
                    refs.append(((sp.tpage, sp.clut), _uv_box(sp.uvs)))
    return refs


def sky_tex_refs(sky):
    return [((pr.tpage, pr.clut), _uv_box(pr.uvs))
            for pr in sky.prims if pr.uvs]


def _build_chunk_mesh(name, bverts, faces, loop_colors, loop_uvs, face_keys,
                      make_material, report, tex=None):
    """One chunk mesh, with its per-loop colour and UV attributes."""
    import bpy  # noqa
    # Every mesh in the importer funnels through here, so this is the one
    # place the texture mode has to rewrite keys and UVs.
    if tex is not None:
        face_keys, loop_uvs = tex.remap(face_keys, loop_uvs)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(bverts, [], faces)
    # See gt2.usable_prims(): validate() must not run before the attributes
    # below, or a single dropped face shifts all of them.
    if len(mesh.polygons) != len(faces):
        report(f"{name}: mesh has {len(mesh.polygons)} faces for "
               f"{len(faces)} primitives; skipping attributes")
    else:
        slot_of: Dict[object, int] = {}
        for k in face_keys:
            if k not in slot_of:
                slot_of[k] = len(slot_of)
                mesh.materials.append(make_material(k))
        if len(slot_of) > 1:
            for poly, k in zip(mesh.polygons, face_keys):
                poly.material_index = slot_of[k]
        # The shared GT2 material factory reads this exact attribute name;
        # anything else and every texel is multiplied by a black vertex colour
        # and the whole course renders solid black.
        col = mesh.color_attributes.new(
            name="GT2_Color", type="BYTE_COLOR", domain="CORNER")
        uvl = mesh.uv_layers.new(name="UVMap")
        li = 0
        for cols, uvs in zip(loop_colors, loop_uvs):
            for k in range(len(cols)):
                col.data[li].color = (cols[k][0], cols[k][1], cols[k][2], 1.0)
                if uvs:
                    uvl.data[li].uv = uvs[k]
                li += 1
    mesh.update()
    return mesh


def _exclude_from_view_layer(context, collection):
    """Untick a collection in the outliner without deleting anything.

    The low-detail world sits exactly on top of the roadway, so leaving it
    enabled means z-fighting on every surface. Excluding it keeps it in the file
    and one click away instead of hiding it somewhere non-obvious.
    """
    def walk(layer):
        if layer.collection is collection:
            layer.exclude = True
            return True
        return any(walk(c) for c in layer.children)
    try:
        walk(context.view_layer.layer_collection)
    except Exception:
        pass


def _build_props(data, tro, root, make_material, report, context=None,
                 depth_bias=0.0, tex=None):
    """Place every instanced prop, each drawn at its most detailed LOD level."""
    import bpy  # noqa
    import math
    instances = parse_instances(data, getattr(tro, "layout", None)
                                and tro.layout.group_base)
    chains = prop_lod_chains(data, tro)
    if not instances or not chains:
        return 0, 0
    group_mask = 0
    try:
        group_mask = gt2.instance_group_mask(data, tro.chunks)
    except Exception:
        pass
    coll = bpy.data.collections.new("GT1 Props")
    root.children.link(coll)
    far_coll = None
    cache = {}
    n_obj = n_face = missing = n_far = 0
    for n, inst in enumerate(instances):
        if not (0 <= inst.lod_index < len(chains)) or not chains[inst.lod_index]:
            missing += 1
            continue
        mesh = None
        # A chain is (max distance, shape) nearest-first, and a chain that opens
        # with an EMPTY shape means the game draws nothing up close: the object
        # only appears in a distance band further out. On `circuit`, LOD 29
        # switches at 50 and 700 world units, so between those it draws a
        # low-detail copy of the roadway and inside 50 it draws nothing at all.
        #
        # Falling straight through to the next level therefore drops a coarse
        # duplicate of the road into the middle of the track. 125 of the 63
        # tracks' 2,728 instances are these, and they are built into their own
        # unticked collection rather than the props proper. An empty level with
        # a billboard list is a different thing and is NOT affected -- that is
        # how a distant object is swapped for a single sprite, and
        # parse_prop_shape() returns it rather than None.
        distant = parse_prop_shape(data, chains[inst.lod_index][0][1]) is None
        for _dist, sd in chains[inst.lod_index]:
            if sd not in cache:
                cache[sd] = None
                got = parse_prop_shape(data, sd)
                if got is not None:
                    verts, prims, scale, sprites = got
                    cache[sd] = _build_prop_mesh(
                        f"gt1_lod_{inst.lod_index:03d}", verts, prims, scale,
                        make_material, sprites, report, tex)
            mesh = cache[sd]
            if mesh is not None:
                break
        if mesh is None:
            missing += 1
            continue
        obj = bpy.data.objects.new(
            f"gt1_{'far' if distant else 'prop'}_{n:04d}"
            f"_lod{inst.lod_index:03d}", mesh)
        px, py, pz = inst.pos
        # Position is 16.16 and ordered like Center: (X, height, Z). Both
        # horizontal axes are negated, matching the roadway.
        w = gt2._WORLD_SCALE
        # `depth_bias` sinks the prop. Zero by default: see the note on
        # _PROP_DEPTH_BIAS_DOC in __init__.py for why it is ever wanted.
        obj.location = (-px * w, -pz * w, py * w - depth_bias)
        obj.rotation_euler = (0.0, 0.0,
                              _PROP_YAW_SIGN * inst.yaw * math.tau / 4096.0)
        sx, sy, sz = inst.scale
        obj.scale = (sx / 4096.0, sz / 4096.0, sy / 4096.0)
        obj["gt1_instance_index"] = n
        obj["gt1_lod_index"] = inst.lod_index
        obj["gt1_instance_group"] = inst.group
        obj["gt1_lod_levels"] = len(chains[inst.lod_index])
        obj["gt1_group_requested"] = bool(inst.group >= 32
                                          or (group_mask >> inst.group) & 1)
        obj["gt1_distant_standin"] = distant
        if distant:
            if far_coll is None:
                far_coll = bpy.data.collections.new("GT1 Distant Stand-ins")
                root.children.link(far_coll)
            far_coll.objects.link(obj)
            n_far += 1
        else:
            coll.objects.link(obj)
            n_obj += 1
            n_face += len(mesh.polygons)
    n_sprite = sum(m.get("gt1_sprite_faces", 0)
                   for m in cache.values() if m is not None)
    if far_coll is not None and context is not None:
        _exclude_from_view_layer(context, far_coll)
    report(f"props: {n_obj} instances of "
           f"{sum(1 for m in cache.values() if m)} LOD meshes, {n_face} faces "
           f"({n_sprite} of them billboards)"
           + (f"; {missing} skipped" if missing else ""))
    if n_far:
        report(f"distant stand-ins: {n_far} instances whose nearest LOD level is "
               f"empty, so the game draws nothing up close (collection unticked)")
    return n_obj, n_face


def _build_glares(glares, root, report):
    """One merged emissive mesh, the same reconstruction GT2's glare uses."""
    import bpy  # noqa
    make_glare, _glare_cache = gt2._make_glare_material_factory()
    s = _GT1_POOL_SCALE
    verts, faces, cols, uvs, keys = [], [], [], [], []
    for g, (ox, oy, oz) in glares:
        cx = -(g.pos[0] + ox) * s
        cy = -(g.pos[1] + oz) * s
        cz = (g.pos[2] + oy) * s
        r = g.size * _GT1_POOL_SCALE * 0.5
        first = len(verts)
        verts.extend([(cx - r, cy, cz - r), (cx + r, cy, cz - r),
                      (cx + r, cy, cz + r), (cx - r, cy, cz + r)])
        faces.append((first, first + 1, first + 2, first + 3))
        cols.append([g.color] * 4)
        uvs.append([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        keys.append(g.color)
    if not faces:
        return 0
    mesh = bpy.data.meshes.new("gt1_lamp_glare")
    mesh.from_pydata(verts, [], faces)
    if len(mesh.polygons) == len(faces):
        slot_of = {}
        for k in keys:
            if k not in slot_of:
                slot_of[k] = len(slot_of)
                mesh.materials.append(make_glare(k))
        for poly, k in zip(mesh.polygons, keys):
            poly.material_index = slot_of[k]
        col = mesh.color_attributes.new(
                name="GT2_Color", type="BYTE_COLOR", domain="CORNER")
        uvl = mesh.uv_layers.new(name="UVMap")
        li = 0
        for cc, uu in zip(cols, uvs):
            for k in range(4):
                col.data[li].color = (cc[k][0], cc[k][1], cc[k][2], 1.0)
                uvl.data[li].uv = uu[k]
                li += 1
    mesh.update()
    obj = bpy.data.objects.new("gt1_lamp_glare", mesh)
    obj["gt1_glare_count"] = len(faces)
    coll = bpy.data.collections.new("GT1 Lamp Glare")
    root.children.link(coll)
    coll.objects.link(obj)
    return len(faces)
