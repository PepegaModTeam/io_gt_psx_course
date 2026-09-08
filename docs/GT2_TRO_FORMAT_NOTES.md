# Foreword

It may be a bit hard to parse through as the rest of this document has been AI generated. It needs some touch ups, however, the information is mostly correct and functional enough for this application.

# GT2 `.tro` / `.trp` / `.bso` Track Format - Notes

## Subjects used for research: 

- GT2-demo **Seattle** (`seattle2000_tro`, crashes in-game)
- retail GT2 **Seattle** (`seattle_tro`, runs)
- **Special Stage Route 5 / highway** (`highway_tro`)

## Status

VALIDATED
- Container: header, TrackChunkTable, chunk prev/next ring.
- **Three geometry streams, all decoded**: the TrackChunk roadway (9-bit
  indices, shared texture descriptors), the instanced LOD props (10-bit indices,
  inline UVs, per-shape scale) and the **billboard sprites in ShapeData slot 8**
  (16-byte records on chunks, 28-byte on props). 699,229 + 138,730 primitives
  and 16,954 billboards across all 126 courses.
- **Skyboxes** (`bgsobj/*.bso` + `.bsp`, 12-bit indices, doubled packets) and the
  `.crsinfo` course table that says which of the 34 each course uses.
- **Lamp glare** (ShapeData slot 9), on the 17 night and evening courses.
- **World placement is 16.16 fixed-point (/65536)**, not /4096.
- **Vertices are 3x s16 (X,Y,Z) + s16 pad**, 8 bytes each (the 4th s16 is always
  0).
- Lists are homogeneous (one prim type each), and the list SLOT selects the
  type. Record sizes: F3/F4/FT3/FT4 12, G3/GT3 20, G4/GT4 24 -- see the SOLVED
  section; the earlier FT3/FT4=24, GT3=32, GT4=36 reading was wrong.
