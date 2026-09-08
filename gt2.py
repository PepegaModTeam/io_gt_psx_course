"""GT2 `.tro` (TRack Object) importer.

The GT2-demo and retail tracks (`@(#)GT-PS` magic) are PlayStation 1 track
objects.

Executable used: SCUS-94455 (GT2 Arcade NTSC-U v1.1)

The geometry encoding below is read directly out of the game's own renderer.

Two geometry streams:

1. INSTANCED LOD MESHES (props/buildings/signs). Placed by 16.16 world records
   from InstancedObjectOffsets, drawn from LODData records that share the
   ShapeData layout used by the track chunks.

2. TRACKCHUNK SHAPEDATA (the drivable roadway). Placed by each chunk's 16.16
   world position (`UnkVec_0x18`).

PRIMITIVE ENCODING - solved statically from GT2.OVL.
All six overlays in GT2.OVL load at 0x80010000, ahead of the resident EXE at
0x8005D5C0; `overlay0` holds the race renderer. Its chunk draw routine has one
unrolled loop per primitive list (ShapeData listCounts at +0x30+2j, listPtrs at
+0x04+4j), and each loop decodes a record as:

    lw   w0, 0(rec)  ;  lw  w1, 4(rec)
    sll  t, w0, 3    ;  andi t, t, 0xff8   ->  (w0        & 0x1FF) * 8
    sra  t, w0, 6    ;  andi t, t, 0xff8   -> ((w0 >>  9) & 0x1FF) * 8
    sra  t, w0, 0xf  ;  andi t, t, 0xff8   -> ((w0 >> 18) & 0x1FF) * 8
    sll  t, w1, 3    ;  andi t, t, 0xff8   ->  (w1        & 0x1FF) * 8   [quads]

so a primitive carries FOUR 9-BIT VERTEX INDICES at bits 0, 9, 18 and 32 -- not
byte indices, and not the 10-bit triple used elsewhere. The `*8` is the 8-byte
vertex stride, itself confirmed by vertexPtr->next-pointer span / vertexCount
= 8 on all 13,209 chunks that have one.

Validated on 699,298 primitives across all 126 retail `.tro` files: 100% of
indices resolve inside the chunk's own vertexCount, and decoded primitives span
636 units on average versus 1,987 for random vertex quadruples from the same
pool -- i.e. they are real, spatially coherent faces.

This supersedes the "consecutive run" heuristic, which produced a road-shaped 
surface but not the true topology.

Per-slot record layout (slot index IS the primitive type; strides measured
unanimous across all 14,387 chunks, and matched by the `count*12` / `count*20`
/ `count*24` address arithmetic in each loop):

    slot 0 F3  12   slot 2 G3  20   slot 4 FT3 12   slot 6 GT3 20
    slot 1 F4  12   slot 3 G4  24   slot 5 FT4 12   slot 7 GT4 24

    bytes 0-3   w0: idx0 bits 0-8, idx1 bits 9-17, idx2 bits 18-26,
                    bits 27-28 select a 64-byte entry from a runtime table,
                    bits 29-31 flags
    bytes 4-7   w1: idx3 bits 0-8, texture-descriptor id bits 9-22, bit 27 flag
    bytes 8-10  RGB (corner 0 for gouraud, the whole face otherwise)
    byte  11    PS1 primitive code (0x20 F3, 0x28 F4, 0x30 G3, 0x38 G4,
                0x24 FT3, 0x2C FT4, 0x34 GT3, 0x3C GT4)
    bytes 12-14, 16-18, 20-22   further RGB triplets for gouraud corners 1..3
                (bytes 15/19/23 are always zero padding)

TEXTURE DESCRIPTORS. UVs are NOT stored per primitive -- 12 bytes cannot hold
four UV pairs. The renderer computes `((w1 >> 4) & 0x7FFE0)` -- that is,
descriptor id `(w1 >> 9) & 0x3FFF` times 32 bytes -- into a table whose pointer
it reads from TrackChunkTable+0x08 (the field previously logged as
`UnkOffset`). Each 32-byte descriptor is two 16-byte LOD entries:

    +0x00  u8 u0, v0 ; u16 clut      +0x08  u8 u2, v2, u3, v3
    +0x04  u8 u1, v1 ; u16 tpage     +0x0C  u16 lod_threshold ; u16 pad

Entry 0 is full resolution, entry 1 a half-size mip elsewhere in the same
texture page; the renderer picks between them on projected depth. This importer
uses entry 0. Every descriptor id in all 126 files resolves inside its file.

Vertices in both streams are 3x s16 (X, Y, Z) + s16 pad, 8 bytes each.

CHUNK PLACEMENT - likewise read out of the renderer, at 0x80026bb4,
which runs once per visible chunk just before the draw and is the only place the
roadway's GTE translation is set:

    lui  $s2, 0xffc0        ; MASK = 0xFFC00000
    lw   $s5, 0x30($a0)     ; chunk Center (+0x30, 16.16, absolute world)
    and  $v0, $s5, $s2      ; Center & MASK
    addu $v0, $fp, $v0      ; + camera (dropped here; we want world space)
    sra  $a1, $v0, 0xa      ; >> 10

    origin = (Center & 0xFFC00000) >> 10       # see chunk_origin()

The mask snaps the origin to a 2^22 (16.16) grid = 64 world units and the pool
holds the remainder, which is why every chunk's pool sits in the same small box.
The `>> 10` is the unit conversion: 16.16 world / 1024 is exactly the pool's
1/64-world-unit scale. There is NO per-chunk rotation -- the GTE rotation is the
camera matrix, merely left-shifted for precision by 0x80081994, and no chunk
header field correlates with the track heading (best R = 0.28).

`UnkVec_0x18` is the chunk's START point and trails Center by half a chunk; the
renderer uses Center at +0x30 both here and for the LOD distance test.

Coordinate frames:
  * Chunk pool is ordered (X, Z, Y) while Center is (X, Y, Z) -- the swap is
    explicit in the renderer's `mtc2` order (Center.Z -> IR2, Center.Y -> IR3).
    Pairing them straight through leaves 18.5% of chunks a whole grid cell out
    of place; pairing pool[1] with Center.Z and pool[2] with Center.Y, 1.6%.
  * GT2 is Y-up. Blender gets (-x, z, y) from Center-ordered triples and
    (-x, y, z) from pool-ordered ones, which is the same physical mapping.
  * X is mirrored (GT2 handedness vs Blender); winding reversed to compensate.
  * Instances / LOD locals: raw (x,y,z) -> Blender (-x, z, y), scale 1/256.

Pointer remap: file offset = runtime pointer - startPos, where
startPos = InstancedObjectOffsets[0] - 0x19C (0 for the loose files).
"""

import os
import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

TRO_MAGIC = b"@(#)GT-PS"

_WORLD_SCALE = 1.0 / 65536.0   # chunk/instance world positions are 16.16 fixed
_CHUNK_LOCAL_SCALE = 1.0 / 64.0  # chunk-local verts (matches chunk-to-chunk spacing)
_LOD_LOCAL_SCALE = 1.0 / 256.0   # LOD/object-local verts (8.8-ish)

# ShapeData list slot -> (primitive code, record stride, corner count, textured,
# gouraud).  The slot index selects the primitive type outright: every list in
# every retail chunk carries the code below at record byte 11, and the loop for
# that slot in overlay0 multiplies its count by exactly this stride.
_SLOTS = {
    0: (0x20, 12, 3, False, False),   # F3   flat tri
    1: (0x28, 12, 4, False, False),   # F4   flat quad
    2: (0x30, 20, 3, False, True),    # G3   gouraud tri
    3: (0x38, 24, 4, False, True),    # G4   gouraud quad
    4: (0x24, 12, 3, True,  False),   # FT3  textured tri
    5: (0x2C, 12, 4, True,  False),   # FT4  textured quad
    6: (0x34, 20, 3, True,  True),    # GT3  textured gouraud tri
    7: (0x3C, 24, 4, True,  True),    # GT4  textured gouraud quad
}

_TEX_ENTRY_SIZE = 32   # two 16-byte LOD entries per descriptor


_ORIGIN_MASK = 0xFFC00000   # overlay0: lui $s2, 0xffc0


def chunk_origin(center_raw: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """The chunk's vertex-pool origin, in the same 1/64-world units as the pool.

    From the per-chunk GTE setup at 0x80026bb4 (called once per visible chunk,
    immediately before the draw): each component of the chunk's Center (+0x30,
    16.16) is masked with 0xFFC00000, added to the camera position, and shifted
    right by 10 before going through MVMVA into TRX/TRY/TRZ. The mask snaps the
    origin to a 2^22 (16.16) grid = 4096 pool units = 64 world units, and the
    pool stores the remainder -- which is why every chunk's pool sits in the
    same small coordinate box."""
    out = []
    for v in center_raw:
        m = (v & 0xFFFFFFFF) & _ORIGIN_MASK
        if m & 0x80000000:
            m -= 1 << 32          # back to signed before the arithmetic shift
        out.append(m >> 10)
    return (out[0], out[1], out[2])


# Per-vertex attributes -- the descriptor's UVs and the gouraud corner colours
# -- are stored in INDEX order, matching indices[0..3] directly, even though the
# packet's screen coordinates are permuted (V0<-i1 etc). Measured: reading them
# in index order leaves 0.22% of textured quads with a self-intersecting UV
# quad; applying the packet permutation leaves 99.58%.

def _prim_indices(w0: int, w1: int, corners: int) -> List[int]:
    """The four 9-bit vertex indices packed at bits 0, 9, 18 and 32."""
    idx = [w0 & 0x1FF, (w0 >> 9) & 0x1FF, (w0 >> 18) & 0x1FF, w1 & 0x1FF]
    return idx[:corners]


@dataclass
class TroPrim:
    """One decoded primitive: pool indices, per-corner RGB, and UVs."""
    slot: int
    indices: Tuple[int, ...]
    colors: List[Tuple[float, float, float]]
    uvs: Optional[List[Tuple[float, float]]] = None
    tpage: int = 0
    clut: int = 0


@dataclass
class TroChunk:
    index: int
    offset: int
    prev_index: int
    next_index: int
    world_raw: Tuple[int, int, int]
    center_raw: Tuple[int, int, int] = (0, 0, 0)
    verts: List[Tuple[int, int, int]] = field(default_factory=list)
    prims: List[TroPrim] = field(default_factory=list)


@dataclass
class Tro:
    version: int
    start_pos: int
    tex_table: int
    chunks: List[TroChunk]


def _resolve(ptr: int, start_pos: int) -> int:
    return ptr - start_pos


def _read_s16_verts(data: bytes, ptr: int, count: int) -> List[Tuple[int, int, int]]:
    out = []
    for i in range(max(0, count)):
        off = ptr + i * 8
        if off < 0 or off + 8 > len(data):
            break
        x, y, z, _w = struct.unpack_from("<4h", data, off)
        out.append((x, y, z))
    return out


def _texel_uv(u: int, v: int) -> Tuple[float, float]:
    """One PS1 texel coordinate as a Blender UV, addressing the texel CENTRE.

    The half-texel matters, and not only for precision. PS1 UVs are integer
    texel indices, so texel row 0 is the top row of the page; mapping it to the
    corner V = 1.0 puts it exactly on the wrap seam, and Blender's REPEAT
    extension sends V = 1.0 to V = 0.0 -- the BOTTOM row, a completely unrelated
    part of the page. 126,235 of the retail set's 645,613 textured chunk faces
    have at least one corner at v = 0, and the 57 whose corners are ALL at v = 0
    (GT2 stretches a single texel line across a face as a cheap colour band)
    render entirely from the wrong row. Centres put every sample safely inside
    its own texel.
    """
    return ((u + 0.5) / 256.0, 1.0 - (v + 0.5) / 256.0)


def _read_tex_descriptor(data: bytes, table: int, tex_id: int, corners: int):
    """Full-resolution (LOD entry 0) UVs, tpage and clut for a descriptor id."""
    off = table + tex_id * _TEX_ENTRY_SIZE
    if off < 0 or off + 16 > len(data):
        return None
    u0, v0 = data[off], data[off + 1]
    clut = struct.unpack_from("<H", data, off + 2)[0]
    u1, v1 = data[off + 4], data[off + 5]
    tpage = struct.unpack_from("<H", data, off + 6)[0]
    u2, v2 = data[off + 8], data[off + 9]
    u3, v3 = data[off + 10], data[off + 11]
    uv = [(u0, v0), (u1, v1), (u2, v2), (u3, v3)][:corners]
    return ([_texel_uv(u, v) for u, v in uv], tpage, clut)


def _read_maybe_gz(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if raw[:2] == b"\x1f\x8b":
        import gzip
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return None
    return raw


def trp_path_for(tro_path: str) -> Optional[str]:
    """The `.trp` texture sidecar next to a `.tro`, plain or gzipped."""
    import os
    base = tro_path
    if base.lower().endswith(".gz"):
        base = base[:-3]
    if base.lower().endswith(".tro"):
        base = base[:-4]
    for cand in (base + ".trp", base + ".trp.gz"):
        if os.path.exists(cand):
            return cand
    return None


def load_trp_vram(path: str):
    """Replay a `.trp` into a PS1 VRAM image: 512 rows x 1024 halfwords.

    The file is `u32 count` then that many TIM-family images, every one of them
    4-bit CLUT (pmode 0) across all 126 retail courses -- 14,138 images, each
    file parsing to exact EOF. Each image carries its own destination VRAM
    coordinates, so replaying them into a single 1MB framebuffer reproduces the
    texture memory the primitives' tpage/clut fields address. Returns None if
    numpy is unavailable or the file does not parse.
    """
    raw = _read_maybe_gz(path)
    if raw is None or len(raw) < 4:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    count = struct.unpack_from("<I", raw, 0)[0]
    if not (0 < count < 20000):
        return None
    vram = np.zeros((512, 1024), dtype=np.uint16)
    off = 4
    for _ in range(count):
        if off + 8 > len(raw):
            break
        magic, flag = struct.unpack_from("<2I", raw, off)
        if magic != 0x10:
            break
        o = off + 8
        for _block in range(2 if (flag & 8) else 1):   # CLUT block, then image
            if o + 12 > len(raw):
                return vram
            blen = struct.unpack_from("<I", raw, o)[0]
            x, y, w, h = struct.unpack_from("<4H", raw, o + 4)
            if w and h and o + 12 + w * h * 2 <= len(raw) \
                    and y + h <= 512 and x + w <= 1024:
                px = np.frombuffer(raw, dtype="<u2", count=w * h,
                                   offset=o + 12).reshape(h, w)
                vram[y:y + h, x:x + w] = px
            if blen <= 0:
                return vram
            o += blen
        off = o
    return vram


def page_rgba(vram, tpage: int, clut: int):
    """The 256x256 RGBA texture a (tpage, clut) pair addresses.

    tpage bits 0-3 are the page X base in 64-halfword steps, bit 4 the Y base in
    256-row steps, bits 7-8 the colour mode -- always 0 (4-bit) for track data.
    clut bits 0-5 are the palette X in 16-halfword steps, bits 6-14 its row.
    A palette entry of 0x0000 is fully transparent, which is how GT2 cuts out
    tree and fence sprites.
    """
    import numpy as np
    tx = (tpage & 0xF) * 64
    ty = ((tpage >> 4) & 1) * 256
    cx = (clut & 0x3F) * 16
    cy = (clut >> 6) & 0x1FF
    if cy >= 512 or cx + 16 > 1024 or tx + 64 > 1024 or ty + 256 > 512:
        return None
    pal = vram[cy, cx:cx + 16].astype(np.uint32)
    lut = np.stack([
        ((pal & 0x1F) * 255 // 31).astype(np.uint8),
        (((pal >> 5) & 0x1F) * 255 // 31).astype(np.uint8),
        (((pal >> 10) & 0x1F) * 255 // 31).astype(np.uint8),
        np.where(pal == 0, 0, 255).astype(np.uint8),
    ], axis=1)
    block = vram[ty:ty + 256, tx:tx + 64].astype(np.uint32)
    idx = np.empty((256, 256), dtype=np.uint8)
    for n in range(4):                      # 4 pixels per halfword, low nibble first
        idx[:, n::4] = ((block >> (n * 4)) & 0xF).astype(np.uint8)
    return lut[idx]



def _decode_shapedata(data: bytes, sd: int, start_pos: int, tex_table: int,
                      verts: List[Tuple[int, int, int]]) -> List[TroPrim]:
    """Decode all eight primitive lists of one ShapeData block."""
    nv = len(verts)
    prims: List[TroPrim] = []
    for slot, (_code, stride, corners, textured, gouraud) in _SLOTS.items():
        ptr = _resolve(struct.unpack_from("<I", data, sd + 4 + slot * 4)[0], start_pos)
        count = struct.unpack_from("<h", data, sd + 0x30 + slot * 2)[0]
        if count <= 0 or ptr <= 0 or ptr + count * stride > len(data):
            continue
        for i in range(count):
            off = ptr + i * stride
            w0, w1 = struct.unpack_from("<2I", data, off)
            idx = _prim_indices(w0, w1, corners)
            if any(k >= nv for k in idx) or len(set(idx)) < 3:
                continue
            # RGB: bytes 8-10, then one triplet per further gouraud corner.
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


# --- Instanced LOD meshes (props, buildings, signs) -------------------------
# A SECOND geometry stream with its own renderer at 0x80019b58 in overlay0. It
# reads the SAME ShapeData layout as the track chunks (vertexPtr at +0x00,
# listPtrs at +0x04+4j, vertexCount at +0x2C, listCounts at +0x30+2j) but
# differs in two ways that matter:
#
#   * indices are TEN bits at bits 0, 10 and 20 (plus a 4th at w1 bits 0-9),
#     not the chunks' nine:
#         sll t,w0,3    ; andi t,t,0x1ff8   ->  (w0        & 0x3FF) * 8
#         sra t,w0,7    ; andi t,t,0x1ff8   -> ((w0 >> 10) & 0x3FF) * 8
#         sra t,w0,0x11 ; andi t,t,0x1ff8   -> ((w0 >> 20) & 0x3FF) * 8
#     Verified on 140,348 LOD primitives across all 126 courses: 100% resolve
#     inside their own vertexCount (the chunks' 9-bit reading gives 23%).
#   * records are LARGER, because a prop carries its UVs inline instead of
#     going through the chunks' shared descriptor table. Strides come from each
#     loop's own count arithmetic and are the ones the pre-0.95 importer had:
#     F3 12, F4 12, G3 20, G4 24, FT3 24, FT4 24, GT3 32, GT4 36.
_LOD_STRIDES = {0: 12, 1: 12, 2: 20, 3: 24, 4: 24, 5: 24, 6: 32, 7: 36}

# Fallback only -- the real scale is PER SHAPE, see lod_shape_scale().
_LOD_LOCAL_SCALE = 2.0 ** -8


@dataclass
class TroInstance:
    """One placed prop: which LOD chain to draw and where to put it."""
    group: int
    flags: int
    yaw: int                       # 4096 = one full turn
    lod_index: int
    scale: Tuple[int, int, int]    # 4096 = 1.0
    pos: Tuple[int, int, int]      # 16.16 world, ordered (X, height, Z)


def parse_lod_lookup(data: bytes, start_pos: int) -> List[List[Tuple[int, int]]]:
    """`lod_index` -> [(max_distance, ShapeData offset), ...], nearest first.

    The table at header+0x14 is `u32 count` then that many pointers, each to a
    record of `u32 numLods; numLods x { u32 maxDistance; u32 shapeDataPtr }`.
    The renderer picks a level with `lw $s3, 4($s0 + 4 + idx*8)` — i.e. the
    pointer sits at +8+idx*8 — at 0x8001f990.
    """
    out: List[List[Tuple[int, int]]] = []
    lut = _resolve(struct.unpack_from("<I", data, 0x14)[0], start_pos)
    if not (0 < lut < len(data) - 4):
        return out
    n = struct.unpack_from("<I", data, lut)[0]
    if not (0 < n < 100000):
        return out
    for i in range(n):
        entry = _resolve(struct.unpack_from("<I", data, lut + 4 + i * 4)[0], start_pos)
        lods: List[Tuple[int, int]] = []
        if 0 < entry < len(data) - 8:
            k = struct.unpack_from("<I", data, entry)[0]
            if 0 < k < 64 and entry + 4 + k * 8 <= len(data):
                for j in range(k):
                    dist = struct.unpack_from("<I", data, entry + 4 + j * 8)[0]
                    sp = _resolve(struct.unpack_from("<I", data,
                                                     entry + 8 + j * 8)[0], start_pos)
                    lods.append((dist, sp))
        out.append(lods)
    return out


def parse_instances(data: bytes, start_pos: int) -> List[TroInstance]:
    """The 33 InstancedObjectOffsets groups at header+0x118.

    Each group is `s32 count` then that many 0x1C-byte records."""
    out: List[TroInstance] = []
    for g in range(33):
        p = _resolve(struct.unpack_from("<I", data, 0x118 + g * 4)[0], start_pos)
        if not (0 < p < len(data) - 4):
            continue
        count = struct.unpack_from("<i", data, p)[0]
        if not (0 <= count < 20000) or p + 4 + count * 0x1C > len(data):
            continue
        for k in range(count):
            o = p + 4 + k * 0x1C
            flags, yaw, _unk, lidx = struct.unpack_from("<4h", data, o)
            sx, sy, sz, _sw = struct.unpack_from("<4h", data, o + 8)
            px, py, pz = struct.unpack_from("<3i", data, o + 0x10)
            out.append(TroInstance(g, flags, yaw, lidx, (sx, sy, sz), (px, py, pz)))
    return out


def _decode_lod_shapedata(data: bytes, sd: int, start_pos: int,
                          verts: List[Tuple[int, int, int]]) -> List[TroPrim]:
    """Decode one LOD ShapeData: 10-bit indices and inline UVs.

    The record is the chunk record plus, for textured types, the same 12-byte
    UV/CLUT/TPAGE block the chunks keep in their shared descriptor table:
        +0x0C u8 u0,v0 ; u16 clut
        +0x10 u8 u1,v1 ; u16 tpage
        +0x14 u8 u2,v2,u3,v3
    Gouraud corner colours follow at +0x0C when untextured, +0x18 when not.
    """
    nv = len(verts)
    prims: List[TroPrim] = []
    for slot, (_code, _chunk_stride, corners, textured, gouraud) in _SLOTS.items():
        stride = _LOD_STRIDES[slot]
        ptr = _resolve(struct.unpack_from("<I", data, sd + 4 + slot * 4)[0], start_pos)
        count = struct.unpack_from("<h", data, sd + 0x30 + slot * 2)[0]
        if count <= 0 or ptr <= 0 or ptr + count * stride > len(data):
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
                uvs = [_texel_uv(uu, vv) for uu, vv in pairs]
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


def lod_shape_scale(data: bytes, sd: int) -> float:
    """World units per raw vertex unit for one LOD shape.

    Props do NOT share a single fixed point -- each shape carries its own
    power-of-two exponent as an s16 at ShapeData+0x54 (retail range 16..26).
    The LOD setup at 0x8001f998 reads it and hands it to 0x8007b800, which
    forms `4096 << (exp - 12)` as the matrix scale, so the vertex scale is
    2^exp against a fixed base -- empirically 2^(exp - 28).

    Two independent checks agree on the base: it reproduces the corrections
    measured by hand on real props (exp 21 wants 2x a flat 1/256, exp 22 wants
    4x), and it puts the median prop at 20 world units tall beside a 15-unit
    road, with the only 150+ outliers being the low-poly distant backdrops on
    Autumn Ring and Tahiti.
    """
    if not (0 < sd < len(data) - 0x56):
        return 2.0 ** -8
    exp = struct.unpack_from("<h", data, sd + 0x54)[0]
    if not (0 < exp < 40):
        return 2.0 ** -8
    return 2.0 ** (exp - 28)


def parse_lod_shape(data: bytes, sd: int, start_pos: int):
    """(verts, prims, scale, sprites) for one LOD ShapeData, or None.

    A shape with no vertices is NOT empty: 65 retail LOD shapes carry
    vertexCount == 0 and a non-empty billboard list, because that is how GT2
    swaps a distant object for a single sprite."""
    if not (0 < sd < len(data) - 0x40):
        return None
    vptr = _resolve(struct.unpack_from("<I", data, sd)[0], start_pos)
    vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
    if not (0 <= vcount <= 100000):
        return None
    verts = _read_s16_verts(data, vptr, vcount) if vcount > 0 else []
    if not verts and not parse_lod_sprites(data, sd, start_pos):
        return None
    return (verts, _decode_lod_shapedata(data, sd, start_pos, verts),
            lod_shape_scale(data, sd), parse_lod_sprites(data, sd, start_pos))




# --- Billboard sprites (trees, bushes, distant stand-ins) -------------------
# A THIRD stream. It hides in plain sight: ShapeData's `listPtrs` array does not stop at eight. 
# Slots 8 and 9 sit at +0x24 and +0x28 with their counts at +0x40 and +0x42, exactly
# continuing the +0x04+4j / +0x30+2j pattern
#
# Slot 8 is billboards. Both renderers build the same thing -- a vertical quad
# that yaws to face the camera:
#
#     lhu  $v1, 0x40($s3)     ; count            (0x8001f9e8, props)
#     lw   $t4, 0x24($s3)     ; list
#     ...
#     ctc2 cos_cam, L11L12    ; L = [[c,0,0], [-s,0,0], [0,0,0]]
#     ctc2 -sin_cam, L13L21
#     mtc2 half_width, IR1
#     MVMVA (mx=L, v=IR, cv=none, sf=1)
#     -> IR1 = c*hw >> 12, IR2 = -s*hw >> 12
#
# so the quad spans `centre +- hw * (cos, sin)` horizontally on the camera yaw
# and rises `height` from its base. It is emitted as a 9-word GP0 packet
# (`lui $v0, 0x900`) and every retail record's command byte is 0x2C -- POLY_FT4,
# an opaque textured quad. There is no NCLIP test in either loop, so sprites are
# never back-face culled.
#
# The two streams differ in stride and in where the texture comes from, the same
# split as their solid geometry:
#
#   * chunks: stride 0x10 (`sll $v0, $v0, 4` at 0x80020444), UVs via the SHARED
#     descriptor table -- `srl $v0, $t1, 0x10; sll $v0, $v0, 5` takes the id from
#     the high half of +0x04 and multiplies by 32 into the pointer cached at
#     scratchpad 0x3a0, which is TrackChunkTable+0x08.
#   * props: stride 0x1C (`sll,subu,sll` = count*28 at 0x8001f9f8), UVs INLINE in
#     the same 12-byte clut/tpage block a prop's solid primitives carry.
#
# Retail totals: 10,927 chunk billboards over 4,327 chunks and 6,027 prop
# billboards over 1,079 LOD shapes -- 16,954 in all, none of them out of bounds.
# 65 LOD shapes have vertexCount == 0 but a non-empty slot 8: those are the
# distant levels where GT2 throws the mesh away and keeps a billboard.
#
# Slot 9 (+0x28, count +0x42, stride 0x14) is NOT track art and is not imported:
# its loop halves and quarters the colour into 0x3E-command packets with
# hard-coded UVs and 45-degree sine-table offsets, i.e. runtime lamp glare. It
# only appears on the night courses (highway 250, Rhighway 246, zero on roma,
# autumn, tahiti_t and every other daylight track), which is the giveaway.
_SPRITE_CHUNK_STRIDE = 0x10
_SPRITE_LOD_STRIDE = 0x1C


@dataclass
class TroSprite:
    """One camera-facing billboard, in its owning stream's local space."""
    pos: Tuple[int, int, int]      # base centre, same axis order as that stream
    width: int                     # FULL horizontal extent -- see _billboard_corners
    height: int                    # rises this far from the base, local units
    color: Tuple[float, float, float]
    uvs: List[Tuple[float, float]]   # v0..v3 = TL, TR, BL, BR
    tpage: int
    clut: int


def _sprite_uv_order(uvs):
    """PS1 quad corners are stored TL, TR, BL, BR (the 'Z' order).

    Read off the packet writes: RTPT projects the three corners into SXY0..2 and
    the stores put SXY1 in word 1, SXY0 in word 3, then after the RTPS SXY1 in
    word 5 and SXY2 in word 7 -- pairing the record's uv0 with the -half_width
    top corner, uv1 with +half_width top, uv2 with -half_width base and uv3 with
    +half_width base. As a polygon loop that is TL, TR, BR, BL.
    """
    return [uvs[0], uvs[1], uvs[3], uvs[2]]


def parse_chunk_sprites(data: bytes, sd: int, start_pos: int,
                        tex_table: int) -> List[TroSprite]:
    """Slot 8 of a chunk ShapeData: 16-byte records, shared descriptor UVs.

        +0x00  s16 x ; s16 y            pool components 0 and 1
        +0x04  s16 z ; u16 texture_id   component 2 is the chunk pool's height
        +0x08  u16 width ; u16 height
        +0x0C  u8 r, g, b ; u8 gp0_command
    """
    out: List[TroSprite] = []
    if not (0 < sd < len(data) - 0x44):
        return out
    count = struct.unpack_from("<H", data, sd + 0x40)[0]
    ptr = _resolve(struct.unpack_from("<I", data, sd + 0x24)[0], start_pos)
    if count <= 0 or ptr <= 0 or ptr + count * _SPRITE_CHUNK_STRIDE > len(data):
        return out
    for i in range(count):
        o = ptr + i * _SPRITE_CHUNK_STRIDE
        x, y = struct.unpack_from("<2h", data, o)
        z, tex_id = struct.unpack_from("<hH", data, o + 4)
        width, height = struct.unpack_from("<2H", data, o + 8)
        if width <= 0 or height <= 0:
            continue
        got = _read_tex_descriptor(data, tex_table, tex_id, 4)
        if got is None:
            continue
        uvs, tpage, clut = got
        col = (data[o + 12] / 255.0, data[o + 13] / 255.0, data[o + 14] / 255.0)
        out.append(TroSprite((x, y, z), width, height, col, uvs, tpage, clut))
    return out


def parse_lod_sprites(data: bytes, sd: int, start_pos: int) -> List[TroSprite]:
    """Slot 8 of a LOD ShapeData: 28-byte records with the UVs inline.

        +0x00  s16 x ; s16 y            y is the height, as for LOD vertices
        +0x04  s16 z ; u16 flags         mirroring the chunk record's z/tex_id
        +0x08  u16 width ; u16 height
        +0x0C  u8 r, g, b ; u8 gp0_command
        +0x10  u8 u0, v0 ; u16 clut     the same 12-byte block a prop primitive
        +0x14  u8 u1, v1 ; u16 tpage    carries, in the same order
        +0x18  u8 u2, v2, u3, v3
    """
    out: List[TroSprite] = []
    if not (0 < sd < len(data) - 0x44):
        return out
    count = struct.unpack_from("<H", data, sd + 0x40)[0]
    ptr = _resolve(struct.unpack_from("<I", data, sd + 0x24)[0], start_pos)
    if count <= 0 or ptr <= 0 or ptr + count * _SPRITE_LOD_STRIDE > len(data):
        return out
    for i in range(count):
        o = ptr + i * _SPRITE_LOD_STRIDE
        x, y = struct.unpack_from("<2h", data, o)
        # +0x04 is a 16-bit z, NOT a 32-bit one. The loop does `lw $a3, -8($t2)`
        # and pushes the result through `mtc2 ... VZ0/VZ1`, and VZ0 is an S16
        # register -- the high half never reaches the GTE. It is not padding
        # either: 253 of the 6,027 retail records (4.2%) carry exactly 1 up
        # there, so it is a flag. Reading the pair as a signed 32-bit int adds
        # 65536 to those sprites' z and flings them thousands of units off the
        # track (roma_night's gt2_prop_0028_lod047 spanned Y[-1940, 190] beside
        # a course only 673 units deep).
        z, _flags = struct.unpack_from("<hH", data, o + 4)
        width, height = struct.unpack_from("<2H", data, o + 8)
        if width <= 0 or height <= 0:
            continue
        col = (data[o + 12] / 255.0, data[o + 13] / 255.0, data[o + 14] / 255.0)
        u = o + 0x10
        clut = struct.unpack_from("<H", data, u + 2)[0]
        tpage = struct.unpack_from("<H", data, u + 6)[0]
        pairs = [(data[u], data[u + 1]), (data[u + 4], data[u + 5]),
                 (data[u + 8], data[u + 9]), (data[u + 10], data[u + 11])]
        uvs = [_texel_uv(uu, vv) for uu, vv in pairs]
        out.append(TroSprite((x, y, z), width, height, col, uvs, tpage, clut))
    return out



# --- Lamp glare: ShapeData slot 9 -------------------------------------------
# The glowing orbs on night-track lamp posts. Slot 9 is the pair to the slot 8
# billboards -- pointer at ShapeData+0x28, count at +0x42 -- and it is the one
# stream GT2 does not author as art: the loop at 0x800205ec (chunks) and
# 0x8001fba8 (props) builds the whole flare procedurally around a single stored
# point.
#
# Record, 20 bytes, the same shape as the slot 8 billboard's first half:
#
#     +0x00  s16 x ; s16 y        pool components 0 and 1
#     +0x04  s16 z ; s16 size     component 2 is height; size is the depth-cue
#                                 coefficient, below
#     +0x08  s16 nx, ny, nz       a unit vector, 4096 = 1.0 (|v| is 4096 on
#     +0x0E  s16 pad              every retail record that has one)
#     +0x10  u8 r, g, b ; u8 0    the lamp's colour; the command byte is OR'd
#                                 in at runtime, so this byte is always zero
#
# What the game draws from it: `mtc2` the point, RTPS, then take MAC0 -- the
# depth-cue term, whose slope is `ctc2 [+0x06], DQA` -- as the on-screen radius,
# so **`size` is a perspective coefficient rather than a world radius**. Four
# 12-word `0x3E` (POLY_GT4, semi-transparent) packets are then emitted at 45
# degree steps off the sine table at 0x80092ef8+0x200/0xa00, giving an eight
# point star, each gouraud-shaded from the stored colour through
# `c/2 -> c/8 -> c/64` (the `and 0xfefefe; srl 1` / `0xfcfcfc; srl 2` /
# `0xf8f8f8; srl 3` chain at 0x8001fcb0). The texture it samples is fixed in
# code -- tpage 0x29, CLUT 0x7f57 -- and is in no file in the volume: nothing
# uploads a TIM to VRAM page 9, so the engine builds it at runtime.
#
# Which is why this is imported as a generated orb rather than a texture lookup:
# there is no sprite to extract, only a position, a colour and a falloff, and
# all three are recoverable. Retail totals: 2,195 chunk records and 358 on LOD
# shapes, over **17 courses, every one of them a night or evening layout** --
# roma_night 328, highway 250, shortway 162 -- which is the check that this is
# the lamp glare and not something else.
_GLARE_STRIDE = 0x14


@dataclass
class TroGlare:
    """One lamp flare: where it is, how big, and what colour."""
    pos: Tuple[int, int, int]
    size: int                       # depth-cue coefficient, 38..299 retail
    direction: Tuple[int, int, int]  # unit * 4096
    color: Tuple[float, float, float]


def parse_glares(data: bytes, sd: int, start_pos: int) -> List[TroGlare]:
    """Slot 9 of a ShapeData. Identical on the chunk and prop streams."""
    out: List[TroGlare] = []
    if not (0 < sd < len(data) - 0x44):
        return out
    count = struct.unpack_from("<H", data, sd + 0x42)[0]
    ptr = _resolve(struct.unpack_from("<I", data, sd + 0x28)[0], start_pos)
    if count <= 0 or ptr <= 0 or ptr + count * _GLARE_STRIDE > len(data):
        return out
    for i in range(count):
        o = ptr + i * _GLARE_STRIDE
        x, y = struct.unpack_from("<2h", data, o)
        z, size = struct.unpack_from("<2h", data, o + 4)
        nx, ny, nz = struct.unpack_from("<3h", data, o + 8)
        col = (data[o + 0x10] / 255.0, data[o + 0x11] / 255.0,
               data[o + 0x12] / 255.0)
        if size <= 0:
            continue
        out.append(TroGlare((x, y, z), size, (nx, ny, nz), col))
    return out


def _make_glare_material_factory():
    """colour -> an emissive orb material, one per distinct lamp colour.

    The alpha is a radial falloff built from the quad's own UVs, because the
    game's glare texture does not exist in any file -- it is generated at
    runtime. The exponent approximates GT2's own ramp, which steps the stored
    colour `c/2 -> c/8 -> c/64` from the centre outwards.
    """
    import bpy  # noqa
    cache = {}

    def build(colour):
        key = tuple(round(c, 3) for c in colour)
        if key in cache:
            return cache[key]
        mat = bpy.data.materials.new(
            f"GT2_glare_{int(key[0]*255):02x}{int(key[1]*255):02x}{int(key[2]*255):02x}")
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
        mix = nt.nodes.new("ShaderNodeMixShader");      mix.location = (200, 0)
        tr = nt.nodes.new("ShaderNodeBsdfTransparent"); tr.location = (0, 120)
        em = nt.nodes.new("ShaderNodeEmission");        em.location = (0, -80)
        em.inputs["Color"].default_value = (colour[0], colour[1], colour[2], 1.0)
        em.inputs["Strength"].default_value = 6.0
        uv = nt.nodes.new("ShaderNodeUVMap");   uv.location = (-800, -200)
        uv.uv_map = "GT2_UV"
        sub = nt.nodes.new("ShaderNodeVectorMath"); sub.location = (-620, -200)
        sub.operation = "SUBTRACT"
        sub.inputs[1].default_value = (0.5, 0.5, 0.0)
        ln = nt.nodes.new("ShaderNodeVectorMath"); ln.location = (-440, -200)
        ln.operation = "LENGTH"
        rng = nt.nodes.new("ShaderNodeMath"); rng.location = (-260, -200)
        rng.operation = "MULTIPLY"; rng.inputs[1].default_value = 2.0
        inv = nt.nodes.new("ShaderNodeMath"); inv.location = (-100, -200)
        inv.operation = "SUBTRACT"; inv.use_clamp = True
        inv.inputs[0].default_value = 1.0
        pw = nt.nodes.new("ShaderNodeMath"); pw.location = (60, -200)
        pw.operation = "POWER"; pw.inputs[1].default_value = 2.5
        nt.links.new(uv.outputs["UV"], sub.inputs[0])
        nt.links.new(sub.outputs["Vector"], ln.inputs[0])
        nt.links.new(ln.outputs["Value"], rng.inputs[0])
        nt.links.new(rng.outputs["Value"], inv.inputs[1])
        nt.links.new(inv.outputs["Value"], pw.inputs[0])
        nt.links.new(pw.outputs["Value"], mix.inputs["Fac"])
        nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
        nt.links.new(em.outputs["Emission"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        for attr, val in (("blend_method", "BLEND"),
                          ("surface_render_method", "BLENDED"),
                          ("show_transparent_back", False)):
            try:
                setattr(mat, attr, val)
            except Exception:
                pass
        mat["gt2_glare_colour"] = key
        cache[key] = mat
        return mat

    return build, cache


def _billboard_corners(sprite: TroSprite, horiz, vert_axis, toward):
    """Four local-space corners for one billboard, TL, TR, BL, BR.

    `horiz` are the two local axis indices the quad spreads across and
    `vert_axis` the one it rises along; `toward` is a local-space point the
    billboard should face (its own chunk's centroid, or the shape origin).

    GT2 yaws every billboard to the camera each frame, so no single static
    orientation is right. Facing the road is the closest a baked mesh gets: it
    is what the player sees for the whole time the sprite is in front of them.
    """
    cx = sprite.pos[horiz[0]]
    cy = sprite.pos[horiz[1]]
    base = sprite.pos[vert_axis]
    fx, fy = toward[0] - cx, toward[1] - cy
    mag = (fx * fx + fy * fy) ** 0.5
    if mag < 1e-6:
        dx, dy = 1.0, 0.0            # degenerate: spread along the first axis
    else:
        dx, dy = -fy / mag, fx / mag  # perpendicular to the facing direction
    # +0x08's low half is a FULL width, not a half-extent, and the halving is
    # hidden in the table it multiplies against: 0x80020228 stores the yaw
    # sine as `sll 16; sra 17` -- sign-extend, then shift right ONE more -- so
    # scratchpad 0x3f0/0x3f2 hold sin/2 and cos/2, and the MVMVA that turns the
    # width into the screen-space offset comes back with width/2. Reading it as
    # a half-extent draws every billboard at twice its size: over the 10,927
    # chunk billboards the quad's aspect then runs a median 1.71x its own
    # texture's aspect, against 0.85x this way.
    hw = sprite.width * 0.5
    lx, ly = cx - hw * dx, cy - hw * dy
    rx, ry = cx + hw * dx, cy + hw * dy
    top = base + sprite.height
    def pt(a, b, v):
        p = [0, 0, 0]
        p[horiz[0]] = a
        p[horiz[1]] = b
        p[vert_axis] = v
        return tuple(p)
    return [pt(lx, ly, top), pt(rx, ry, top), pt(lx, ly, base), pt(rx, ry, base)]


def parse_tro(data: bytes) -> Optional[Tro]:
    if data[:len(TRO_MAGIC)] != TRO_MAGIC:
        return None
    version = struct.unpack_from("<i", data, 0x0C)[0]
    track_chunks_ptr = struct.unpack_from("<I", data, 0x10)[0]
    ioo0 = struct.unpack_from("<I", data, 0x118)[0]
    start_pos = ioo0 - 0x19C

    tct = _resolve(track_chunks_ptr, start_pos)
    num_chunks = struct.unpack_from("<h", data, tct + 4)[0]
    # TrackChunkTable+0x08 is the texture-descriptor table the renderer loads
    # into its UV lookup (overlay0: lw v0, 8(s3) -> sw v0, 0x3a0(scratch)).
    tex_table = _resolve(struct.unpack_from("<I", data, tct + 8)[0], start_pos)
    if not (0 < tex_table < len(data)):
        tex_table = 0
    chunk_ptrs = struct.unpack_from(f"<{num_chunks}I", data, tct + 0x0C)

    chunks: List[TroChunk] = []
    for i, cp in enumerate(chunk_ptrs):
        c = _resolve(cp, start_pos)
        if c < 0 or c + 0xA4 + 0x44 > len(data):
            continue
        prev_i, next_i = struct.unpack_from("<2H", data, c)
        world_raw = struct.unpack_from("<3i", data, c + 0x18)
        center_raw = struct.unpack_from("<3i", data, c + 0x30)
        chunk = TroChunk(i, c, prev_i, next_i, world_raw, center_raw)

        sd = c + 0xA4
        vptr = _resolve(struct.unpack_from("<I", data, sd)[0], start_pos)
        vcount = struct.unpack_from("<i", data, sd + 0x2C)[0]
        chunk.verts = _read_s16_verts(data, vptr, vcount) if 0 < vcount <= 100000 else []
        if chunk.verts:
            chunk.prims = _decode_shapedata(data, sd, start_pos, tex_table,
                                            chunk.verts)
        chunks.append(chunk)

    return Tro(version, start_pos, tex_table, chunks)



# --- Skyboxes: `bgsobj/*.bso` + `.bsp` --------------------------------------
# A course's sky is NOT in its `.tro`. It lives in a separate `bgsobj` directory
# as a `<name>.bso` / `<name>.bsp` pair -- the same split as `crsobj`'s
# `.tro`/`.trp`, and the `.bsp` is byte-for-byte the same container as a `.trp`
# (u32 count then TIM-family images), so `load_trp_vram` reads it unchanged.
#
# Which sky a course uses is in `.crsinfo` at the volume root, keyed by the
# course's own name hash -- see `track_sky_map()`.
#
# The `.bso` is the `.tro`'s ShapeData with a different hat on:
#
#     +0x00  char magic[4] "BG\0\0"
#     +0x04  u8 r, g, b ; u8 0x28      background colour A
#     +0x08  u8 r, g, b ; u8 0x28      background colour B
#     +0x0C  u32 vertexCount
#     +0x10  u16 listCounts[8]         F3 F4 G3 G4 FT3 FT4 GT3 GT4, the same
#                                      slot order the track chunks use
#     +0x20  vertexCount x 8 bytes     s16 x, y, z, pad -- the .tro's vertex format
#     then   the eight primitive lists, in slot order
#
# Two things differ from the roadway, and both come straight from the PS1:
#
#   * a primitive record is `8 bytes of indices` followed by **TWO copies** of
#     `[u32 OT tag][the GPU packet]`, because the console needs one packet per
#     double-buffered frame. Hence the strides below: 8 + 2*(4 + words*4).
#     Every record's OT tag length matches its own GP0 command byte across all
#     34 retail skies, which is what pins the strides.
#   * indices are **four 12-bit fields** at bits 0-11 and 12-23 of each of the
#     two words -- wider than the roadway's 9 and the props' 10, and they need
#     to be: `t_sky` alone has 640 vertices. Verified on 5,292 primitives over
#     all 34 skies: every index lands inside its own file's vertexCount, and
#     all 34 files parse to exact EOF.
#
# The screen coordinates in the stored packets are zero -- the game fills them
# in each frame -- but the colours, UVs, CLUT and TPAGE are authored, so a
# skybox reads out fully textured.
BSO_MAGIC = b"BG\x00\x00"

# words in the GPU packet, per slot: F3 F4 G3 G4 FT3 FT4 GT3 GT4
_BSO_WORDS = {0: 4, 1: 5, 2: 6, 3: 8, 4: 7, 5: 9, 6: 8, 7: 12}
_BSO_STRIDES = {k: 8 + 2 * (4 + w * 4) for k, w in _BSO_WORDS.items()}
_BSO_LOCAL_SCALE = 1.0 / 64.0    # same fixed point as the roadway pool


@dataclass
class Bso:
    """One decoded skybox."""
    colour_a: Tuple[float, float, float]
    colour_b: Tuple[float, float, float]
    verts: List[Tuple[int, int, int]]
    prims: List[TroPrim]


def _bso_packet_colour(data: bytes, w: int) -> Tuple[float, float, float]:
    return (data[w] / 255.0, data[w + 1] / 255.0, data[w + 2] / 255.0)


def parse_bso(data: bytes) -> Optional[Bso]:
    """Decode a `.bso` skybox. `data` is already decompressed."""
    if len(data) < 0x20 or data[:4] != BSO_MAGIC:
        return None
    ca = _bso_packet_colour(data, 0x04)
    cb = _bso_packet_colour(data, 0x08)
    nv = struct.unpack_from("<I", data, 0x0C)[0]
    if not (0 < nv <= 4096):          # 12-bit indices cap the pool at 4096
        return None
    counts = struct.unpack_from("<8H", data, 0x10)
    verts = _read_s16_verts(data, 0x20, nv)
    if not verts:
        return None
    off = 0x20 + nv * 8
    prims: List[TroPrim] = []
    for slot in range(8):
        stride = _BSO_STRIDES[slot]
        count = counts[slot]
        if count and off + count * stride > len(data):
            break
        _code, _cs, corners, textured, gouraud = _SLOTS[slot]
        for i in range(count):
            o = off + i * stride
            a, b = struct.unpack_from("<2I", data, o)
            idx = [a & 0xFFF, (a >> 12) & 0xFFF,
                   b & 0xFFF, (b >> 12) & 0xFFF][:corners]
            if any(k >= nv for k in idx) or len(set(idx)) != len(idx):
                continue
            # the packet starts after the 8 index bytes and the 4-byte OT tag
            w = o + 12
            base = _bso_packet_colour(data, w)
            uvs = None
            tpage = clut = 0
            if textured:
                # POLY_FT/GT word order: colour+cmd, xy0, uv0|clut, [colour1,]
                # xy1, uv1|tpage, ... -- the stride between corners is 8 bytes
                # for flat-textured and 12 for gouraud-textured.
                step = 12 if gouraud else 8
                u0 = w + 8
                clut = struct.unpack_from("<H", data, u0 + 2)[0]
                tpage = struct.unpack_from("<H", data, u0 + step + 2)[0]
                pairs = [(data[u0 + step * c], data[u0 + step * c + 1])
                         for c in range(corners)]
                uvs = [_texel_uv(uu, vv) for uu, vv in pairs]
            if gouraud:
                step = 12 if textured else 8
                cols = [_bso_packet_colour(data, w + step * c)
                        for c in range(corners)]
            else:
                cols = [base] * corners
            prims.append(TroPrim(slot, tuple(idx), cols, uvs, tpage, clut))
        off += count * stride
    return Bso(ca, cb, verts, prims)


def bsp_path_for(bso_path: str) -> Optional[str]:
    """The `.bsp` texture sidecar beside a `.bso`, plain or gzipped."""
    import os
    base = bso_path
    if base.lower().endswith(".gz"):
        base = base[:-3]
    if base.lower().endswith(".bso"):
        base = base[:-4]
    for cand in (base + ".bsp", base + ".bsp.gz"):
        if os.path.exists(cand):
            return cand
    return None


def gt2_track_id(name: str) -> int:
    """GT2's own name hash, used as the course id in `.crsinfo`.

    Rotate the accumulator left by 6 and add each ASCII byte. Resolves all 126
    `crsobj` filenames against the retail `.crsinfo` with nothing left over.
    """
    t = 0
    for ch in name:
        t = ((t << 6) | (t >> 26)) & 0xFFFFFFFF
        t = (t + ord(ch)) & 0xFFFFFFFF
    return t


# `.crsinfo` stores a skybox INDEX, and no name table exists anywhere in the
# executable or the overlays -- `/bgsobj` appears only as a directory path. The
# index is a position in the VOL's own directory listing for that folder, and
# that listing is **ASCII-sorted**: `_` is 0x5F, below every lowercase letter, so
# `roma_sh` sorts before `romadark_sky`, `sea_ha_b` before `sea_hare`, and
# `t_sky` before `tesr_l2sky`. Verified against the directory block of both the
# retail `GT2.VOL` (at 0xB1A7) and the Euro Demo 53 build's.
#
# So the table is NOT a constant -- `sky_names_for()` builds it by listing the
# `bgsobj` directory that is actually present, because different builds ship
# different sets: retail has 34 skies, the demo 25. Using retail's list on the
# demo mismatches almost every course (its `highway` wants index 2, which is
# `dawn` there and `circle30sky` in retail).
#
# The list below is retail's, kept only as a fallback for a `bgsobj` that cannot
# be listed. It is also worth recording because the widely-circulated community
# list is these same 34 names sorted the way Windows Explorer sorts them, which
# ignores the underscore: the two agree for indices 0..15 and diverge from 16 on,
# so most courses look right and only some are wrong -- Tahiti Road picks up
# `tesr_l2sky`'s green mountains instead of `t_sky`'s beach and blue horizon.
GT2_SKY_NAMES = [
    "au", "cartsky", "circle30sky", "circle80sky", "cloudtest", "dawn",
    "grinsky", "gv_sky", "indisky", "lagunasky", "licen_sky", "mskyX",
    "mskyX_2", "new_parmas_sky", "noon", "parma_sky", "roma_sh", "roma_sh_sky",
    "roma_sky", "romadark_sky", "romadsky", "sea_ha_b", "sea_ha_c", "sea_ha_d",
    "sea_ha_e", "sea_hare", "speedsky", "t_sky", "tesr_l2sky", "tl_sky2",
    "tl_sky2g", "tl_sky4", "tl_skyG", "tl_skyG2",
]


def sky_names_for(bgsobj_dir: str) -> List[str]:
    """The skybox name table for one game build, in `.crsinfo` index order.

    The index is a position in the VOL directory listing, which is ASCII-sorted,
    so listing the extracted `bgsobj` and sorting reproduces it exactly -- checked
    against the directory blocks of both the retail and Euro Demo 53 `GT2.VOL`.
    Doing it this way rather than from a constant is what makes the demo work:
    it ships 25 skies where retail ships 34, and every index above 0 differs.
    """
    import os
    try:
        names = {f.split(".bso")[0] for f in os.listdir(bgsobj_dir)
                 if ".bso" in f}
    except OSError:
        return list(GT2_SKY_NAMES)
    return sorted(names) if names else list(GT2_SKY_NAMES)


def parse_crsinfo(data: bytes, sky_names: Optional[List[str]] = None) -> dict:
    """`.crsinfo` -> {course name hash: {...}}.

    `char magic[4] "CRS\\0"; u16 version(2); u16 courseCount;` then one 24-byte
    record per course:

        +0x00  u32 displayNameOffset   (into the string table that follows)
        +0x04  u32 courseId            (gt2_track_id of the crsobj filename)
        +0x08  u8  flags               bit0 night, 1 evening, 2 dirt,
                                       3 two-player, 4 reverse, 5 point-to-point
        +0x09  u8  pad
        +0x0A  u16 skybox              index into the build's own sky list
        +0x0C  3 x { u16 colour; u16 multiplier }   lighting areas
    """
    if len(data) < 8 or data[:4] != b"CRS\x00":
        return {}
    names_tbl = sky_names if sky_names is not None else GT2_SKY_NAMES
    count = struct.unpack_from("<H", data, 6)[0]
    names = {}
    p = 8 + count * 24
    while p < len(data):
        s = p
        while p < len(data) and data[p] != 0:
            p += 1
        if p > s:
            names[s] = data[s:p].decode("ascii", "replace")
        p += 1
    out = {}
    for i in range(count):
        o = 8 + i * 24
        name_off, course_id = struct.unpack_from("<2I", data, o)
        flags = data[o + 8]
        sky = struct.unpack_from("<H", data, o + 0x0A)[0]
        out[course_id] = {
            "display_name": names.get(name_off, ""),
            "flags": flags,
            "night": bool(flags & 1),
            "evening": bool(flags & 2),
            "dirt": bool(flags & 4),
            "sky_index": sky,
            "sky": names_tbl[sky] if sky < len(names_tbl) else None,
            "lighting": struct.unpack_from("<6H", data, o + 0x0C),
        }
    return out


def find_sky_for_tro(tro_path: str):
    """(bso path, course record) for a `.tro`, or (None, None).

    Looks for the volume layout the game ships: the `.tro` in `crsobj/`, the
    skies in a sibling `bgsobj/`, and `.crsinfo` at the volume root. Anything
    missing just means no sky, which is the normal case when only `crsobj` has
    been extracted.
    """
    import os
    base = os.path.basename(tro_path)
    for suffix in (".tro.gz", ".tro"):
        if base.lower().endswith(suffix):
            course = base[:-len(suffix)]
            break
    else:
        return (None, None)
    crsobj = os.path.dirname(os.path.abspath(tro_path))
    for root in (os.path.dirname(crsobj), crsobj,
                 os.path.dirname(os.path.dirname(crsobj))):
        info = os.path.join(root, ".crsinfo")
        bgs = os.path.join(root, "bgsobj")
        if not (os.path.exists(info) and os.path.isdir(bgs)):
            continue
        try:
            table = parse_crsinfo(open(info, "rb").read(), sky_names_for(bgs))
        except OSError:
            continue
        rec = table.get(gt2_track_id(course))
        if rec is None or not rec["sky"]:
            continue
        for cand in (os.path.join(bgs, rec["sky"] + ".bso"),
                     os.path.join(bgs, rec["sky"] + ".bso.gz")):
            if os.path.exists(cand):
                return (cand, rec)
    return (None, None)


def _make_material_factory(vram, report):
    """(tpage, clut) -> Blender material, built once and shared between chunks.

    PS1 modulates a texel by the primitive colour as `texel * prim / 128`, so
    0x80 is neutral and the stored bytes can brighten as well as darken. The
    colour attribute holds prim/255, hence the x2 before the multiply.
    """
    import bpy  # noqa
    cache = {}

    def build(key):
        if key in cache:
            return cache[key]
        tpage, clut = key if key is not None else (None, None)
        name = "GT2_untextured" if key is None else f"GT2_{tpage:02x}_{clut:04x}"
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            try:
                bsdf.inputs["Roughness"].default_value = 1.0
            except Exception:
                pass
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "GT2_Color"
        vc.location = (-760, -120)
        boost = nt.nodes.new("ShaderNodeMixRGB")
        boost.blend_type = "MULTIPLY"
        boost.label = "PS1Modulate"
        boost.inputs["Fac"].default_value = 1.0
        boost.inputs["Color2"].default_value = (2.0, 2.0, 2.0, 1.0)
        boost.location = (-560, -120)
        nt.links.new(vc.outputs["Color"], boost.inputs["Color1"])
        src = boost.outputs["Color"]
        img = None
        if key is not None and vram is not None:
            px = page_rgba(vram, tpage, clut)
            if px is not None:
                import numpy as np
                img = bpy.data.images.new(name, 256, 256, alpha=True)
                flat = (px[::-1].astype("float32") / 255.0).reshape(-1)
                img.pixels.foreach_set(flat)
                img.pack()
                tex = nt.nodes.new("ShaderNodeTexImage")
                tex.image = img
                tex.interpolation = "Closest"      # PS1 point sampling
                tex.extension = "REPEAT"
                tex.location = (-760, 200)
                mix = nt.nodes.new("ShaderNodeMixRGB")
                mix.blend_type = "MULTIPLY"
                mix.inputs["Fac"].default_value = 1.0
                mix.location = (-320, 60)
                nt.links.new(tex.outputs["Color"], mix.inputs["Color1"])
                nt.links.new(boost.outputs["Color"], mix.inputs["Color2"])
                src = mix.outputs["Color"]
                if bsdf is not None:
                    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
                for attr, val in (("blend_method", "CLIP"),
                                  ("surface_render_method", "DITHERED")):
                    try:
                        setattr(mat, attr, val)
                    except Exception:
                        pass
        if bsdf is not None:
            nt.links.new(src, bsdf.inputs["Base Color"])
        mat["gt2_tpage"] = -1 if key is None else tpage
        mat["gt2_clut"] = -1 if key is None else clut
        cache[key] = mat
        return mat

    return build, cache


def usable_prims(prims: List[TroPrim]) -> List[TroPrim]:
    """Drop the primitives Blender's mesh.validate() would delete.

    This matters far more than it looks. UVs, corner colours and material
    indices are assigned to `mesh.polygons[i]` positionally, so if validate
    removes ONE face, every face after it in that chunk inherits the previous
    face's texture and UVs. Across the retail set validate was deleting faces in
    18 of highway's 194 chunks and 40 of roma's 179 -- which is exactly the
    "UV mapping is wrong" and "textures assigned to the wrong face" symptom.

    Of 699,229 chunk primitives, validate removes two kinds:
      * 150 with a vertex repeated inside the face -- genuinely invalid, dropped
        here (the old `len(set(idx)) < 3` test let quads like (a,b,c,a) through).
      * 4,704 that exactly duplicate an earlier face. 4,006 of those also repeat
        its texture and are pure redundancy, so they are dropped; the remaining
        698 carry a DIFFERENT texture on the same four corners -- they are the
        decals GT2 layers onto the road, and they are kept. Letting validate eat
        them removed real detail and left the face underneath showing instead.
    """
    out: List[TroPrim] = []
    seen: dict = {}
    for pr in prims:
        idx = pr.indices
        if len(set(idx)) != len(idx):
            continue
        key = frozenset(idx)
        tex = (pr.tpage, pr.clut, pr.uvs is not None)
        if key in seen and tex in seen[key]:
            continue
        seen.setdefault(key, set()).add(tex)
        out.append(pr)
    return out



_GLARE_SIZE_SCALE = _CHUNK_LOCAL_SCALE * 0.5


def _glare_quads(glares, to_world, out_verts, out_faces, out_uvs, out_mats,
                 make_glare):
    """Append one screen-facing quad per lamp flare.

    `size` is a depth-cue coefficient, not a world radius -- GT2's flare is a
    screen-space effect -- so a world size has to be chosen. Reading it in the
    pool's own 1/64 units and halving puts the retail spread (38..299, median
    213) at 0.3 to 2.3 world units of radius beside a 15-unit road, and keeps
    the relative sizes the file actually stores.
    """
    for gl in glares:
        r = gl.size * _GLARE_SIZE_SCALE
        cx, cy, cz = to_world(gl.pos)
        first = len(out_verts)
        # a flare is radially symmetric, so the quad's own orientation carries
        # no information; it is built in the view-neutral XZ plane and meant to
        # be pointed at the camera.
        out_verts.extend([(cx - r, cy, cz + r), (cx + r, cy, cz + r),
                          (cx + r, cy, cz - r), (cx - r, cy, cz - r)])
        out_faces.append((first, first + 1, first + 2, first + 3))
        out_uvs.append([(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)])
        out_mats.append(make_glare(gl.color))


def _build_glare_mesh(name, glares, to_world, make_glare):
    import bpy  # noqa
    verts, faces, uvs, mats = [], [], [], []
    _glare_quads(glares, to_world, verts, faces, uvs, mats, make_glare)
    if not faces:
        return None
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    if len(mesh.polygons) != len(faces):
        return None
    uvl = mesh.uv_layers.new(name="GT2_UV")
    for ti, quad in enumerate(uvs):
        poly = mesh.polygons[ti]
        for c in range(min(poly.loop_total, 4)):
            uvl.data[poly.loop_start + c].uv = quad[c]
    slot_of = {}
    for m in mats:
        if m.name not in slot_of:
            slot_of[m.name] = len(slot_of)
            mesh.materials.append(m)
    if len(slot_of) > 1:
        for i, poly in enumerate(mesh.polygons):
            poly.material_index = slot_of[mats[i].name]
    return mesh

# --- texture modes ----------------------------------------------------------
#
# The default is a VRAM PAGE per (tpage, clut): exactly what the console
# addresses, and what every UV in the file is relative to. It is also wasteful
# to look at -- `highway` references 136 pages, so the import carries 136
# 256x256 images even though the textures inside them are a few dozen texels
# across, and every material shows a whole page with the wanted texture
# somewhere in it.
#
# The other two modes both rest on the same observation. A texture's extent is
# not recorded anywhere; the file only says which texels each face samples. But
# a face's UV corners bound the texture it uses, and faces that share a texture
# produce boxes that overlap. Unioning overlapping boxes per (tpage, clut)
# therefore RECOVERS the textures: on `highway` 1,374 distinct per-face boxes
# collapse to 141 tiles, on `circuit` 1,739 to 158. That is the right order of
# magnitude for a PS1 course, and not one tile came out a full page.
#
# A palette is part of a texture's identity -- the same 4-bit indices drawn
# through a different CLUT are a different image -- so (tpage, clut) keys the
# grouping, never tpage alone.

def _uv_texel(uv):
    """A page-relative UV back to the integer texel `_texel_uv()` made it
    from. Exact: the encoder stores (u + 0.5) / 256."""
    u = int(round(uv[0] * 256.0 - 0.5))
    v = int(round((1.0 - uv[1]) * 256.0 - 0.5))
    return (0 if u < 0 else 255 if u > 255 else u,
            0 if v < 0 else 255 if v > 255 else v)


def _uv_box(uvs):
    pts = [_uv_texel(x) for x in uvs]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _merge_rects(rects):
    """Union overlapping texel rectangles until none overlaps another.

    Absorbing into an accumulator and re-testing is what makes this correct: two
    rects that do not touch can both touch a third, and a single pass would
    leave them separate.
    """
    out = []
    for r in rects:
        hit = True
        while hit:
            hit = False
            for i, o in enumerate(out):
                if not (r[2] < o[0] or o[2] < r[0] or r[3] < o[1] or o[3] < r[1]):
                    r = (min(r[0], o[0]), min(r[1], o[1]),
                         max(r[2], o[2]), max(r[3], o[3]))
                    out.pop(i)
                    hit = True
                    break
        out.append(r)
    return out


def _shelf_pack(sizes, cap=8192):
    """Pack (w, h) boxes tallest-first into shelves -> (width, height, [(x, y)]).

    Tiles come off a 256-texel page and cluster into a few heights, which is the
    case shelf packing handles well. Nothing here needs a better packer.
    """
    area = sum(w * h for w, h in sizes) or 1
    side = 256
    while side * side < area:
        side *= 2
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    while side <= cap:
        pos = [None] * len(sizes)
        x = y = shelf = 0
        ok = True
        for i in order:
            w, h = sizes[i]
            if w > side:
                ok = False
                break
            if x + w > side:
                x = 0
                y += shelf
                shelf = 0
            if y + h > side:
                ok = False
                break
            pos[i] = (x, y)
            x += w
            if h > shelf:
                shelf = h
        if ok:
            return side, y + shelf, pos
        side *= 2
    return None


class _Tile:
    """One recovered texture: where it sits in VRAM, and where it ends up."""
    __slots__ = ("key", "src", "dst", "size")

    def __init__(self, key, src, dst, size):
        self.key = key      # material key handed to TextureMapper.material()
        self.src = src      # (x0, y0) of the crop inside the 256x256 page
        self.dst = dst      # (x, y) of the crop inside the destination image
        self.size = size    # (width, height) of the destination image

    def uv(self, uv):
        u, v = _uv_texel(uv)
        w, h = self.size
        return ((u - self.src[0] + self.dst[0] + 0.5) / w,
                1.0 - (v - self.src[1] + self.dst[1] + 0.5) / h)


class TextureMapper:
    """Rewrites face texture keys and UVs for the chosen texture mode.

    PAGE is the identity: it hands every key straight to the shared GT2 material
    factory. INDIVIDUAL gives each recovered tile its own cropped image and its
    own material. ATLAS packs every tile into one image behind one material.

    Both non-default modes drop duplicates by CONTENT, so two CLUTs that hold
    the same colours, or one texture reached through two descriptors, become a
    single image rather than two.
    """

    def __init__(self, mode, vram, report, tag="GT"):
        self.report = report
        self.tag = tag
        self.vram = vram
        self.mode = mode if mode in ("INDIVIDUAL", "ATLAS") else "PAGE"
        if vram is None:
            self.mode = "PAGE"
        self._page_material, self._page_cache = _make_material_factory(
            vram, report)
        self._tiles = {}     # (tpage, clut) -> [(rect, _Tile), ...]
        self._mats = {}      # unique-texture ordinal -> material
        self._missed = 0

    # -- construction --------------------------------------------------------
    def build(self, refs):
        """Group the collected boxes into tiles and realise the images."""
        if self.mode == "PAGE" or not refs:
            return
        try:
            import numpy as np
        except Exception:
            self.mode = "PAGE"
            self.report("textures: numpy unavailable; falling back to VRAM pages")
            return
        boxes = {}
        for key, box in refs:
            boxes.setdefault(key, set()).add(box)

        pages, crops = {}, []
        for key in sorted(boxes):
            if key not in pages:
                pages[key] = page_rgba(self.vram, key[0], key[1])
            px = pages[key]
            if px is None:
                continue
            for rect in sorted(_merge_rects(boxes[key])):
                x0, y0, x1, y1 = rect
                crops.append((key, rect, px[y0:y1 + 1, x0:x1 + 1]))
        if not crops:
            self.mode = "PAGE"
            return

        # Content dedup: identical pixels are one texture, whatever addressed it.
        uniq, owner, unique = {}, [], []
        for _k, _r, arr in crops:
            h = arr.tobytes()
            n = uniq.get(h)
            if n is None:
                n = uniq[h] = len(unique)
                unique.append(arr)
            owner.append(n)

        self._n_pages = len(set(k for k, _r, _a in crops))
        self._n_crops = len(crops)
        if self.mode == "ATLAS":
            self._build_atlas(unique, crops, owner, np)
        else:
            self._build_individual(unique, crops, owner)

    def _register(self, crops, owner, dst, size):
        for i, (key, rect, _a) in enumerate(crops):
            n = owner[i]
            self._tiles.setdefault(key, []).append(
                (rect, _Tile(("gt_tile", n), (rect[0], rect[1]),
                             dst[n], size[n])))

    def _build_individual(self, unique, crops, owner):
        import bpy  # noqa
        for n, arr in enumerate(unique):
            h, w = arr.shape[0], arr.shape[1]
            name = f"{self.tag}_tex_{n:04d}"
            img = bpy.data.images.new(name, w, h, alpha=True)
            img.pixels.foreach_set(
                (arr[::-1].astype("float32") / 255.0).reshape(-1))
            img.pack()
            self._mats[n] = self._tex_material(name, img)
        self._register(crops, owner, [(0, 0)] * len(unique),
                       [(a.shape[1], a.shape[0]) for a in unique])
        self.report(f"textures: {len(unique)} individual images recovered from "
                    f"{self._n_pages} VRAM pages ({self._n_crops} tiles, "
                    f"{self._n_crops - len(unique)} duplicates dropped)")

    def _build_atlas(self, unique, crops, owner, np):
        import bpy  # noqa
        sizes = [(a.shape[1], a.shape[0]) for a in unique]
        # No gutter around the tiles. A rasterised pixel interpolates between
        # the face's corner UVs, so it stays inside the corner bounding box and
        # therefore inside the tile -- there is nothing to bleed. Measured: a
        # one-texel replicated border changes `seattle`'s worst render
        # difference not at all (23/255 either way) and raises the count of
        # sub-texel roundings, so it is pure cost.
        packed = _shelf_pack(sizes)
        if packed is None:
            self.mode = "PAGE"
            self.report("textures: atlas would exceed 8192 px; using VRAM pages")
            return
        aw, ah, pos = packed
        canvas = np.zeros((ah, aw, 4), dtype=np.uint8)
        for arr, (x, y) in zip(unique, pos):
            canvas[y:y + arr.shape[0], x:x + arr.shape[1]] = arr
        name = f"{self.tag}_atlas"
        img = bpy.data.images.new(name, aw, ah, alpha=True)
        img.pixels.foreach_set(
            (canvas[::-1].astype("float32") / 255.0).reshape(-1))
        img.pack()
        mat = self._tex_material(name, img)
        for n in range(len(unique)):
            self._mats[n] = mat
        self._register(crops, owner, pos, [(aw, ah)] * len(unique))
        fill = sum(w * h for w, h in sizes) / float(aw * ah)
        self.report(f"textures: {len(unique)} textures packed into one "
                    f"{aw}x{ah} atlas ({fill * 100:.0f}% full) from "
                    f"{self._n_pages} VRAM pages "
                    f"({self._n_crops - len(unique)} duplicates dropped)")

    def _tex_material(self, name, img):
        """The page factory's shader graph, pointed at a cropped image.

        Built by hand rather than reused because _make_material_factory()
        decodes its own page from a (tpage, clut) key. Everything else about the
        graph -- the GT2_Color attribute, the x2 PS1 modulate, point sampling,
        clipped alpha -- is deliberately identical, so all three modes shade the
        same.
        """
        import bpy  # noqa
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            try:
                bsdf.inputs["Roughness"].default_value = 1.0
            except Exception:
                pass
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "GT2_Color"
        vc.location = (-760, -120)
        boost = nt.nodes.new("ShaderNodeMixRGB")
        boost.blend_type = "MULTIPLY"
        boost.label = "PS1Modulate"
        boost.inputs["Fac"].default_value = 1.0
        boost.inputs["Color2"].default_value = (2.0, 2.0, 2.0, 1.0)
        boost.location = (-560, -120)
        nt.links.new(vc.outputs["Color"], boost.inputs["Color1"])
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.interpolation = "Closest"          # PS1 point sampling
        # A cropped tile has no page around it to wrap into, so EXTEND rather
        # than REPEAT: a UV landing a hair outside samples the edge texel
        # instead of the far side of an unrelated texture.
        tex.extension = "EXTEND"
        tex.location = (-760, 200)
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.location = (-320, 60)
        nt.links.new(tex.outputs["Color"], mix.inputs["Color1"])
        nt.links.new(boost.outputs["Color"], mix.inputs["Color2"])
        if bsdf is not None:
            nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        for attr, val in (("blend_method", "CLIP"),
                          ("surface_render_method", "DITHERED")):
            try:
                setattr(mat, attr, val)
            except Exception:
                pass
        return mat

    # -- use -----------------------------------------------------------------
    def material(self, key):
        if isinstance(key, tuple) and len(key) == 2 and key[0] == "gt_tile":
            return self._mats[key[1]]
        return self._page_material(key)

    def _tile_for(self, key, box):
        for rect, tile in self._tiles.get(key, ()):
            if (rect[0] <= box[0] and rect[1] <= box[1]
                    and box[2] <= rect[2] and box[3] <= rect[3]):
                return tile
        return None

    def remap(self, face_keys, loop_uvs):
        """Face keys and UVs rewritten for the active mode."""
        if self.mode == "PAGE":
            return face_keys, loop_uvs
        keys, uvs = [], []
        for k, u in zip(face_keys, loop_uvs):
            tile = None if (k is None or not u) else self._tile_for(k, _uv_box(u))
            if tile is None:
                if k is not None and u:
                    self._missed += 1
                keys.append(k)
                uvs.append(u)
            else:
                keys.append(tile.key)
                uvs.append([tile.uv(x) for x in u])
        return keys, uvs

    def finish(self):
        if self._missed:
            self.report(f"textures: {self._missed} faces had no recovered tile "
                        f"and kept their whole VRAM page")


def collect_tex_refs(data, tro, sprites=True, props=True):
    """Every (tpage, clut) and texel box a `.tro` is going to draw.

    A separate walk rather than a hook in the build, because the atlas has to be
    packed before the first UV is written and the pack needs the whole set.
    """
    refs = []
    for ch in tro.chunks:
        for pr in ch.prims:
            if pr.uvs:
                refs.append(((pr.tpage, pr.clut), _uv_box(pr.uvs)))
        if sprites:
            for sp in parse_chunk_sprites(data, ch.offset + 0xA4, tro.start_pos,
                                          tro.tex_table):
                refs.append(((sp.tpage, sp.clut), _uv_box(sp.uvs)))
    if props:
        seen = set()
        for chain in parse_lod_lookup(data, tro.start_pos):
            for _d, sd in chain:
                if sd in seen:
                    continue
                seen.add(sd)
                got = parse_lod_shape(data, sd, tro.start_pos)
                if not got:
                    continue
                _v, prims, _sc, sprs = got
                for pr in prims:
                    if pr.uvs:
                        refs.append(((pr.tpage, pr.clut), _uv_box(pr.uvs)))
                for sp in sprs:
                    refs.append(((sp.tpage, sp.clut), _uv_box(sp.uvs)))
    return refs


def bso_tex_refs(bso):
    return [((pr.tpage, pr.clut), _uv_box(pr.uvs))
            for pr in bso.prims if pr.uvs]


def _build_prim_mesh(name, verts, prims, scale, make_material, sprites=(),
                     tex=None):
    """Shared mesh construction for both geometry streams.

    Same corner ordering as the roadway -- quads (0,1,2,3), tris (0,1,2), no
    extra winding reversal.

    The AXIS ORDER differs from the chunk pool, though. Chunk vertices are
    (X, Z, height), because the chunk translation is fed to the GTE through a
    swap (Center.Z -> IR2, Center.Y -> IR3 at 0x80026d48/4c). A prop has no such
    swap: its position at instance+0x10 is copied straight into the object
    matrix's translation slot at +0x14 (0x8001f874-0x8001f888), so its vertices
    must share that ordering -- (X, height, Z). Using the chunk order here tips
    every prop on its side and sinks it into the ground: measured over all 126
    courses, prop bases sit a median 7.9 units BELOW the nearest road that way
    against 0.8 with this one.
    """
    import bpy  # noqa
    # The prop's local Z runs opposite the track's, so Blender Y takes -v[2].
    # Caught by reading a prop's own texture: without it the sign on
    # highway's gt2_prop_0014 renders "GRAN TURISMO" reversed. Negating a
    # single axis flips handedness, so the winding is reversed here to keep
    # normals outward -- the roadway needs no such reversal because there the
    # X mirror and PS1's Y-down screen space already cancel.
    bverts = [(-v[0] * scale, -v[2] * scale, v[1] * scale) for v in verts]
    faces, loop_colors, loop_uvs, face_keys = [], [], [], []
    for pr in usable_prims(prims):
        f = pr.indices
        order = (0, 1, 2, 3) if len(f) == 4 else (0, 1, 2)
        order = tuple(reversed(order))
        faces.append(tuple(f[k] for k in order))
        loop_colors.append([pr.colors[k] for k in order])
        loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
        face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)
    # Slot 8 billboards. Each becomes four fresh vertices, so nothing here can
    # disturb the primitive/face alignment the attributes below depend on. Prop
    # vertices are (X, height, Z), so the quad spreads across axes 0 and 2 and
    # rises along axis 1, and it is turned to face the shape's own origin -- the
    # object it is standing in for.
    n_sprite = 0
    for sp in sprites:
        corners = _billboard_corners(sp, (0, 2), 1, (0, 0))
        first = len(bverts)
        bverts.extend((-c[0] * scale, -c[2] * scale, c[1] * scale) for c in corners)
        # TL, TR, BR, BL, then reversed for the same handedness flip the solid
        # primitives get from the (-x, -z, y) mapping.
        loop = (first + 0, first + 1, first + 3, first + 2)
        uvs = _sprite_uv_order(sp.uvs)
        faces.append(tuple(reversed(loop)))
        loop_colors.append(list(reversed([sp.color] * 4)))
        loop_uvs.append(list(reversed(uvs)))
        face_keys.append((sp.tpage, sp.clut))
        n_sprite += 1
    if not faces:
        return None
    if tex is not None:
        face_keys, loop_uvs = tex.remap(face_keys, loop_uvs)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(bverts, [], faces)
    # No mesh.validate() here: usable_prims() has already removed everything it
    # would legitimately delete, and the only thing left for it to take are the
    # intentional coplanar decals. Removing any face would silently shift every
    # per-face attribute assigned below.
    if len(mesh.polygons) != len(faces):
        return None
    try:
        ca = mesh.color_attributes.new(name="GT2_Color", type="BYTE_COLOR",
                                       domain="CORNER")
        for ti, cols in enumerate(loop_colors):
            if ti >= len(mesh.polygons):
                break
            poly = mesh.polygons[ti]
            for c in range(min(poly.loop_total, len(cols))):
                li = poly.loop_start + c
                if li < len(ca.data):
                    ca.data[li].color = (cols[c][0], cols[c][1], cols[c][2], 1.0)
    except Exception:
        pass
    if any(u is not None for u in loop_uvs):
        try:
            uvl = mesh.uv_layers.new(name="GT2_UV")
            for ti, uvs in enumerate(loop_uvs):
                if uvs is None or ti >= len(mesh.polygons):
                    continue
                poly = mesh.polygons[ti]
                for c in range(min(poly.loop_total, len(uvs))):
                    li = poly.loop_start + c
                    if li < len(uvl.data):
                        uvl.data[li].uv = uvs[c]
        except Exception:
            pass
    slot_of = {}
    for k in face_keys:
        if k not in slot_of:
            slot_of[k] = len(slot_of)
            mesh.materials.append(make_material(k))
    if len(slot_of) > 1:
        for i, poly in enumerate(mesh.polygons):
            if i < len(face_keys):
                poly.material_index = slot_of[face_keys[i]]
    mesh["gt2_sprite_faces"] = n_sprite
    return mesh


def instance_group_mask(data: bytes, chunks) -> int:
    """Which of the 33 instance groups this course ever asks to be drawn.

    Not a formality: the group dispatcher at 0x8002002c walks groups 0..31 and
    draws each one ONLY if the matching bit is set in the mask handed to it in
    $a2 (`andi $v0, $s2, 1` / `srl $s2, $s2, 1`), then draws group 32
    unconditionally. That mask is the return value of the chunk-draw pass at
    0x80020110, which ORs together `lw $v0, 0xc($a1)` -- a 32-bit group bitmask
    stored on every TrackChunk at +0x0C -- over the chunks it just found
    visible. So a prop group is on screen only while a chunk that requests it
    is, and a group no chunk ever names is dead data.

    Across the retail set exactly one course has such a group: lagunareverse
    populates 6, 8, 9, 10 and 11 and never requests any of them.
    """
    mask = 0
    for ch in chunks:
        if 0 <= ch.offset + 0x10 <= len(data):
            mask |= struct.unpack_from("<I", data, ch.offset + 0x0C)[0]
    return mask


def _import_lod_props(data, start_pos, context, root, make_material, report,
                      chunks=(), depth_bias=0.0, tex=None):
    """Place every instanced prop, drawing each one's nearest LOD level."""
    import bpy  # noqa
    import math
    lookup = parse_lod_lookup(data, start_pos)
    instances = parse_instances(data, start_pos)
    group_mask = instance_group_mask(data, chunks)
    # Road height reference, so a prop parked in the sky can be reported rather
    # than quietly imported as though it belonged there.
    road = []
    for ch in chunks:
        if not ch.verts:
            continue
        ox, oy, oz = chunk_origin(ch.center_raw)
        n_ = len(ch.verts)
        road.append((-(sum(v[0] for v in ch.verts) / n_ + ox) * _CHUNK_LOCAL_SCALE,
                     (sum(v[1] for v in ch.verts) / n_ + oz) * _CHUNK_LOCAL_SCALE,
                     (sum(v[2] for v in ch.verts) / n_ + oy) * _CHUNK_LOCAL_SCALE))
    stranded = []
    if not lookup or not instances:
        report("no instanced props found")
        return 0, 0
    props = bpy.data.collections.new("GT2 Props (LOD)")
    root.children.link(props)
    far_props = None
    n_far = 0
    mesh_cache = {}
    n_obj = n_face = 0
    missing = 0
    for n, inst in enumerate(instances):
        if not (0 <= inst.lod_index < len(lookup)) or not lookup[inst.lod_index]:
            missing += 1
            continue
        # Level 0 is the nearest / most detailed, but a chain may open with an
        # empty level (437 LOD shapes across the retail set carry
        # vertexCount == 0), so fall through to the first level that has
        # geometry rather than dropping the instance.
        mesh = None
        # A chain is (max distance, shape) nearest-first, and one that opens
        # with an EMPTY shape means the game draws nothing up close -- the
        # object only appears in a band further out, typically as a coarse
        # stand-in for scenery or for the roadway itself. Falling straight
        # through to the next level drops that stand-in into the middle of the
        # track: 398 of the retail set's 6,083 instances are these, 46 of them
        # on `parma` alone. They are built into their own unticked collection
        # instead. An empty level that carries a BILLBOARD list is a different
        # thing and is unaffected -- that is how a distant object is swapped for
        # a single sprite, and parse_lod_shape() returns it rather than None.
        distant = parse_lod_shape(data, lookup[inst.lod_index][0][1],
                                  start_pos) is None
        for _dist, sd in lookup[inst.lod_index]:
            if sd not in mesh_cache:
                got = parse_lod_shape(data, sd, start_pos)
                mesh_cache[sd] = None
                if got is not None:
                    verts, prims, scale, sprites = got
                    mesh_cache[sd] = _build_prim_mesh(
                        f"gt2_lod_{inst.lod_index:03d}", verts, prims,
                        scale, make_material, sprites, tex)
            mesh = mesh_cache[sd]
            if mesh is not None:
                break
        if mesh is None:
            missing += 1
            continue
        obj = bpy.data.objects.new(
            f"gt2_{'far' if distant else 'prop'}_{n:04d}"
            f"_lod{inst.lod_index:03d}", mesh)
        px, py, pz = inst.pos
        # Instance position is 16.16 and ordered like Center: (X, height, Z).
        # `depth_bias` sinks the prop; zero by default, so the geometry
        # stays exactly as authored unless asked.
        obj.location = (-px * _WORLD_SCALE, pz * _WORLD_SCALE,
                        py * _WORLD_SCALE - depth_bias)
        # Rotation: the record holds THREE angles at +0x00/+0x02/+0x04, all
        # masked to 12 bits by the matrix builder at 0x800812d4 (4096 = one full
        # turn, indexing a sine table at 0x80092ef8 with cosine 1024 entries
        # further on). Only +0x02 varies in practice -- it is non-zero on 29.6%
        # of the retail set's 6,083 instances against 1.2% and 0.5% for the
        # other two -- so it is the yaw, and it is the only one applied here.
        # Sign: measured, not assumed. Comparing each rotated prop's principal
        # horizontal axis against the local road heading over all 126 courses,
        # negative yaw gives a 35.5 deg median error with 30.0% inside 15 deg,
        # positive yaw 46.3 deg and 18.1% -- the latter being indistinguishable
        # from the ~45 deg / ~17% you get from random orientations.
        obj.rotation_euler = (0.0, 0.0, -inst.yaw * math.tau / 4096.0)
        # Scale is 4096 = 1.0; the routine at 0x8007b1bc early-outs when all
        # three components are 4096, and 99.8% of retail instances hit that.
        sx, sy, sz = inst.scale
        obj.scale = (sx / 4096.0, sz / 4096.0, sy / 4096.0)
        obj["gt2_instance_index"] = n
        obj["gt2_lod_index"] = inst.lod_index
        obj["gt2_instance_group"] = inst.group
        obj["gt2_flags"] = inst.flags
        obj["gt2_lod_levels"] = len(lookup[inst.lod_index])
        obj["gt2_group_requested"] = bool(inst.group >= 32
                                          or (group_mask >> inst.group) & 1)
        if road:
            near = min(road, key=lambda p: (p[0] - obj.location[0]) ** 2
                                           + (p[1] - obj.location[1]) ** 2)
            above = obj.location[2] - near[2]
            obj["gt2_height_above_road"] = round(above, 2)
            if above > 100.0:
                stranded.append((n, inst.group, inst.lod_index, round(above)))
        obj["gt2_distant_standin"] = distant
        if distant:
            if far_props is None:
                far_props = bpy.data.collections.new("GT2 Distant Stand-ins")
                root.children.link(far_props)
                try:
                    def _walk(layer):
                        if layer.collection is far_props:
                            layer.exclude = True
                            return True
                        return any(_walk(c) for c in layer.children)
                    _walk(context.view_layer.layer_collection)
                except Exception:
                    pass
            far_props.objects.link(obj)
            n_far += 1
            continue
        props.objects.link(obj)
        n_obj += 1
        n_face += len(mesh.polygons)
    for n, grp, lod, above in stranded:
        report(f"NOTE: instance {n} (group {grp}, LOD {lod}) sits {above} units "
               f"above the nearest road. The record is well formed and its group "
               f"is {'requested' if (group_mask >> grp) & 1 else 'NEVER requested'} "
               f"by this course's chunks -- so this is where the file puts it, "
               f"not a placement error.")
    n_sprite = sum(m.get("gt2_sprite_faces", 0)
                   for m in mesh_cache.values() if m is not None)
    if n_far:
        report(f"distant stand-ins: {n_far} instances whose nearest LOD level is "
               f"empty, so the game draws nothing up close (collection unticked)")
    report(f"props: {n_obj} instances of {sum(1 for m in mesh_cache.values() if m)} "
           f"LOD meshes, {n_face} faces ({n_sprite} of them billboards)"
           + (f" ({missing} skipped)" if missing else ""))
    return n_obj, n_face



def _build_bso_mesh(name, bso, scale, make_material, tex=None):
    """Build the skydome mesh.

    Corner order is NOT the roadway's. A `.bso` primitive stores literal PS1
    packet operands -- its four indices fill xy0..xy3 in order -- so quads are
    the console's Z-order (TL, TR, BL, BR) and the polygon loop is (0,1,3,2).
    Measured over all 4,458 retail sky quads: 0.07% self-intersect that way
    against 99.98% with the roadway's (0,1,2,3).

    Axis mapping follows the ROADWAY, not the props. Sky vertices are ordered
    (X, height, Z) like a prop's, but a skybox is drawn on the camera rotation
    with no object matrix of its own, so it has to agree with the world the
    chunks define: (x, y, z) -> (-x, z, y). That is a proper rotation
    (determinant +1), so the stored winding carries over unchanged -- unlike the
    props' (-x, -z, y), which is a mirror and needs its winding reversed.
    """
    import bpy  # noqa
    bverts = [(-v[0] * scale, v[2] * scale, v[1] * scale) for v in bso.verts]
    faces, loop_colors, loop_uvs, face_keys = [], [], [], []
    for pr in usable_prims(bso.prims):
        f = pr.indices
        order = (0, 1, 3, 2) if len(f) == 4 else (0, 1, 2)
        faces.append(tuple(f[k] for k in order))
        loop_colors.append([pr.colors[k] for k in order])
        loop_uvs.append([pr.uvs[k] for k in order] if pr.uvs else None)
        face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)
    if not faces:
        return None
    if tex is not None:
        face_keys, loop_uvs = tex.remap(face_keys, loop_uvs)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(bverts, [], faces)
    if len(mesh.polygons) != len(faces):
        return None
    try:
        ca = mesh.color_attributes.new(name="GT2_Color", type="BYTE_COLOR",
                                       domain="CORNER")
        for ti, cols in enumerate(loop_colors):
            poly = mesh.polygons[ti]
            for c in range(min(poly.loop_total, len(cols))):
                li = poly.loop_start + c
                if li < len(ca.data):
                    ca.data[li].color = (cols[c][0], cols[c][1], cols[c][2], 1.0)
    except Exception:
        pass
    if any(u is not None for u in loop_uvs):
        try:
            uvl = mesh.uv_layers.new(name="GT2_UV")
            for ti, uvs in enumerate(loop_uvs):
                if uvs is None:
                    continue
                poly = mesh.polygons[ti]
                for c in range(min(poly.loop_total, len(uvs))):
                    li = poly.loop_start + c
                    if li < len(uvl.data):
                        uvl.data[li].uv = uvs[c]
        except Exception:
            pass
    slot_of = {}
    for k in face_keys:
        if k not in slot_of:
            slot_of[k] = len(slot_of)
            mesh.materials.append(make_material(k))
    if len(slot_of) > 1:
        for i, poly in enumerate(mesh.polygons):
            if i < len(face_keys):
                poly.material_index = slot_of[face_keys[i]]
    return mesh


def import_gt2_bso(filepath: str, data: bytes, context, *, report=None,
                   import_textures: bool = True, sky_radius: float = 1500.0,
                   root=None, name_hint: str = None,
                   texture_mode: str = "PAGE") -> Tuple[int, int, int, int]:
    """Import a `.bso` skybox as one mesh.

    `sky_radius` is the world radius the dome is scaled to. There is no "true"
    scale to recover: a skybox is drawn on the camera's rotation with its
    translation dropped, so every uniform scale looks identical in game and only
    the direction of each vertex matters. 1500 clears GT2's widest course
    (Special Stage Route 5, 1,326 units across).
    """
    import bpy  # noqa
    import os

    def _report(msg):
        if report:
            report(msg)

    bso = parse_bso(data)
    if bso is None:
        _report("not a GT2 .bso skybox (magic mismatch)")
        return (0, 0, 0, 0)

    name = name_hint or os.path.basename(filepath).split(".")[0]
    vram = None
    if import_textures:
        bp = bsp_path_for(filepath)
        if bp is None:
            _report(f"sky {name}: no .bsp sidecar; importing untextured")
        else:
            vram = load_trp_vram(bp)      # a .bsp IS a .trp container
            if vram is None:
                _report(f"sky {name}: could not decode {bp}")
    # The dome has its own .bsp, so it gets its own mapper -- and in ATLAS
    # mode its own atlas, rather than being packed with a course whose VRAM it
    # does not share.
    tex = TextureMapper(texture_mode, vram, _report, tag=f"GT2_sky_{name}")
    tex.build(bso_tex_refs(bso))
    make_material, mat_cache = tex.material, tex._page_cache

    radius = max(max(abs(v[0]) for v in bso.verts),
                 max(abs(v[2]) for v in bso.verts), 1)
    scale = float(sky_radius) / radius
    mesh = _build_bso_mesh(f"gt2_sky_{name}", bso, scale, make_material, tex)
    if mesh is None:
        _report(f"sky {name}: no usable primitives")
        return (0, 0, 0, 0)

    if root is None:
        root = bpy.data.collections.new("GT2 Sky (.bso)")
        context.scene.collection.children.link(root)
    col = bpy.data.collections.new(f"sky_{name}")
    root.children.link(col)
    obj = bpy.data.objects.new(f"gt2_sky_{name}", mesh)
    obj["gt2_sky_name"] = name
    # The two RGB words at +0x04 and +0x08 are stored as finished GPU colour
    # words -- RGB then the POLY_F4 command byte 0x28 -- so they are ready-made
    # background fills rather than anything the geometry uses.
    obj["gt2_sky_colour_a"] = tuple(round(c, 4) for c in bso.colour_a)
    obj["gt2_sky_colour_b"] = tuple(round(c, 4) for c in bso.colour_b)
    obj["gt2_sky_radius"] = float(sky_radius)
    col.objects.link(obj)
    _report(f"sky {name}: {len(bso.verts)} verts, {len(mesh.polygons)} faces, "
            f"{len(mat_cache)} materials, radius {sky_radius:g}; background "
            f"A=#{int(bso.colour_a[0]*255):02x}{int(bso.colour_a[1]*255):02x}"
            f"{int(bso.colour_a[2]*255):02x} "
            f"B=#{int(bso.colour_b[0]*255):02x}{int(bso.colour_b[1]*255):02x}"
            f"{int(bso.colour_b[2]*255):02x}")
    return (1, len(bso.verts), len(mesh.polygons), 1)

def import_gt2_tro(filepath: str, data: bytes, context, *,
                   report=None, import_textures: bool = True,
                   import_props: bool = True, import_sky: bool = True,
                   import_glare: bool = True, sky_radius: float = 1500.0,
                   prop_depth_bias: float = 0.0,
                   texture_mode: str = "PAGE",
                   max_edge: float = 0.0) -> Tuple[int, int, int, int]:
    """Import a GT2 `.tro` into Blender. `data` is already decompressed (the
    caller unwraps `.tro.gz`). Each chunk becomes one mesh placed at its 16.16
    world position, under one collection.

    `max_edge` drops faces with an edge longer than the given local-space
    distance. It defaulted to 80.0 while the roadway used the consecutive-run
    heuristic, to hide that decode's stray faces; the indices are now exact, so
    it defaults off -- a nonzero value would discard legitimate large landscape
    polygons."""
    import bpy  # noqa

    def _report(msg):
        if report:
            report(msg)

    tro = parse_tro(data)
    if tro is None:
        _report("not a GT2 .tro (magic mismatch)")
        return (0, 0, 0, 0)

    _report(f"GT2 .tro: {len(tro.chunks)} track chunks "
            f"(version {tro.version:#x}, ptr base {tro.start_pos:#x}, "
            f"texture table {tro.tex_table:#x})")

    vram = None
    if import_textures:
        tp = trp_path_for(filepath)
        if tp is None:
            _report("no .trp sidecar found; importing untextured")
        else:
            vram = load_trp_vram(tp)
            if vram is None:
                _report(f"could not decode {tp}; importing untextured")
    # PAGE hands (tpage, clut) straight to the material factory, exactly as
    # before; the other two modes recover individual textures out of the pages
    # first and rewrite every UV to match. See TextureMapper.
    tex = TextureMapper(texture_mode, vram, _report, tag="GT2")
    tex.build(collect_tex_refs(data, tro, props=import_props))
    make_material, mat_cache = tex.material, tex._page_cache

    # A chunk's primitives address its pool with NINE bits, so a pool longer
    # than 512 has vertices no primitive can reach. Retail respects that
    # everywhere (14,387 chunks, 0 over), and so do 47 of the Euro Demo 53
    # build's 48 courses. `seattle2000` is the exception -- 22 chunks up to
    # 1,010 vertices, 3,825 unreachable in total -- and the demo's own renderer
    # has the identical limit (its decoder is byte-for-byte retail's:
    # sll 3 / sra 6 / sra 15 with andi 0xff8), so the game cannot draw them
    # either.
    over_9bit = [(ch.index, len(ch.verts)) for ch in tro.chunks
                 if len(ch.verts) > 512]
    if over_9bit:
        lost = sum(n - 512 for _i, n in over_9bit)
        worst = max(over_9bit, key=lambda x: x[1])
        _report(f"WARNING: {len(over_9bit)} chunks have more vertices than the "
                f"format's 9-bit indices can address (max 512); {lost} vertices "
                f"are unreachable, worst is chunk {worst[0]} with {worst[1]}. "
                f"Those chunks import with malformed geometry unless a geometry "
                f"reference is supplied. This is a property of the file, not the "
                f"import: the game's own chunk decoder is 9-bit too.")

    root = bpy.data.collections.new("GT2 Track (.tro)")
    context.scene.collection.children.link(root)

    n_obj = n_vert = n_face = n_uv = 0
    n_skipped_attr = 0
    n_sprite = 0
    for ch in tro.chunks:
        if not ch.verts or not ch.prims:
            continue
        # Pool origin from the masked Center, in the SAME 1/64-world units as
        # the pool itself, so origin and locals share one mapping: GT2 is Y-up,
        # X mirrored -> Blender (-x, z, y).
        ox, oy, oz = chunk_origin(ch.center_raw)
        oX = -ox * _CHUNK_LOCAL_SCALE      # Center.X pairs with pool component 0
        oY = oz * _CHUNK_LOCAL_SCALE       # Center.Z pairs with pool component 1
        oZ = oy * _CHUNK_LOCAL_SCALE       # Center.Y (height) with component 2
        # The pool is stored (X, Z, Y) while Center is (X, Y, Z) -- the same
        # swap the renderer makes feeding the translation into the GTE
        # (Center.Z -> IR2, Center.Y -> IR3 at 0x80026d48/0x80026d4c). Pairing
        # them the other way puts 18.5% of chunks a whole grid cell out; this
        # way, 1.6%.
        bverts = [(-lx * _CHUNK_LOCAL_SCALE, ly * _CHUNK_LOCAL_SCALE,
                   lz * _CHUNK_LOCAL_SCALE) for (lx, ly, lz) in ch.verts]

        faces = []
        loop_colors = []
        loop_uvs = []
        face_keys = []
        for pr in usable_prims(ch.prims):
            f = pr.indices
            if max_edge > 0:
                pts = [bverts[k] for k in f]
                longest = 0.0
                for a in range(len(pts)):
                    for b in range(a + 1, len(pts)):
                        dist = sum((pts[a][k] - pts[b][k]) ** 2
                                   for k in range(3)) ** 0.5
                        longest = max(longest, dist)
                if longest > max_edge:
                    continue
            # Corner order is NOT the PS1 packet order. From the mtc2 sequence
            # in each of the eight loops: quads load V0<-i1, V1<-i2, V2<-i0 and
            # then RTPS i3 into V3, so the outline V0,V1,V3,V2 = i1,i2,i3,i0 --
            # as a cycle, simply (0,1,2,3). Treating the record as a PS1 strip
            # and using (0,1,3,2) makes EVERY quad a bowtie: 99.9% of them, each
            # rendering as a triangular hole plus a back-facing triangle.
            #
            # Triangles load V0<-i0, V1<-i2, V2<-i1, i.e. wound opposite to the
            # quads -- GT2 compensates in its cull test (the quad loop negates
            # the NCLIP result before checking it), so the stored winding is not
            # a consistent orientation cue. For a DCC mesh we want one
            # convention, and the geometry picks it unambiguously: with (0,1,2)
            # the near-horizontal faces of every textured type point up --
            # FT3 97.2%, GT3 100%, FT4 95.0%, GT4 100% over five courses.
            # (F3/G3 come out mostly downward either way; they are the
            # untextured filler/underside polygons.)
            order = (0, 1, 2, 3) if len(f) == 4 else (0, 1, 2)
            poly = tuple(f[k] for k in order)
            cols = [pr.colors[k] for k in order]
            uvs = [pr.uvs[k] for k in order] if pr.uvs else None
            # No extra winding reversal for the X mirror: PS1 screen space is
            # already Y-down, so that flip and the mirror cancel. Reversing here
            # as well turns the whole course inside out (up-facing road drops
            # from 95% to 5%).
            faces.append(poly)
            loop_colors.append(cols)
            loop_uvs.append(uvs)
            face_keys.append((pr.tpage, pr.clut) if pr.uvs is not None else None)

        # Slot 8 billboards: trees, bushes, roadside clutter. The chunk pool is
        # (X, Z, height), so these spread across components 0 and 1 and rise
        # along 2. Each gets four fresh vertices appended after the shared pool,
        # which keeps the face/primitive alignment the attribute loops below
        # rely on. Facing: GT2 yaws them to the camera every frame, so a baked
        # mesh has to pick something -- they are turned toward the centroid of
        # their own chunk's vertices, which is the road.
        sprites = parse_chunk_sprites(data, ch.offset + 0xA4, tro.start_pos,
                                      tro.tex_table)
        if sprites:
            cx = sum(v[0] for v in ch.verts) / len(ch.verts)
            cy = sum(v[1] for v in ch.verts) / len(ch.verts)
            for sp in sprites:
                corners = _billboard_corners(sp, (0, 1), 2, (cx, cy))
                first = len(bverts)
                bverts.extend((-c[0] * _CHUNK_LOCAL_SCALE,
                               c[1] * _CHUNK_LOCAL_SCALE,
                               c[2] * _CHUNK_LOCAL_SCALE) for c in corners)
                # TL, TR, BR, BL -- and no winding reversal, for the same reason
                # the roadway needs none: the X mirror and PS1's Y-down screen
                # space cancel.
                faces.append((first + 0, first + 1, first + 3, first + 2))
                loop_colors.append([sp.color] * 4)
                loop_uvs.append(_sprite_uv_order(sp.uvs))
                face_keys.append((sp.tpage, sp.clut))
                n_sprite += 1
        if not faces:
            continue

        face_keys, loop_uvs = tex.remap(face_keys, loop_uvs)

        mesh = bpy.data.meshes.new(f"gt2_chunk_{ch.index:03d}")
        mesh.from_pydata(bverts, [], faces)
        # See usable_prims(): validate() must not run before the per-face
        # attributes below, or a single deleted face shifts all of them.
        if len(mesh.polygons) != len(faces):
            _report(f"chunk {ch.index}: mesh has {len(mesh.polygons)} faces for "
                    f"{len(faces)} primitives; skipping attributes")
            n_skipped_attr += 1
        try:
            ca = mesh.color_attributes.new(name="GT2_Color", type="BYTE_COLOR",
                                           domain="CORNER")
            for ti, cols in enumerate(loop_colors):
                if ti >= len(mesh.polygons):
                    break
                poly = mesh.polygons[ti]
                for corner in range(min(poly.loop_total, len(cols))):
                    li = poly.loop_start + corner
                    if li < len(ca.data):
                        c = cols[corner]
                        ca.data[li].color = (c[0], c[1], c[2], 1.0)
        except Exception:
            pass
        if any(u is not None for u in loop_uvs):
            try:
                uvl = mesh.uv_layers.new(name="GT2_UV")
                for ti, uvs in enumerate(loop_uvs):
                    if uvs is None or ti >= len(mesh.polygons):
                        continue
                    poly = mesh.polygons[ti]
                    for corner in range(min(poly.loop_total, len(uvs))):
                        li = poly.loop_start + corner
                        if li < len(uvl.data):
                            uvl.data[li].uv = uvs[corner]
                n_uv += 1
            except Exception:
                pass

        slot_of = {}
        for k in face_keys:
            if k not in slot_of:
                slot_of[k] = len(slot_of)
                if isinstance(k, tuple) and k and k[0] == "ref":
                    mesh.materials.append(bpy.data.materials.get(k[1])
                                          if k[1] else make_material(None))
                else:
                    mesh.materials.append(make_material(k))
        if len(slot_of) > 1:
            for i, poly in enumerate(mesh.polygons):
                if i < len(face_keys):
                    poly.material_index = slot_of[face_keys[i]]

        obj = bpy.data.objects.new(f"gt2_chunk_{ch.index:03d}", mesh)
        obj.location = (oX, oY, oZ)
        obj["gt2_chunk_index"] = ch.index
        obj["gt2_prev"] = ch.prev_index
        obj["gt2_next"] = ch.next_index
        obj["gt2_index_mode"] = "9bit_packed"
        obj["gt2_origin_raw"] = (ox, oy, oz)
        obj["gt2_sprite_faces"] = len(sprites)
        col_c = bpy.data.collections.new(f"chunk_{ch.index:03d}")
        root.children.link(col_c)
        col_c.objects.link(obj)
        n_obj += 1
        n_vert += len(bverts)
        n_face += len(faces)

    if import_glare:
        # Slot 9. Chunk flares are gathered into one world-space mesh for the
        # whole course: they are tiny, there are hundreds of them, and one
        # object per chunk would be noise. Night courses only -- 17 of the 126
        # carry any.
        make_glare, glare_cache = _make_glare_material_factory()
        all_glares = []
        for ch in tro.chunks:
            gl = parse_glares(data, ch.offset + 0xA4, tro.start_pos)
            if not gl:
                continue
            ox, oy, oz = chunk_origin(ch.center_raw)

            def to_world(p, ox=ox, oy=oy, oz=oz):
                return (-(p[0] + ox) * _CHUNK_LOCAL_SCALE,
                        (p[1] + oz) * _CHUNK_LOCAL_SCALE,
                        (p[2] + oy) * _CHUNK_LOCAL_SCALE)
            all_glares.append((gl, to_world))
        if all_glares:
            verts, faces, uvs, mats = [], [], [], []
            for gl, tw in all_glares:
                _glare_quads(gl, tw, verts, faces, uvs, mats, make_glare)
            gmesh = bpy.data.meshes.new("gt2_lamp_glare")
            gmesh.from_pydata(verts, [], faces)
            if len(gmesh.polygons) == len(faces):
                uvl = gmesh.uv_layers.new(name="GT2_UV")
                for ti, quad in enumerate(uvs):
                    poly = gmesh.polygons[ti]
                    for c in range(min(poly.loop_total, 4)):
                        uvl.data[poly.loop_start + c].uv = quad[c]
                slot_of = {}
                for m in mats:
                    if m.name not in slot_of:
                        slot_of[m.name] = len(slot_of)
                        gmesh.materials.append(m)
                if len(slot_of) > 1:
                    for i, poly in enumerate(gmesh.polygons):
                        poly.material_index = slot_of[mats[i].name]
                gcol = bpy.data.collections.new("GT2 Lamp Glare")
                root.children.link(gcol)
                gobj = bpy.data.objects.new("gt2_lamp_glare", gmesh)
                gobj["gt2_glare_count"] = len(faces)
                gcol.objects.link(gobj)
                n_obj += 1
                n_face += len(faces)
                _report(f"lamp glare: {len(faces)} flares in "
                        f"{len(glare_cache)} colours (ShapeData slot 9)")
        else:
            _report("lamp glare: none (this is a daylight course)")

    if import_props:
        p_obj, p_face = _import_lod_props(data, tro.start_pos, context, root,
                                          make_material, _report, tro.chunks,
                                          prop_depth_bias, tex)
        n_obj += p_obj
        n_face += p_face

    if import_sky:
        # The sky is a separate file: bgsobj/<name>.bso next to crsobj, with
        # .crsinfo naming which one this course uses. Absent when only crsobj
        # has been extracted, which is the common case.
        sky_path, rec = find_sky_for_tro(filepath)
        if sky_path is None:
            _report("no skybox found (needs the volume's bgsobj/ and .crsinfo "
                    "alongside crsobj/)")
        else:
            sdata = _read_maybe_gz(sky_path)
            if sdata is None:
                _report(f"could not read {sky_path}")
            else:
                s_obj, s_vert, s_face, _ = import_gt2_bso(
                    sky_path, sdata, context, report=_report,
                    import_textures=import_textures, sky_radius=sky_radius,
                    root=root, name_hint=rec["sky"],
                    texture_mode=texture_mode)
                n_obj += s_obj
                n_vert += s_vert
                n_face += s_face

    _report(f"imported {n_obj} chunk objects, {n_vert} verts, {n_face} faces "
            f"({n_uv} chunks with UVs; masked-Center placement, "
            f"9-bit packed indices)")
    if n_sprite:
        _report(f"billboards: {n_sprite} chunk sprites (ShapeData slot 8)")
    if n_skipped_attr:
        _report(f"WARNING: {n_skipped_attr} chunks had a face-count mismatch; "
                f"their UVs and materials were left unassigned")
    if vram is not None:
        _report(f"textures: {len(mat_cache)} materials from the .trp "
                f"({sum(1 for k in mat_cache if k is not None)} texture pages)")
    tex.finish()
    return (n_obj, n_vert, n_face, len(tro.chunks))