- **Instanced LOD meshes (props/buildings), confirmed against the renderer at
  0x80019b58 and now imported.** They use the SAME ShapeData layout as the track
  chunks but differ in two ways:
  - indices are **10-bit at bits 0, 10, 20** (plus a 4th at w1 bits 0-9), not
    the chunks' 9-bit -- `sll t,w0,3 / andi 0x1ff8`, `sra t,w0,7 / andi 0x1ff8`,
    `sra t,w0,0x11 / andi 0x1ff8`. Verified on **140,348 LOD primitives across
    all 126 courses: 100% in range** (the chunks' 9-bit reading gives 23%).
  - records are **larger**, because a prop carries its UVs inline instead of
    going through the chunks' shared descriptor table. From each loop's own
    count arithmetic: **F3 12, F4 12, G3 20, G4 24, FT3 24, FT4 24, GT3 32,
    GT4 36** -- i.e. the sizes the pre-0.95 notes listed. Those were never wrong
    for props; they were only wrong for chunks, which is where the two streams
    were being conflated.

  Record layout (identical to the chunk record through byte 11):

      bytes 0-3    w0: i0 bits 0-9, i1 bits 10-19, i2 bits 20-29
      bytes 4-7    w1: i3 bits 0-9 (quads)
      bytes 8-10   RGB (corner 0)        byte 11  PS1 primitive code
      textured:    bytes 12-23 the SAME 12-byte UV block as a chunk descriptor
                   (u0,v0,clut / u1,v1,tpage / u2,v2,u3,v3)
      gouraud:     further RGB triplets at +0x0C untextured, +0x18 textured

  Corner order matches the chunks exactly (quads V0<-i1,V1<-i2,V2<-i0 then i3;
  tris V0<-i0,V1<-i2,V2<-i1), so the importer uses the same (0,1,2,3)/(0,1,2).

- **LOD lookup and instance placement.** Header+0x14 is `u32 count` then that
  many pointers, each to `u32 numLods; numLods x { u32 maxDistance; u32
  shapeDataPtr }`; the renderer indexes it as `[$s0 + 8 + idx*8]` at 0x8001f990.
  Level 0 is nearest, but **437 LOD shapes across the retail set have
  vertexCount == 0**, so a chain can open empty and a reader must fall through
  to the first level with geometry (doing so recovers e.g. 9 of Autumn Ring's
  85 props).
  Header+0x118 is 33 group pointers, each `s32 count` then 0x1C-byte records.
  The field roles are read off the consumer at 0x8001f874-0x8001f8f0, not
  guessed -- an earlier reading of `flags, yaw, unk, lod_index` was wrong in
  everything but the lod_index:

      +0x00 s16 rotation A          +0x08 s16 scale X
      +0x02 s16 rotation B          +0x0A s16 scale Y
      +0x04 s16 rotation C          +0x0C s16 scale Z
      +0x06 s16 lod_index           +0x0E s16 LOD-distance divisor
      +0x10 s32 pos X / +0x14 pos height / +0x18 pos Z   (16.16, like Center)

  - The three angles go to the matrix builder at **0x800812d4**, which masks
    each to 12 bits (**4096 = one full turn**) and indexes a sine table at
    0x80092ef8, cosine being 1024 entries further on. Called as
    `(A = -[+0x02], B = [+0x00], C = [+0x04])`, it emits the 3x3

        [ cosA cosC - sinA sinB sinC,  -cosA sinC - sinA sinB cosC,  sinA cosB ]
        [ cosB sinC,                    cosB cosC,                   sinB      ]
        [ -sinA cosC - cosA sinB sinC,  sinA sinC - cosA sinB cosC,  cosA cosB ]

    (it builds this by loading a partial matrix whose middle column is never
    read, then pushing two basis vectors with VY = 0 through MVMVA). With
    B = C = 0 that collapses to a clean rotation about the **middle** axis --
    which is height -- so **+0x02 is a yaw**. Only it varies in practice:
    non-zero on **29.6%** of the 6,083 retail instances against 1.2% and 0.5%
    for the other two, so it is the only one applied.
  - Its **sign is negative** in Blender (the builder negates it, and the X
    mirror negates again). Measured rather than assumed: comparing each rotated
    prop's principal horizontal axis with the local road heading over all 126
    courses gives a **35.5 deg median error and 30.0% inside 15 deg for -yaw**
    against **46.3 deg / 18.1% for +yaw** -- the latter indistinguishable from
    the ~45 deg / ~17% of random orientations.
  - Scale is **4096 = 1.0**; the routine at 0x8007b1bc early-outs when all three
    components are 4096, which 99.8% of instances are.
  - **+0x0E is not a fourth scale component** -- 0x8001f950 divides the LOD
    distance by it.

  **Props are also mirrored relative to the roadway.** Blender's Y takes
  **-v[2]**, not +v[2]. This is invisible on untextured geometry and on
  symmetric props; it shows up in a prop's own texture, where highway's
  `gt2_prop_0014` (LOD 32) renders its "GRAN TURISMO" sign reversed without it.
  Negating a single axis flips handedness, so prop winding must be reversed as
  well -- the roadway needs no such reversal, because there the X mirror and
  PS1's Y-down screen space already cancel.

  **Vertex AXIS ORDER differs from the chunk pool too.** Chunk vertices are
  (X, Z, height) because the chunk translation reaches the GTE through a swap
  (Center.Z -> IR2, Center.Y -> IR3). A prop has no such swap -- its position at
  instance+0x10 is copied straight into the object matrix's translation slot at
  +0x14 (0x8001f874-0x8001f888) -- so prop vertices are ordered **(X, height,
  Z)**, matching their own position. Borrowing the chunk order tips every prop
  on its side and sinks it: measured over all 126 courses, prop bases then sit a
  median **7.9 units below** the nearest road against **0.8** with the right
  order. This is what reads as "the props are rotated wrong" -- the yaw is fine.

  **Props have no single fixed point at all -- the scale is PER SHAPE.** Each
  LOD ShapeData carries a power-of-two exponent as an s16 at **+0x54** (retail
  range 16..26, mode 22). The LOD setup reads it at 0x8001f998 and hands it to
  0x8007b800, which forms `4096 << (exp - 12)` as the matrix scale; the vertex
  scale works out as **2^(exp - 28)**.

  Two independent checks pin the base: it reproduces corrections measured by
  hand on real props (a shape with exp 21 wants 2x a flat 1/256, exp 22 wants
  4x), and it puts the median prop at **19.8 world units** tall beside a
  15-unit road with p90 at 60. The only 150+ outliers are the low-poly distant
  backdrops on Autumn Ring (274 x 859 from 133 vertices) and Tahiti.

  Any single global scale is wrong -- 1/64 makes the median prop 100 units and
  1/256 makes it 4 -- and a wrong global scale reads as props *floating*, since
  an oversized tall prop reaches proportionally too high.
  Retail totals: **6,083 instances, 0 without a resolvable LOD chain**, over
  5,577 LOD shapes / 138,730 primitives. Nine courses ship no props at all --
  every dev/test layout, plus the 2P and reverse variants of some real courses
  (2p_mountain has 0 where mountain has 41).

## TrackChunk roadway primitive encoding

Read statically out of the game's own renderer, not inferred from captures.

- **Where the code is.** `GT2.OVL` is a 6-entry TOC of gzip blobs
  (`overlay0, global, arcade, overlay3, gt, overlay5`). **All six load at
  0x80010000**, overlaying the first 0x4D5C0 bytes of the main EXE's address
  space; the resident EXE code begins at its entry point 0x8005D5C0. (Recovered
  by voting `jal` targets - absolute on MIPS - against function prologues:
  every overlay peaks at 0x80010000, and overlay0's size 0x4D5B4 lands exactly
  on 0x8005D5C0.) `overlay0` is the race overlay: 296 `lwc2`, 66 RTPS, 26 RTPT.
- **The chunk draw routine** is at 0x800210a8-0x80022c14 in overlay0, as eight
  unrolled loops - one per ShapeData list, each reading `listCounts[j]` at
  +0x30+2j and `listPtrs[j]` at +0x04+4j, and sizing the list by `count*stride`.
- **Vertex indices are FOUR 9-BIT FIELDS at bits 0, 9, 18 and 32:**

      lw   w0, 0(rec)  ;  lw  w1, 4(rec)
      sll  t, w0, 3    ;  andi t, t, 0xff8   ->  (w0        & 0x1FF) * 8
      sra  t, w0, 6    ;  andi t, t, 0xff8   -> ((w0 >>  9) & 0x1FF) * 8
      sra  t, w0, 0xf  ;  andi t, t, 0xff8   -> ((w0 >> 18) & 0x1FF) * 8
      sll  t, w1, 3    ;  andi t, t, 0xff8   ->  (w1        & 0x1FF) * 8  [quads]

  The `* 8` is the 8-byte vertex stride. This is neither the byte indices nor
  the 10-bit triple guessed earlier; it explains every previous partial reading
  - "byte 0 and byte 4 are indices" was the low 8 bits of index 0 and index 3,
  and the "UV bytes 1,2,5" were the middle of indices 1 and 2.
- **Validated on all 126 retail `.tro` files / 14,387 chunks / 699,229
  primitives: 100% of indices resolve inside the owning chunk's vertexCount**,
  and decoded primitives span 636 units on average versus 1,987 for random
  vertex quadruples drawn from the same pool.
- **Per-slot layout.** The list slot IS the primitive type. Strides measured
  unanimous across every chunk, and matched by each loop's own arithmetic:

  | slot | prim | stride | corners | lists seen |
  |------|------|--------|---------|------------|
  | 0 | F3  | 12 | 3 | 1,243 |
  | 1 | F4  | 12 | 4 | 4,696 |
  | 2 | G3  | 20 | 3 | 416 |
  | 3 | G4  | 24 | 4 | 1,330 |
  | 4 | FT3 | 12 | 3 | 8,678 |
  | 5 | FT4 | 12 | 4 | 13,208 |
  | 6 | GT3 | 20 | 3 | 780 |
  | 7 | GT4 | 24 | 4 | 3,984 |

  This **supersedes the earlier FT3/FT4 = 24, GT3 = 32, GT4 = 36 sizes.**

      bytes 0-3   w0: idx0 bits 0-8, idx1 bits 9-17, idx2 bits 18-26,
                      bits 27-28 select a 64-byte entry from a runtime table
                      (`srl v0,w0,0x15; andi v0,0xc0`), bits 29-31 flags
      bytes 4-7   w1: idx3 bits 0-8, texture-descriptor id bits 9-22,
                      bit 27 a flag (`lui 0x800; and`)
      bytes 8-10  RGB;  byte 11  PS1 primitive code
      bytes 12-14, 16-18, 20-22   further RGB triplets for gouraud corners 1..3
                                  (bytes 15/19/23 always zero)

- **UVs are not in the primitive record** - 12 bytes cannot hold four UV pairs.
  The renderer computes `((w1 >> 4) & 0x7FFE0)`, i.e. descriptor id
  `(w1 >> 9) & 0x3FFF` times 32 bytes, into a table whose pointer it reads from
  **TrackChunkTable+0x08** - the field previously logged as `UnkOffset`
  (`lw v0, 8(s3)` -> `sw v0, 0x3a0(scratch)`). Each 32-byte descriptor is two
  16-byte LOD entries:

      +0x00  u8 u0, v0 ; u16 clut       +0x08  u8 u2, v2, u3, v3
      +0x04  u8 u1, v1 ; u16 tpage      +0x0C  u16 lod_threshold ; u16 pad

  Entry 0 is full resolution; entry 1 is a half-size mip elsewhere in the same
  page (e.g. SSR5 descriptor 8 gives UVs (0,126)(0,0)(126,0)(126,126) in entry
  0 and the same tile at (128,128)-(190,190) in entry 1). The renderer picks on
  projected depth. Every descriptor id in all 126 files resolves inside its
  file; 92.3% of all primitives are textured and now carry UVs.
- **Corner order is NOT the index order** - read it off the `mtc2` sequence in
  each loop, because guessing it wrong is catastrophic and not obvious:
  - **Quads** load `V0<-i0+1`, i.e. V0<-i1, V1<-i2, V2<-i0, then RTPS the 4th
    index into V3. The outline V0,V1,V3,V2 = i1,i2,i3,i0, which as a cycle is
    simply **(0,1,2,3)**. Treating the record as a PS1 strip and using the
    textbook `(0,1,3,2)` makes **99.9% of quads self-intersecting bowties** -
    each rendering as a triangular hole plus a back-facing triangle, giving the
    whole course a checkerboard of holes.
  - **Triangles** load V0<-i0, V1<-i2, V2<-i1, i.e. wound *opposite* to the
    quads. GT2 compensates in its cull test - the quad loop does `negu` on the
    NCLIP result before checking it - so **the stored winding is not a
    consistent orientation cue** and cannot be used to orient a DCC mesh.
  - For one consistent convention the geometry decides it: with `(0,1,2)` for
    tris and `(0,1,2,3)` for quads, near-horizontal faces of every textured type
    point up across all 126 courses - FT3 97.5%, FT4 96.1%, GT3 98.2%,
    GT4 99.3%. (F3/G3 sit mostly downward either way; they are the untextured
    filler and underside polygons.)
  - No extra winding reversal is needed for the Blender X mirror: PS1 screen
    space is already Y-down, so that flip and the mirror cancel. Reversing as
    well turns the course inside out (up-facing road drops from ~95% to ~5%).

## Third geometry stream: billboard sprites

The trees. Every course came in with bare grass where GT2 has trees, bushes and
distant stand-ins, and the reason is that **ShapeData's `listPtrs` array does not
stop at eight**. Slots 8 and 9 sit at **+0x24 and +0x28 with their counts at
+0x40 and +0x42**, continuing the +0x04+4j / +0x30+2j pattern exactly; earlier
notes logged them as `unk24`, `unk28` and `count24` and left them alone.

**Slot 8 is a camera-facing billboard.** Both renderers build the same thing --
props at 0x8001f9e8, chunks at 0x80020434:

```
lhu  $v1, 0x40($s3)      ; count
lw   $t4, 0x24($s3)      ; list
ctc2 cos_cam, L11L12     ; L = [[c,0,0], [-s,0,0], [0,0,0]]
ctc2 -sin_cam, L13L21
mtc2 width, IR1
MVMVA                    ; mx=L, v=IR, cv=none, sf=1
-> IR1 = c*width>>12, IR2 = -s*width>>12
```

so the quad spans `centre ± (IR1, IR2)` horizontally on the camera yaw and rises
`height` from its base. It is emitted as a **9-word GP0 packet** (`lui $v0,
0x900`) and **all 16,954 retail records carry command byte 0x2C - POLY_FT4**,
which is the check that the strides below are right. Neither loop runs NCLIP, so
sprites are never back-face culled.

- **The width field is a FULL width, not a half-extent**, and the halving hides
  in the table it multiplies against. 0x80020228 stores the camera yaw as
  `sll 16; sra 17` - sign-extend, then shift right **one more** - so scratchpad
  0x3f0/0x3f2 hold **sin/2 and cos/2**, and the MVMVA returns width/2. Reading
  it as a half-extent draws every billboard at twice its size: across the 10,927
  chunk billboards the quad's aspect then runs a median **1.71x its own
  texture's aspect**, against **0.85x** the right way (p10 0.51, p90 1.35).
- **Chunk records are 16 bytes** (`sll $v0, $v0, 4` at 0x80020444), and take
  their UVs from the SHARED descriptor table - `srl $v0, $t1, 0x10;
  sll $v0, $v0, 5` reads the id from the high half of +0x04 and multiplies by 32
  into the pointer cached at scratchpad 0x3a0, i.e. TrackChunkTable+0x08:

      +0x00  s16 x ; s16 y            pool components 0 and 1
      +0x04  s16 z ; u16 texture_id   component 2 is the pool's height
      +0x08  u16 width ; u16 height
      +0x0C  u8 r, g, b ; u8 gp0_command

- **Prop records are 28 bytes** (count*28 at 0x8001f9f8) and carry their UVs
  inline, in the same 12-byte clut/tpage block a prop primitive uses:

      +0x00  s16 x ; s16 y            y is the height, as for LOD vertices
      +0x04  s16 z ; u16 flags         z is SIXTEEN bits -- see below
      +0x08  u16 width ; u16 height
      +0x0C  u8 r, g, b ; u8 gp0_command
      +0x10  u8 u0, v0 ; u16 clut
      +0x14  u8 u1, v1 ; u16 tpage
      +0x18  u8 u2, v2, u3, v3

- **The prop record's z at +0x04 is 16 bits, and the half above it is a flag,
  not padding.** The loop reads the pair with `lw $a3, -8($t2)` and pushes the
  result through `mtc2 ... VZ0/VZ1` - and VZ0 is an **S16** register, so the high
  half never reaches the GTE. It is tempting to read the field as a 32-bit z
  because the chunk record's equivalent slot holds `s16 z; u16 texture_id` and a
  prop needs no texture id there. But **253 of the 6,027 retail records (4.2%)
  carry exactly 1 in that high half**, and reading 32 bits adds 65536 to their z:
  roma_night's `gt2_prop_0028_lod047` then spans Y[-1940, 190] on a course only
  673 units deep, and billboards scatter across the sky far from any track.
  Measured over every prop billboard, distance outside its own shape's vertex
  pool separates the two readings by an order of magnitude - 16-bit gives p99
  38.5 and max 275.3 world units (Rome's night backdrop, flag 0), 32-bit gives
  p99 3,869.9 and max 8,110.8.
- **Corner order is the PS1 'Z': TL, TR, BL, BR.** Read off the packet writes --
  RTPT projects three corners into SXY0..2 and the stores put SXY1 in word 1,
  SXY0 in word 3, then after the RTPS SXY1 in word 5 and SXY2 in word 7 --
  pairing uv0 with the -width top corner, uv1 with +width top, uv2 with -width
  base, uv3 with +width base. As a polygon loop, TL, TR, BR, BL.
- Retail totals: **10,927 chunk billboards over 4,327 chunks and 6,027 prop
  billboards over 1,079 LOD shapes, 16,954 in all**, none out of bounds. Roma
  has the most (433 + 408); tahiti_t only 23, but they are the palms and the
  broadleaf on the main straight.
- **65 LOD shapes have vertexCount == 0 and a non-empty slot 8.** That is how GT2
  swaps a distant object for a single sprite, so a reader must not treat
  vertexCount == 0 as an empty shape - the old code returned None there.

## Slot 9, the lamp glare

The glowing orbs on night-track lamp posts. Same shape as slot 8 - pointer at
ShapeData+0x28, count at +0x42 - but this is the one stream GT2 does **not**
author as art: the loop at 0x800205ec (chunks) / 0x8001fba8 (props) builds the
whole flare procedurally around a single stored point.

    +0x00  s16 x ; s16 y        pool components 0 and 1
    +0x04  s16 z ; s16 size     component 2 is height; size is a depth-cue
                                coefficient, NOT a world radius
    +0x08  s16 nx, ny, nz       a unit vector, 4096 = 1.0
    +0x0E  s16 pad              always zero
    +0x10  u8 r, g, b ; u8 0    the lamp colour; the command byte is OR'd in at
                                runtime, so this byte is always zero

The renderer `mtc2`s the point, RTPS's it, and takes **MAC0** - the depth-cue
term, whose slope it sets with `ctc2 [+0x06], DQA` - as the on-screen radius.
It then emits **four 12-word `0x3E` (POLY_GT4, semi-transparent) packets at 45
degree steps** off the sine table at 0x80092ef8+0x200/0xa00, giving an eight
point star, each gouraud-shaded from the stored colour through **`c/2 -> c/8 ->
c/64`** (the `and 0xfefefe; srl 1` / `0xfcfcfc; srl 2` / `0xf8f8f8; srl 3` chain
at 0x8001fcb0). That ramp is the falloff, and it is recoverable even though the
sprite is not.

**The texture it samples exists in no file.** The UVs, CLUT (0x7f57) and TPAGE
(0x29) are constants in the code, and nothing in the entire volume uploads a TIM
into VRAM page 9 - not the course `.trp`, not `crstim.arc` (which is a sixth
`@(#)GT-` format, `@(#)GT-ARC`, holding six TIMs at pages 6 and 0), not
`.crstims.tsd`. The engine builds it at runtime. So a flare is imported as a
generated emissive orb: position, colour and relative size are real data, the
falloff follows the c/2 -> c/8 -> c/64 ramp, and the sprite is reconstructed.

Retail totals: **2,195 chunk records and 358 on LOD shapes, across 17 courses,
every one of them a night or evening layout** - roma_night 328, highway 250,
shortway 162, and zero on roma, autumn, tahiti_t and the rest. The sweep asserts
that night/evening correspondence against `.crsinfo`'s own flags rather than a
hand-written list of track names, which is what makes it evidence rather than a
label.

Because `size` is a perspective coefficient, its world scale is a choice, the
same way the skydome's radius is. Reading it in the pool's own 1/64 units and
halving puts the retail spread (38..299, median 213) at 0.3 to 2.3 world units
of radius beside a 15-unit road, and preserves the relative sizes the file does
store.

## Skybox: `bgsobj/*.bso` + `.bsp`

**A course's sky is not in its `.tro`.** Everything in the `.tro` was accounted
for before this - every texture page the `.trp` writes is sampled by track
geometry, none is left over - and the largest prop on every course is a flat
distant backdrop that does not enclose the track. The sky is a separate pair of
files in a sibling `bgsobj/` directory, split exactly the way `crsobj` splits
geometry from textures:

- **`<name>.bsp` is byte-for-byte a `.trp`** - `u32 count` then TIM-family
  images with their own VRAM destinations. All 34 decode with the unmodified
  `.trp` reader.
- **`<name>.bso` is the `.tro`'s ShapeData with a different header:**

      +0x00  char magic[4] "BG\0\0"
      +0x04  u8 r, g, b ; u8 0x28      background colour A
      +0x08  u8 r, g, b ; u8 0x28      background colour B
      +0x0C  u32 vertexCount
      +0x10  u16 listCounts[8]         F3 F4 G3 G4 FT3 FT4 GT3 GT4 -- the same
                                       eight slots, in the same order, as a
                                       TrackChunk's ShapeData
      +0x20  vertexCount x 8 bytes     s16 x, y, z, pad -- the .tro vertex format
      then   the eight primitive lists, in slot order

  The two colour words are finished GPU colour words - RGB then the POLY_F4
  command byte `0x28` - i.e. ready-made background fills. That is the other half
  of the picture: **the mesh is only the horizon band**, and the flat sky above
  it is those colours. `dawn` (Special Stage Route 5) has both set to black,
  which is why SSR5's sky is black.

Two things differ from the roadway, and both come from the console:

- **Each record is 8 index bytes followed by TWO copies of `[u32 OT tag][the
  packet]`** - one packet per double-buffered frame. So the stride is
  `8 + 2*(4 + words*4)`: F3 48, F4 56, G3 64, G4 80, FT3 72, FT4 88, GT3 80,
  GT4 112. Pinned twice over: **all 34 retail skies parse to exact EOF**, and
  **every record's stored OT tag word count equals the word count its own GP0
  command implies** (0 disagreements over 5,292 primitives).
- **Indices are four 12-bit fields** at bits 0-11 and 12-23 of each of the two
  words - wider than the roadway's 9 and the props' 10, and they need to be:
  `t_sky` alone has 640 vertices. 0 of 5,292 primitives index outside their own
  file's pool.

**Corner order is NOT the roadway's.** A `.bso` stores literal packet operands,
so its indices fill xy0..xy3 in order and quads are the console's Z-order
(TL, TR, BL, BR) - polygon loop `(0,1,3,2)`. Measured over all 4,458 retail sky
quads: **0.07% self-intersect that way against 99.98%** with the roadway's
`(0,1,2,3)`.

**Axis mapping follows the roadway, not the props.** Sky vertices are ordered
(X, height, Z) like a prop's, but a skybox is drawn on the camera's rotation with
no object matrix of its own, so it has to agree with the world the chunks define:
`(x, y, z) -> (-x, z, y)`. That is a proper rotation (determinant +1), so the
stored winding carries straight over - unlike the props' `(-x, -z, y)`, which is
a mirror and needs its winding reversed.

**There is no true world scale.** A skybox is drawn with the camera's rotation
and its translation dropped, so every uniform scale renders identically and only
each vertex's direction carries information. The importer scales the dome to a
chosen world radius (default 1500, which clears SSR5's 1,326-unit span).

Which sky a course uses is in **`.crsinfo`** at the volume root:

    char magic[4] "CRS\0"; u16 version(2); u16 courseCount;
    courseCount x 24 bytes:
      +0x00  u32 displayNameOffset   into the string table that follows
      +0x04  u32 courseId            hash of the crsobj filename, below
      +0x08  u8  flags               bit0 night, 1 evening, 2 dirt,
                                     3 two-player, 4 reverse, 5 point-to-point
      +0x09  u8  pad
      +0x0A  u16 skybox              index into the 34-name table
      +0x0C  3 x { u16 colour; u16 multiplier }    lighting areas
    then null-terminated display names to EOF

`courseId` is GT2's own name hash - rotate the accumulator left 6, add each
ASCII byte - and it resolves **all 126 `crsobj` filenames with nothing left
over**.

**The skybox index is a position in `GT2.VOL`'s own directory listing, and that
listing is ASCII-sorted.** The 34 names appear nowhere in the executable or the
overlays - `/bgsobj` is in the EXE's path table as a bare directory and nothing
else - so the only place the order exists is the volume directory block, at
0xB1A7 in the retail `GT2.VOL`. In ASCII `_` is 0x5F, below every lowercase
letter, so `roma_sh` sorts before `romadark_sky`, `sea_ha_b` before `sea_hare`,
and `t_sky` before `tesr_l2sky`. Plain `sorted()` reproduces the table exactly.

This is worth stating loudly because **the widely-circulated community list is
the same 34 names sorted the way Windows Explorer sorts them**, which ignores the
underscore. The two agree for indices 0..15 and diverge from 16 on, so a course
importer using it looks correct on most tracks and quietly wrong on the rest:
Tahiti Road comes out under `tesr_l2sky`'s green mountains instead of `t_sky`'s
ocean and cloud band, Rome-Night under `roma_sh_sky` instead of `romadark_sky`.
Every name reads sensibly once the order is right - `t_sky` for Tahiti,
`tesr_l2sky` for the `test_l2` layout, `romadark_sky` for Rome-Night. The
regression sweep pins the table three ways: it must be ASCII-sorted, it must
equal the order read live out of `GT2.VOL` when that file is reachable, and four
unambiguous course-to-sky pairs must hold.

`speedsky` is the most used (13 courses) and Special Stage Route 5 uses `dawn`,
whose two background colours are black - which is why its sky is black. Eleven
of the 34 are never referenced by any retail course.

## Which prop groups a course actually draws

The 33 `InstancedObjectOffsets` groups are not all live at once. The dispatcher
at 0x8002002c walks groups 0..31 and draws each **only if the matching bit is set
in the 32-bit mask handed to it in `$a2`** (`andi $v0, $s2, 1` /
`srl $s2, $s2, 1`), then draws group 32 unconditionally. That mask is the return
value of the chunk-draw pass at 0x80020110, which ORs together **`lw $v0,
0xc($a1)` - a group bitmask stored on every TrackChunk at +0x0C** - over the
chunks it has just found visible.

So a prop group is on screen only while a chunk that requests it is, and a group
no chunk ever names is dead data. Across the retail set exactly one course has
such a group: **lagunareverse populates 6, 8, 9, 10 and 11 and requests none of
them.** This is the check to run before concluding that an oddly placed prop is
an importer bug - on SSR5 instance 17 (group 0, LOD 31, a PIT gantry) sits 139
units above the road at essentially the world origin, and group 0 IS requested,
by 52 of the course's 194 chunks. The record is well formed and its single LOD
level has a ~700-unit draw radius, so the game would draw it up there.

**It is dev debris, and the sibling layouts prove it.** Fingerprinting that
shape (40 verts, 18 primitives) across all 126 courses finds it on exactly five,
in two states:

| course        | instance | world position          | height above road |
|---------------|----------|-------------------------|-------------------|
| shortway      | 12       | (-7.0,  1.9,  -0.0)     | -1.1              |
| Rshortway     | 12       | (-7.0,  1.9,  -0.0)     | -1.3              |
| 2p_shortway   | 7        | (-7.0,  1.9,  -0.0)     | -1.1              |
| highway       | 17       | (-5.2,  1.7, 140.4)     | **+139.1**        |
| 2p_highway    | 7        | (-5.2,  1.7, 140.4)     | **+139.1**        |

Same gantry, same spot on the ground plane, correctly planted on all three
Clubman Stage Route 5 layouts and lifted 140 units on both full SSR5 layouts.
Clubman's pit entry is where that sign belongs; on the long route the developers
raised it out of shot instead of deleting it, and SSR5 carries no second copy of
the mesh (its own pit signage is a different shape). Video of SSR5 shows nothing
there, which agrees. **So: correctly decoded, correctly placed, and correctly
invisible in practice - nothing for an importer to fix.**

This is a useful general technique for the format: hash a LOD shape's vertex
pool and primitive lists, then look for the same hash across the retail set. The
2P and reverse variants of a course are near-duplicates of it, so a prop that
looks wrong on one and right on its sibling is a data quirk, not a decode bug.

## Chunk world placement

Also read out of the renderer. `0x80026bb4` is called once per visible chunk
(from 0x800203f4, `$a0` = chunk pointer, `$a1` = 0x1F800000 = the scratchpad
camera block) immediately before the draw, and it is the only place the GTE
translation is set for the roadway:

```
lui  $s2, 0xffc0            ; MASK = 0xFFC00000
lw   $s5, 0x30($a0)         ; chunk Center.X   (+0x30, 16.16, absolute)
and  $v0, $s5, $s2          ; Center & MASK
addu $v0, $fp, $v0          ; + camera  ([0x1F800020..28], negated)
sra  $a1, $v0, 0xa          ; >> 10
...                          ; same for Y and Z
mtc2 $a1, IR1 ; mtc2 $v1, IR2 ; mtc2 $a2, IR3
MVMVA                        ; rotate by the camera matrix
ctc2 ... TRX / TRY / TRZ
```

So, dropping the camera term, the chunk's pool origin is

    origin = (Center & 0xFFC00000) >> 10        # in the pool's own 1/64 units

- The **mask snaps the origin to a 2^22 (16.16) grid = 64 world units**, and the
  pool stores the remainder. That is why every chunk's pool sits in the same
  small coordinate box (pool-centroid stdev 1,199 raw across SSR5's 194 chunks
  versus 26,176 for the track itself), and why chunk-to-chunk vertex deltas kept
  coming out modulo 4096 (= 64 world units in pool scale).
- The **`>> 10` is the unit conversion**: 16.16 world / 1024 is exactly the
  pool's 1/64-world-unit scale. It is not a per-chunk scale factor.
- **The pool is ordered (X, Z, Y) while Center is (X, Y, Z)** - the swap is
  visible in the `mtc2` order above (`$v1`, from Center.Z, goes to IR2; `$a2`,
  from Center.Y, to IR3). Pairing them straight through leaves **18.5%** of
  chunks a whole grid cell out of place; pairing pool component 1 with Center.Z
  and component 2 with Center.Y leaves **1.6%** (measured over
  highway + roma + seattle, 496 consecutive-chunk steps).
- There is **no per-chunk rotation**. The GTE rotation comes from the camera
  matrix at 0x1F800000, copied and left-shifted for precision by `0x80081994`
  (nine `sllv`s, no chunk input); the whole chunk-draw range 0x8002106c-
  0x80022c14 contains zero `ctc2`. Independently: sweeping every 2-byte chunk
  header field against the track heading gives a best circular correlation of
  R = 0.28, i.e. no stored yaw exists.

## The Euro Demo 53 build

The GT2 demo on Euro Demo 53 ships 48 courses in the same `.tro` version
(0x001F0000) and decodes with the retail code unchanged: **0 out-of-range
indices over 321,506 primitives**, props still 10-bit (0% out of range against
73% for 9-bit, on 31,186 prop primitives), skyboxes and `.crsinfo` the same
formats. Its chunk decoder is byte-for-byte retail's -- the same
`sll 3 / sra 6 / sra 15` feeding `andi 0xff8` -- so the same four 9-bit indices.

Two things differ and one is a trap:

- **The skybox name table is per-build, not a constant.** The demo ships 25
  skies where retail ships 34, so retail's list mis-resolves nearly every demo
  course (the demo's `highway` wants index 2, which is `dawn` there and
  `circle30sky` in retail). The index is a position in that build's own VOL
  directory listing, which is ASCII-sorted, so the fix is to list the `bgsobj`
  directory that is actually present -- `sky_names_for()`. Verified against the
  demo `GT2.VOL`'s directory block as well as retail's.
- The demo's `overlay0` contains **no 10-bit mask at all**, so its LOD prop
  renderer lives elsewhere in the build; the prop DATA is still 10-bit, which is
  what matters for reading it.

### `seattle2000`: unreachable geometry, and it is the file, not the reader

`seattle2000` is a GT2000 leftover and the only course in either build that
breaks the format's own addressing rule. A chunk's primitives index its vertex
pool with **nine bits**, so a pool longer than 512 has vertices nothing can
reach. Retail respects that on all 14,387 of its chunks and so do 47 of the
demo's 48 courses. `seattle2000` has **22 chunks over the limit, up to 1,010
vertices, 3,825 unreachable in total**.

The consequences are visible: those chunks reference **exactly** vertices 0..511
and no more, their pool coverage sits at a median 77% against 100% everywhere
else, and the grandstand in chunk 89 imports as a coherent lower tier with a
shredded roof.

It is not a decode error. Three independent checks say so:
- The demo's own chunk decoder is byte-identical to retail's 9-bit one, so the
  game cannot reach those vertices either.
- 10-bit indices fail badly on the same chunks -- 61% out of range against 0%,
  and median primitive span 1,627 raw against 144.
- Every other chunk in the same file, and every chunk in the other 47 courses,
  decodes to 100% pool coverage.

## Textures: a texture's extent is not recorded, but it is recoverable

A `.tro` never says where one texture ends and the next begins. Per face it
stores a texture page, a palette and the texel coordinates of the corners --
all the console needs, because it draws out of VRAM directly.

The extents come back out of the UVs. A face's corners bound the texture it
samples, and two faces sharing a texture make boxes that overlap, so unioning
overlapping boxes per (page, palette) reassembles them:

| course | (page, palette) pairs | distinct per-face boxes | recovered textures | texels |
| --- | --- | --- | --- | --- |
| `seattle` | 167 | 2,338 | 168 | 484,085 |
| `parma` | 121 | 1,338 | 129 | 491,572 |
| `l_mid2` (Midfield) | 117 | 1,076 | 124 | 479,036 |
| median of 126 | 71 | -- | 74 | -- |

**Across all 126 courses, zero recovered textures cover a full 256x256 page**,
which is the check that matters: an over-merging rule would collapse each page
to one block and the texture count would land on the pair count instead.

The same two rules as GT1 apply, for the same reasons. The palette is part of
a texture's identity, so the key is always (page, palette) -- the same 4-bit
indices through a different CLUT are a different image. And pages do not
overlap in VRAM: a tpage's X base is `(tpage & 0xF) * 64` halfwords and a
4-bit page is 64 halfwords wide, so they tile exactly, and the duplicates that
do turn up are two palettes holding the same colours, merged by content hash.

The skydome is grouped separately because it has its own texture container
(`.bsp`, not the course's `.trp`) -- packing the two together would put
textures from two unrelated VRAM images into one atlas for no gain.

### Equivalence

The modes differ only in where the texels live, so the test is whether a face
still reads the same texels. Building `circuit`, `seattle` and `parma` three
times each and sampling every textured mesh loop's UV out of its own material's
image: **129,546 loops, 0 differences**. The 126-course sweep additionally
checks that no textured face falls back to a page material, which is how an
unrecovered texture would show up. See `GT2/test_gt2_textures.py`.

### The renders differ on a handful of pixels, and it is not a mapping error

Sampling at the corners is exact, but the rasteriser interpolates in NORMALISED
UV space and only then multiplies by the image width -- and a page and an atlas
do not have the same width. At a texel boundary the two normalisations can round
to different texels. Rendering `seattle` identically in both modes: 2,790 of
1,140,000 pixels differ at all, and **17 by more than 5/255** (worst 23), on
distant surfaces where a texel is about a pixel wide. `circuit` has none above 5,
and individual textures are cleaner still (max 1/255 on `seattle`).

Three explanations were tested and ruled out, rather than assumed:

* **Not minification or mip bleed.** Rendering at 3x resolution does not reduce
  it.
* **Not the atlas collapsing 143 materials into one** and changing EEVEE's
  alpha dithering. Disabling alpha entirely leaves the same 17 pixels.
* **Not edge bleed between packed tiles.** A one-texel replicated gutter around
  every tile changes the worst case not at all -- 23/255 either way -- because a
  rasterised pixel interpolates within the face's corner bounding box and
  therefore cannot leave its own tile. The gutter was measured and then removed
  rather than kept because it sounded prudent.


## Importer trap: face/attribute alignment

Not a format finding, but the single nastiest bug in this decode, and worth
recording because it *looks* like a format bug.

UVs, corner colours and material indices are assigned to `mesh.polygons[i]`
positionally. Calling Blender's `mesh.validate()` before assigning them deletes
faces and silently shifts everything after -- so a chunk renders with textures
on the wrong faces and UVs that look scrambled. It fired on **18 of highway's
194 chunks and 40 of roma's 179**.

Of 699,229 chunk primitives, `validate()` removes two kinds:
- **150** repeat a vertex inside the face. Genuinely invalid; drop them. (A test
  of `len(set(idx)) < 3` is not enough -- it lets quads like `(a,b,c,a)` past.)
- **4,704** exactly duplicate an earlier face. **4,006** also repeat its texture
  and are pure redundancy. The other **698 carry a different texture on the same
  four corners: they are the decals GT2 layers onto the road**, they are real,
  and deleting them both loses detail and leaves the face underneath showing.

So: filter the primitives yourself, then build, then assign, and never let
`validate()` run in between. `usable_prims()` does the filtering and the
importer asserts `len(mesh.polygons) == len(faces)` before touching attributes.

Related, and settled by measurement rather than by reading the packet layout:
the descriptor's UVs and the gouraud corner colours are stored in **index
order**, matching `indices[0..3]` directly, even though the packet's screen
coordinates are permuted (`V0<-i1` and so on). Applying the packet permutation
to the attributes as well takes self-intersecting UV quads from **0.24% to
99.6%** -- which on screen reads as smeared road textures and faces that look
like they were handed someone else's texture.

## Importer trap: UVs address texel CENTRES

The second one of these, and it looks like a texture bug rather than a mapping
one. PS1 UVs are integer texel indices, so texel row 0 is the top row of the
page. Mapping it to the corner `V = 1.0` puts the sample exactly on the wrap
seam, and Blender's REPEAT extension sends `V = 1.0` to `V = 0.0` - the BOTTOM
row, an unrelated part of the page.

**126,235 of the retail set's 645,613 textured chunk faces have at least one
corner at v = 0**, and the **57 whose corners are ALL at v = 0** render entirely
from the wrong row. Map to centres instead:

    u_blender = (u + 0.5) / 256
    v_blender = 1.0 - (v + 0.5) / 256

which is also what point sampling wants: PS1 samples texel `floor(u)`, and the
centre lands unambiguously inside it.

## Not a bug: collapsed UV islands

Worth recording, because it looks exactly like a decode failure. Across the
retail set **1,020 chunk faces have all four UVs sharing one u or one v, and 255
have all four identical.** Their descriptors are valid and deliberate - id 25 on
2p_autumn is `40 ef 6a 7c 40 ef 0f 00 40 ef 40 ef`, i.e. the texel (64, 239)
repeated four times - and where a descriptor has a second LOD entry it is
collapsed the same way. GT2 stretches a single texel, or a single texel line,
across a face as a cheap flat colour or gradient band. In a UV editor those
islands show as a dot or a hairline. They are supposed to.

## Container structure

Every offset below is one the importer actually computes, or a
neighbour whose position is pinned by one that is; *What the importer reads*
at the end of the section says which is which, because a declared field is not
the same as a decoded one.

All values are little-endian. Fields named `unk_*` are unidentified: their
sizes are fixed by the offsets of their neighbours, not by anything known about
their contents.

**Pointer remap.** Every pointer stored in a `.tro` is a runtime address, not a
file offset:

    file_offset = stored_pointer - start_pos
    start_pos   = header.instanced_object_offsets[0] - 0x19C

`0x19C` is `sizeof(tro_header_t)`, so instance group 0's record list begins
immediately after the header — which is what makes that subtraction work.
Loose extracted files give `start_pos == 0`.

```c
typedef struct { int32_t x, y, z; } vec3_t;   /* 16.16 fixed unless noted */
typedef struct { int16_t x, y;    } sector_t;

/* ==========================================================================
 * FILE HEADER                                            0x000, size 0x19C
 * ========================================================================== */
typedef struct {
/* 0x000 */ char     magic[12];              /* "@(#)GT-PS", NUL-padded      */
/* 0x00C */ int32_t  version;                /* GT2 0x001F0000 (GT1 0x001C0000,
                                              * Jul-97 GT1 prototype 0x001A0000) */
/* 0x010 */ uint32_t track_chunk_table_ptr;  /* -> tro_chunk_table_t         */
/* 0x014 */ uint32_t lod_lookup_table_ptr;   /* -> tro_lod_lookup_t          */
/* 0x018 */ uint32_t lod_data_ptr;
/* 0x01C */ uint32_t unk_ptr_1c;
/* 0x020 */ uint32_t unk_ptr_20;
/* 0x024 */ int32_t  sector_count;
/* 0x028 */ sector_t sectors[8];
/* 0x048 */ vec3_t   origin;
/* 0x054 */ int16_t  start_position_direction;
/* 0x056 */ int16_t  unk_56;
/* 0x058 */ vec3_t   start_positions[16];
/* 0x118 */ uint32_t instanced_object_offsets[33];  /* -> tro_instance_group_t,
                                                     * one per prop group     */
} tro_header_t;                                     /* 0x19C                  */

/* ==========================================================================
 * INSTANCE GROUPS -- where the props are placed
 * 33 independent lists. A chunk names the groups it wants through its own
 * instance_group_mask; see tro_chunk_t.
 * ========================================================================== */
typedef struct {
/* 0x00 */ int16_t flags;
/* 0x02 */ int16_t yaw;               /* 4096 = one full turn                 */
/* 0x04 */ int16_t unk_04;
/* 0x06 */ int16_t lod_lookup_index;  /* index into tro_lod_lookup_t          */
/* 0x08 */ int16_t scale_x;           /* 4096 = 1.0                           */
/* 0x0A */ int16_t scale_y;
/* 0x0C */ int16_t scale_z;
/* 0x0E */ int16_t scale_w;
/* 0x10 */ int32_t pos_x;             /* 16.16 world; ordered (x, height, z)  */
/* 0x14 */ int32_t pos_y;
/* 0x18 */ int32_t pos_z;
} tro_instance_t;                     /* 0x1C                                 */

typedef struct {
/* 0x00 */ int32_t        count;
/* 0x04 */ tro_instance_t records[/* count */];
} tro_instance_group_t;

/* ==========================================================================
 * LOD LOOKUP -- header.lod_lookup_table_ptr
 * An instance names a chain; the chain lists that prop's detail levels.
 * ========================================================================== */
typedef struct {
/* 0x00 */ uint32_t max_distance;
/* 0x04 */ uint32_t shape_data_ptr;    /* -> tro_lod_shape_data_t             */
} tro_lod_level_t;

typedef struct {
/* 0x00 */ uint32_t        level_count;
/* 0x04 */ tro_lod_level_t levels[/* level_count */];   /* level 0 = nearest  */
} tro_lod_chain_t;

typedef struct {
/* 0x00 */ uint32_t chain_count;
/* 0x04 */ uint32_t chain_ptrs[/* chain_count */];      /* -> tro_lod_chain_t */
} tro_lod_lookup_t;

/* ==========================================================================
 * TRACK CHUNK TABLE -- header.track_chunk_table_ptr
 * ========================================================================== */
typedef struct {
/* 0x00 */ int16_t  unk_00;
/* 0x02 */ int16_t  v_coord_finish;
/* 0x04 */ int16_t  chunk_count;
/* 0x06 */ int16_t  unk_count;
/* 0x08 */ uint32_t texture_descriptor_table_ptr;  /* -> tro_tex_descriptor_t[]
/* 0x0C */ uint32_t chunk_ptrs[/* chunk_count */]; /* -> tro_chunk_t            */
} tro_chunk_table_t;

/* ==========================================================================
 * TRACK CHUNK -- one drivable segment of roadway
 * ========================================================================== */
typedef struct {
/* 0x00 */ uint16_t prev_index;
/* 0x02 */ uint16_t next_index;
/* 0x04 */ uint32_t prev_ptr;
/* 0x08 */ uint32_t next_ptr;
/* 0x0C */ uint32_t instance_group_mask;  /* bit g set = this chunk asks for
                                           * instance group g to be drawn      */
/* 0x10 */ uint8_t  unk_10[8];
/* 0x18 */ vec3_t   start_position;       /* 16.16 world. The chunk's START, a
                                           * half-chunk behind center; NOT the
                                           * field the renderer places with. */
/* 0x24 */ uint8_t  unk_24[12];
/* 0x30 */ vec3_t   center;               /* 16.16 world, absolute. THIS is the
                                           * placement field, and the LOD
                                           * distance test uses it too         */
/* 0x3C */ int32_t  unk_positional[22];   /* 0x3C..0x93                        */
/* 0x94 */ uint32_t shape_data_2_ptr;     /* the low-detail second ShapeData   */
/* 0x98 */ uint32_t boundary_collision_ptr;
/* 0x9C */ uint32_t unk_ptr_9c;
/* 0xA0 */ uint32_t unk_ptr_a0;
/* 0xA4 */ tro_shape_data_t shape;        /* the roadway geometry              */
} tro_chunk_t;

/* The four sections that follow `shape` are laid out back to back, and a chunk
 * is walked rather than sized from a stored length:
 *
 *     tro_shape_data_t  shape_1;           at +0xA4
 *     tro_shape_data_t  shape_2;           the low-detail copy
 *     struct { uint32_t count; uint8_t items[count][8]; }        list;
 *     struct { uint16_t hdr[4], counts[16]; uint32_t ptrs[16],
 *              items[sum(counts)]; }       groupings;  104 + 4*sum bytes
 *     struct { uint16_t count, chunk[count]; }  visibility;  padded to 4
 *
 * then the next chunk begins. Exact on all 14,261 GT2 chunks when checked
 * against GT2's own stored pointers -- the walk is implemented in `gt1.py`
 * (`chunk_sections`, `shapedata_size`), which shares this container.
 */

/* ==========================================================================
 * SHAPE DATA -- the geometry block, shared by chunks, props and (reshaped)
 * skyboxes. Header is 0x44 bytes; the pool and lists are reached by pointer.
 * ========================================================================== */
typedef struct {
/* 0x00 */ uint32_t vertex_ptr;        /* -> tro_vertex_t[vertex_count]       */
/* 0x04 */ uint32_t list_ptrs[10];     /* [0..7] solid, [8] sprites,
                                        * [9] lamp glare                      */
/* 0x2C */ int32_t  vertex_count;
/* 0x30 */ uint16_t list_counts[8];    /* solid slots, matching list_ptrs[0..7]*/
/* 0x40 */ uint16_t sprite_count;      /* == list_counts[8]                   */
/* 0x42 */ uint16_t glare_count;       /* == list_counts[9]                   */
} tro_shape_data_t;                    /* 0x44                                */

/* A prop's ShapeData carries more fields past the common header. The two
 * eight-byte slots at +0x44 and +0x4C are unidentified -- see the note at the
 * end of this section; the previous text called them vec3 bounds, which does
 * not fit the offsets.                                                       */
typedef struct {
/* 0x00 */ tro_shape_data_t common;
/* 0x44 */ int16_t unk_44[4];          /* UNIDENTIFIED                        */
/* 0x4C */ int16_t unk_4c[4];          /* UNIDENTIFIED                        */
/* 0x54 */ int16_t scale_exponent;     /* world units per raw unit = 2^(e-28);
                                        * retail range 16..26                 */
/* 0x56 */ int16_t unk_56;
} tro_lod_shape_data_t;                /* 0x58                                */

typedef struct {
/* 0x00 */ int16_t x, y, z;
/* 0x06 */ int16_t pad;                /* always 0                            */
} tro_vertex_t;                        /* 8 -- the stride is confirmed by
                                        * (next_ptr - vertex_ptr)/vertex_count
                                        * == 8 on all 13,209 chunks with a pool */

/* ==========================================================================
 * PRIMITIVES
 * The list SLOT selects the primitive type outright -- lists are homogeneous.
 * Record strides, by slot:
 *
 *   slot  type    gp0   chunk  prop      A chunk record reaches its UVs
 *   ----  ------  ----  -----  ----      through the shared descriptor
 *    0    F3      0x20    12     12      table; a prop carries the same
 *    1    F4      0x28    12     12      12-byte UV block inline instead,
 *    2    G3      0x30    20     20      which is the whole reason its
 *    3    G4      0x38    24     24      records are wider.
 *    4    FT3     0x24    12     24
 *    5    FT4     0x2C    12     24
 *    6    GT3     0x34    20     32
 *    7    GT4     0x3C    24     36
 *    8    SPRITE  0x2C    16     28
 *    9    GLARE   0x3E    20     20
 * ========================================================================== */
typedef struct {
/* 0x00 */ uint32_t w0;   /* index_0    bits  0..8    (9-bit, chunk stream)
                           * index_1    bits  9..17
                           * index_2    bits 18..26
                           * bits 27..28  select a 64-byte entry from a table
                           *              built at runtime
                           * bits 29..31  flags                               */
/* 0x04 */ uint32_t w1;   /* index_3    bits  0..8    (quads only)
                           * descriptor bits  9..22   14-bit id into the
                           *              texture descriptor table
                           * bit  27      flag                                */
/* 0x08 */ uint8_t  r, g, b;   /* corner 0 for gouraud, the whole face if not */
/* 0x0B */ uint8_t  gp0_command;   /* the gp0 code from the table above       */
/* 0x0C */ /* gouraud only: corners 1..3 as { uint8_t r, g, b; uint8_t pad; }
            * at +0x0C, +0x10 and +0x14. The pad byte is always zero.
            * textured PROP records instead carry the 12-byte UV block here,
            * and push their gouraud corners to +0x18.                        */
} tro_prim_t;

/* A prop uses the same record with WIDER indices: three 10-bit fields at w0
 * bits 0..9, 10..19 and 20..29, plus a fourth at w1 bits 0..9. Reading a prop
 * with the chunk's 9-bit fields resolves only 23% of indices; the 10-bit
 * reading resolves 100% of 140,348 prop primitives across all 126 courses.  */

/* ==========================================================================
 * TEXTURE DESCRIPTORS -- chunk_table.texture_descriptor_table_ptr
 * Chunk primitives do not store UVs: 12 bytes cannot hold four UV pairs. The
 * renderer indexes this table by the record's 14-bit descriptor id.
 * Each descriptor is TWO 16-byte mip entries; entry 0 is full resolution and
 * entry 1 a half-size copy elsewhere in the same page. The importer uses 0.
 * ========================================================================== */
typedef struct {
/* 0x00 */ uint8_t  u0, v0;
/* 0x02 */ uint16_t clut;
/* 0x04 */ uint8_t  u1, v1;
/* 0x06 */ uint16_t tpage;
/* 0x08 */ uint8_t  u2, v2, u3, v3;
/* 0x0C */ uint16_t lod_threshold;
/* 0x0E */ uint16_t pad;
} tro_tex_entry_t;                       /* 0x10 */

typedef struct {
/* 0x00 */ tro_tex_entry_t entries[2];   /* [0] full res, [1] half res */
} tro_tex_descriptor_t;                  /* 0x20 */

/* ==========================================================================
 * SLOT 8 -- BILLBOARD SPRITES (trees, bushes, distant stand-ins)
 * A vertical quad that yaws to face the camera: it spans
 * centre +- (width/2) * (cos, sin) horizontally and rises `height` from its
 * base. Every retail record's gp0_command is 0x2C (POLY_FT4), and neither
 * renderer back-face culls them.
 * ========================================================================== */
typedef struct {                    /* chunk stream, stride 0x10 */
/* 0x00 */ int16_t  x, y;           /* pool components 0 and 1              */
/* 0x04 */ int16_t  z;              /* component 2 -- the pool's height     */
/* 0x06 */ uint16_t texture_id;     /* into the shared descriptor table     */
/* 0x08 */ uint16_t width;          /* FULL horizontal extent               */
/* 0x0A */ uint16_t height;
/* 0x0C */ uint8_t  r, g, b;
/* 0x0F */ uint8_t  gp0_command;    /* 0x2C on every retail record          */
} tro_chunk_sprite_t;               /* 0x10 */

typedef struct {                    /* prop stream, stride 0x1C */
/* 0x00 */ int16_t  x, y;           /* y is the height, as for prop vertices */
/* 0x04 */ int16_t  z;
/* 0x06 */ uint16_t flags;          /* where the chunk record keeps its id   */
/* 0x08 */ uint16_t width, height;
/* 0x0C */ uint8_t  r, g, b;
/* 0x0F */ uint8_t  gp0_command;
/* 0x10 */ uint8_t  u0, v0;         /* the same 12-byte UV block a prop      */
/* 0x12 */ uint16_t clut;           /* primitive carries, in the same order  */
/* 0x14 */ uint8_t  u1, v1;
/* 0x16 */ uint16_t tpage;
/* 0x18 */ uint8_t  u2, v2, u3, v3;
} tro_lod_sprite_t;                 /* 0x1C */

/* ==========================================================================
 * SLOT 9 -- LAMP GLARE. Identical on both streams. Not track art: the loop
 * halves and quarters the colour into 0x3E-command packets with hard-coded
 * UVs and 45-degree sine-table offsets, i.e. it is generated at runtime and
 * the sprite exists in no file. Only the 17 night and evening courses have any.
 * ========================================================================== */
typedef struct {
/* 0x00 */ int16_t x, y;
/* 0x04 */ int16_t z;
/* 0x06 */ int16_t size;            /* depth-cue coefficient, retail 38..299 */
/* 0x08 */ int16_t dir_x, dir_y, dir_z;   /* unit vector * 4096              */
/* 0x0E */ int16_t unk_0e;
/* 0x10 */ uint8_t r, g, b;
/* 0x13 */ uint8_t unk_13;
} tro_glare_t;                      /* 0x14 */
```

### What the importer reads

Decoded and used: `version`, `track_chunk_table_ptr`, `lod_lookup_table_ptr`,
`instanced_object_offsets`, the whole of `tro_chunk_table_t`, a chunk's
`prev_index`/`next_index`/`instance_group_mask`/`start_position`/`center`, both
ShapeData headers, the vertex pool, all ten lists, the descriptor table, and
every field of `tro_instance_t`, `tro_lod_level_t`, the sprite records and
`tro_glare_t`.

Declared but never read: `lod_data_ptr`, `unk_ptr_1c`, `unk_ptr_20`,
`sector_count`, `sectors`, `origin`, `start_position_direction`,
`start_positions`, the chunk's four trailer pointers at +0x94..+0xA0, and
`unk_positional`.

## Coordinate frames (empirical)
- Instances / LOD locals: raw (x,y,z) -> Blender (-x, z, y) [Y-up source];
  LOD local scale 1/256, instance world 16.16.
- Chunk world position: 16.16 (/65536) -> Blender (-x, z, y).
- Chunk LOCAL verts: raw (x,y,z) -> Blender (-x, y, z), scale 1/64 (matches
  chunk-to-chunk spacing: highway spacing ~35.4 units = 2270 raw /64).
- X mirrored (GT2 handedness); winding reversed to compensate.

## `.trp` textures - decoded and bound
`.trp` = `u32 count`, then that many sequential TIM-family images. All **14,138
images across all 126 courses are 4-bit CLUT (pmode 0)**, and every file parses
to exact EOF. Each image carries its own destination VRAM coordinates, so
replaying the whole file into a single **512 x 1024 halfword PS1 VRAM** image
reconstructs the texture memory that the primitives' `tpage`/`clut` fields
address.

Addressing, as the GPU does it:
- `tpage` bits 0-3 = page X base in 64-halfword steps, bit 4 = Y base in
  256-row steps, bits 7-8 = colour mode (always 0 / 4-bit for track data).
- `clut` bits 0-5 = palette X in 16-halfword steps, bits 6-14 = palette row.
- A 4-bit page is 64 halfwords x 256 rows = 256 x 256 pixels; UVs are 0-255.
- A palette entry of `0x0000` is **fully transparent** - that is how GT2 cuts
  out tree, fence and sign sprites.

**100% of textured primitives on every course resolve to a page and CLUT that
the `.trp` actually loaded**, which is the check that the whole chain - chunk
descriptor table, LOD inline UVs, and VRAM replay - is consistent.

Colour: PS1 modulates a texel by the primitive RGB as `texel * prim / 128`, so
0x80 is neutral and the stored byte can brighten as well as darken. Track
textures are near-greyscale by design and get their colour from that
multiply; the road's median primitive byte is 60, i.e. about 0.47x. The
importer stores prim/255 in the colour attribute and doubles it in the material
to recover the /128 scale.

## DuckStation `.psxgpu` GPU dump (analyzed, wrong capture moment)
Format PSXGPUDUMPv1, records = [u8 gp0_cmd][u8 word_count][u16 pad][words];
parses byte-exact to EOF (validated). Command byte follows PS1 GP0 semantics
(0x20-3F polygons, 0xA0/0xC0 VRAM copies, 0xE1-E6 env, 0x00 nop, 0xFF marker).
`psxgpu_analyze.py` decodes it.

The supplied capture is **88% VRAM/texture-upload traffic** (1518 large records,
243,614 words) with only 144 scattered small polygon-range records and **zero
on-screen decodable polygons** - i.e. it was captured during a texture-streaming
/ load moment, not steady track rendering, so it contains no track draw list and
cannot resolve the roadway index mapping. It DOES corroborate the texture path.

To crack the roadway topology from a GPU dump instead of GTE logging, capture a
frame during steady in-race track rendering: the stream should then contain a
contiguous run of small-count (<=12-word) polygon records that form the track on
screen. Back-projecting those final vertices (with the frame's GTE/drawing
offset) onto the `.tro` pool would reveal, per primitive, which pool entries the
byte-0/byte-4 (and the missing 3rd/4th) indices resolve to.

## RenderDoc capture (gt2.rdc, Rome start area) - container decoded, geometry needs RenderDoc API
The capture is a genuine RenderDoc RDC (magic RDOC, v1.45 "1.45 2fc0bc") of the
Rome Circuit start (embedded 2048x548 JPEG thumbnail confirms: road, umbrella
pines, HUD "Lap 1/1 6th", speedometer). DuckStation rendered with the **Vulkan**
backend on an RTX 4090 (driver 596.49), so RenderDoc captured the emulator's
Vulkan draw calls.

Container layout decoded:
  0x00 "RDOC\0\0\0\0"; 0x08 u32 version (0x102); 0x10 version string;
  0x20 u16 w, u16 h, u32 jpeg_len; 0x28 JPEG thumbnail; then binary sections.
Section payloads (draw calls, vertex/index buffers) are **zstd-compressed** and
referenced through RenderDoc's chunk serialisation. Raw byte-scanning of the file
mostly hits texture/framebuffer and NVIDIA driver-cache data (the file is
dominated by these), and the naive zstd-magic frames do not expose the Vulkan
chunk stream, so the road vertex buffers cannot be pulled out by hand reliably.

Reliable extraction path: run `extract_gt2_draws.py` inside RenderDoc's Python
console. It walks each drawcall, pulls the bound vertex/index buffers via the
RenderDoc API, and writes them to JSON for the `.tro` matcher.

Important caveat that determines usefulness: PS1 emulation normally feeds the GPU
only 2D screen-space primitives (the GTE projects on the CPU), so unless
DuckStation ran with **PGXP Geometry Correction ON** (which recovers 3D depth
per vertex), the captured vertices are 2D screen-space only - enough for draw
order + UVs, but not for direct 3D matching to the `.tro` pool. With PGXP on, the
recovered 3D positions can be matched to pool vertices to read off, per
primitive, which pool entries the byte-0/byte-4 (and missing 3rd/4th) indices
resolve to - finally closing the roadway topology.

## D3D11 version-correct geometry (v4) - definitive findings
Extractor v4 (per-draw SetFrameEvent reads, no dedup) produced clean
version-correct geometry: gt2_mesh.json = 157 draws, 143 with geometry, 683 road
quads / 2842 verts carrying PGXP perspective depth (w 0.02-0.29). Render order is
back-to-front (w rises across draws) - painter's order, not .tro index order.

Definitive facts established from this ground truth:
  * Each rendered road primitive is an INDEPENDENT quad: 4 distinct vertices,
    no strips, no vertex sharing between consecutive quads (dedup ratio ~1.00,
    consecutive-quad shared verts = 0 or 1, never 2). So every .tro primitive
    must carry all 4 corner indices itself.
  * Road quads are long/thin (edge aspect ~11), i.e. road-ribbon segments.
  * The chunk FT4 record is firmly 12 bytes (list span / count is exact).
    Layout so far: byte0 + byte4 = two real pool indices (RAM-validated tight
    edge, ~794 vs ~2234 random); byte6 = 0; bytes 8-10 = RGB; byte11 = prim
    (0x2C). bytes 1,2,5 look like UVs; byte3 (~0xd9, very stable) and byte7
    (0 or 16) are unresolved.

Structural hypotheses RULED OUT for the 3rd/4th corner indices (all give pool
span ~1600+ vs a coherent quad's ~300; RAM-validated on Rome chunk0 list5):
byte0/byte4 +/-1; consecutive-record strips (either winding); a fixed width
offset K (quad [b0,b4,b4+K,b0+K] for all K); byte3 (216-249) or byte7 (0/16) as
indices (out of main-pool range 0-142); the 2nd ShapeData at chunk+0x94 (only 8
verts); and the 6 sixteen-byte records at ShapeData+0x24 (a separate small
special-primitive set, not the road). So the two unknown corners are neither a
simple function of byte0/byte4 nor stored as plain index bytes in the 12-byte
record.

The open puzzle: with only 2 clear index bytes but 4 independent corners, the
other two corner indices are NOT byte0/byte4 +/-1, not a consecutive-record strip,
and not any tested packing (all give pool span ~1600 vs a coherent quad's few
hundred). Reading them off requires registering the rendered ground-truth quads
to the pool (recover camera pose, project pool, match) - the rendered verts are
screen/view-space (recoverable to view-space via GTE OFX=160/OFY=120/H=216, scale
~1/8 vs raw s16 pool) so a rigid+scale registration is well-posed but not yet
solved. That registration is the remaining step to finalise the roadway encoding.

## D3D11 RenderDoc capture - BREAKTHROUGH data, one versioning wrinkle
Switching DuckStation to the **D3D11** backend fixed the missing-geometry problem
(the Vulkan capture only had 2 present blits; the geometry submit was on the GPU
thread). The D3D11 frame has **157 clean DrawIndexed geometry draws**, vertex
buffer (ResourceId::46, stride 32 = PGXP x,y,z,w + color + texpage + uv + limits)
and index buffer (ResourceId::47, u16). Each draw is a small batch of quads
(quad = 6 indices 0,1,2,2,1,3). Draw order follows GT2's primitive submission.

The road geometry is fully present and reconstructs the Rome frame: verts 0-16104
carry ~14k real screen-space+PGXP vertices, indices 0-37244 give ~6170 quads.
Counts line up with the .tro: ~16.1k rendered verts vs 17,307 total pool verts
(~93%), i.e. nearly all chunks render.

Versioning wrinkle (why it isn't solved yet): the vertex buffer is a D3D11
MAP_DISCARD streaming buffer. The extractor that dumped the whole buffer ONCE
captured a single, mismatched version - the 157 captured draws reference verts
16105+ (this frame) which read as ZERO, while verts 0-16104 hold the PREVIOUS
frame's road. Reconstructing per-batch baseVertex from index-resets drifts
(a batch that reuses its first vertex produces a false 0-reset), so only ~3880 of
6170 quads reconstruct cleanly before drift.

FIX (extractor v4): read each draw's OWN index+vertex range FRESH at that draw's
event (SetFrameEvent, no dedup) so RenderDoc returns the version-correct data per
draw. Output gt2_mesh.json = per-draw quads in submission order, directly
alignable to the .tro primitive lists. Then (match_draws_to_tro.py): propagate
the known byte-0/byte-4 pool indices through the explicit shared vertices to read
off the missing 3rd/4th corners and finalise the encoding.

## RenderDoc PGXP capture - geometry IS recoverable, but draws weren't captured
The PGXP capture's vertex buffer (DuckStation Vulkan, ResourceId::214) was
extracted and decoded. Findings:
  * Vertex format CONFIRMED: 32-byte BatchVertex = float x,y,z,w + u32 color +
    u32 texpage + u32 uv + u32 uv_limits. PGXP gives precise float positions.
  * The 8 MB head holds ~262k vertices / ~87k coherent triangles (mean screen
    span ~26 px) that reconstruct the Rome frame (~50% screen coverage). Colors
    are authentic GT2 (road grays 0x404040/0x595959, sky/sign blue 0x284078).
  * BUT positions are SCREEN-SPACE (x[-371,697] y[-193,712] z[0,1], depth in w),
    not model space, so matching to the .tro pool needs camera-pose recovery.
  * CRITICAL: the captured frame has only TWO draws, both fullscreen present
    blits (3-vert triangle + 4-vert clear/quad); there are NO geometry draw
    calls. DuckStation rendered the PS1 road into VRAM on its GPU thread in a
    separate submit that RenderDoc's present-to-present capture didn't include.
    The 32 MB vertex buffer is a streaming ring that still holds ~20+ frames of
    batched geometry, but with no draw boundaries and no per-chunk segmentation.

Consequence: cracking the chunk index mapping from THIS capture would require
segmenting an unlabelled multi-frame screen-space soup, solving the camera pose,
and label-propagating the known byte-0/byte-4 indices - complex and uncertain.

Clean path: capture a frame that CONTAINS the geometry draws. In DuckStation,
disable **Threaded Rendering** (Settings -> Advanced / GPU) so the geometry
submit executes on the main thread inside the captured frame. RenderDoc will
then record the per-batch vertex/index buffers in GT2's primitive-submission
order, which aligns to the .tro chunk primitive lists - enabling a pose bootstrap
from the byte-0/byte-4 correspondences and read-off of the missing corners.

## DuckStation dump validation (Rome loaded)
- RAM: `.tro` loads verbatim at 0x8009de54; runtime ptr - 0x80000000 = RAM
  offset. Chunk count (179), placement, pool, and lists all match the file.
- VRAM (1024x512, 16bpp): texture pages + CLUTs present, matching `.trp`.
- SPU RAM: audio, not track-relevant.
- Key result: primitive records DO index the pool (bytes 0 and 4 are vertex
  indices, RAM-validated across chunks) - see the OPEN section above.

## Next
- Second ShapeData (chunk+0x94 - the renderer picks it over +0xA4 for one of the
  two draw modes at 0x8002040c), boundary collision, driving line, cameras,
  spawns.
- The alternate chunk draw path at 0x800234f8, taken when the visible-chunk
  record's +0x0E field is non-zero.
- LOD level selection: the importer always draws the nearest non-empty level;
  the `maxDistance` values are parsed but unused.

## Method note
Everything in the SOLVED section came from static analysis of `GT2.OVL` plus a
full 126-file sweep - no emulator, RAM dump, GPU dump or RenderDoc capture. The
four earlier capture-based attempts documented below all failed on the same
problem this solved in one pass.
