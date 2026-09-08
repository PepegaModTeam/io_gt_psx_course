# Foreword

Gran Turismo 1 has been looked into after Gran Turismo 2, so there will be a lot of comparisons and references between the two in this document and in the code itself.

Additionally, it may be a bit hard to parse through as the rest of this document has been AI generated. It needs some touch ups, however, the information is mostly correct and functional enough for this application.

# Gran Turismo 1 course format

Covers `COURSE.DAT` (tracks), `BG.DAT` (skydomes) and `SYSTEM.DAT` (the
course table that ties them together).

Every track in GT1 lives in one archive at the disc root. `COURSE.DAT` is an
`@(#)GT-ARC` container - the same family as GT2's `crstim.arc` - holding **126
entries, which are 63 tracks × 2**:

    entry 2i      the track's texture bundle, a named archive of PS1 TIMs
    entry 2i + 1  the track model: magic `@(#)GT-PS`, version **0x001C0000**

GT2's `.tro` files are version **0x001F0000**, and the two
formats are the same lineage - the primitive encoding, the chunk header, the
texture descriptor and the world scale all carry over. Five things differ, and
all five are set out below with what pins them.

Container: header `@(#)GT-ARC`, `u16 count` at +0x0E, then `count ×
{u32 offset; u32 storedSize; u32 uncompressedSize}`. An entry whose two sizes
differ is LZSS-compressed (flag byte covering eight chunks, LSB first; a set bit
is `length + 3` then a one- or two-byte distance, 32K window). All 126 entries
decompress to exactly their stated size.

## Track names come out of the data

Each texture bundle is `u32 count`, then `count × {char name[16]; u32 offset}`,
then the TIMs. The **second** image in every bundle is named after its own track
(the first is the shared `refrect.tim`), so the 63 names are read rather than
hard-coded, and the importer's track dropdown is filled from whichever archive
is selected.

`track_entries()` does not assume retail's bundle/model alternation either: it
classifies each entry by its own first bytes - `@(#)GT-PS` means a model - and
pairs a model with the most recent bundle before it. A build shipping a
different number of tracks, or a different order, enumerates just as well.
Checked on a synthesised three-track archive holding `testline`, `highway` and
`end` in that order: it enumerates exactly those three, by name, and all three
import with the same geometry they have in retail.

| Index | Name             |
| ----- | -----------------|
| 0     | circuit          |
| 1     | rev_circuit      |
| 2     | 2p_circuit       |
| 3     | arcade_circuit   |
| 4     | short            |
| 5     | rev_short        |
| 6     | arcade_short     |
| 7     | 2p_short         |
| 8     | autumn           |
| 9     | rev_autumn       |
| 10    | arcade_autumn    |
| 11    | 2p_autumn        |
| 12    | mini             |
| 13    | rev_mini         |
| 14    | arcade_mini      |
| 15    | 2p_mini          |
| 16    | highway          |
| 17    | rev_highway      |
| 18    | arcade_highway   |
| 19    | 2p_highway       |
| 20    | hifi_highway     |
| 21    | shortway         |
| 22    | rev_shortway     |
| 23    | arcade_shortway  |
| 24    | 2p_shortway      |
| 25    | hifi_shortway    |
| 26    | outbahn          |
| 27    | rev_outbahn      |
| 28    | arcade_outbahn   |
| 29    | arcade_rev_outba |
| 30    | 2p_outbahn       |
| 31    | hifi_outbahn     |
| 32    | testline         |
| 33    | rev_testline     |
| 34    | test_in2         |
| 35    | rev_test_in2     |
| 36    | mountain         |
| 37    | rev_mountain     |
| 38    | speed            |
| 39    | maxspeed         |
| 40    | 2p_testline      |
| 41    | 2p_test_in2      |
| 42    | 2p_mountain      |
| 43    | arcade_testline  |
| 44    | arcade_test_in2  |
| 45    | arcade_mountain  |
| 46    | TC_lisence_1     |
| 47    | TC_lisence_2     |
| 48    | DF_lisence_1     |
| 49    | DF_lisence_2     |
| 50    | DF_lisence_3     |
| 51    | HSR_lisence_1    |
| 52    | HSR_lisence_2    |
| 53    | DF_lisence_2_2   |
| 54    | autumn_license   |
| 55    | gv1_license      |
| 56    | TMt_lisence      |
| 57    | gv2_license      |
| 58    | DF_lisence_3_2   |
| 59    | gv4_license      |
| 60    | gv3_license      |
| 61    | rogotest         |
| 62    | end              |

`circuit` is Grand Valley Speedway; `testline` is High Speed Ring; `highway` is
Special Stage Route 5. The internal names are not descriptions.

## Differences from the Gran Turismo 2 format

(TODO: Stylize this better for human reading)

## DIFFERENCE 1 - the header is 8 bytes shorter

GT2 has five u32 section pointers at +0x10..+0x20 before a `3` and a
three-word constant; GT1 has three at +0x10..+0x18 and the `3` lands at +0x1C.
Everything downstream shifts by the same 8: GT2's instance-placement count sits
at +0x19C, GT1's at +0x194.

## DIFFERENCE 2 - GT1 bakes NO pointers at all

All three header pointers are zero in all 63 tracks, and so is every internal
one - the chunk pointer array, each ShapeData's vertex and list pointers, the
prop shape pointers. The loader patches them at load time. Nothing in the file
says where anything is.

Everything is still reachable, because the file is laid out in the order the
pointers would have pointed and every section's length is a function of its own
counts:

    0x194   33 instanced-object groups, `{u32 count; count × 28-byte placement}`
            end to end. A placement is `s16 rot[2]; s16 pad[2]; s16 scale[4];
            s32 pos[3]` in 16.16.
    then    TrackChunkTable: `u16 a, b; u16 numChunks; u16 c; u32 texTable;
            u32 chunkPtrs[numChunks]` - the last two fields zeroed.
    then    numChunks TrackChunks end to end, each sized from its own counts.
    then    the texture-descriptor table, `(highest referenced id + 1) × 32`.
    then    a 4-byte pad, the prop LOD chains, and the prop shapes.

### The chunk size formula, derived on GT2 where it can be checked

A TrackChunk is its 0xA4 header, ShapeData 1 in place at +0xA4, ShapeData 2, and
three trailing sections. **GT2 stores a pointer to each of the last four at
+0x94..+0xA0**, so the arithmetic can be validated there before being trusted
here:

| section | size |
|---|---|
| ShapeData (either) | `0x44 + vertexCount*8 + Σ listCount[i]*stride[i]` |
| at +0x98 | `4 + count*8` |
| at +0x9C | `104 + 4*Σ counts[16]` - a `{u16 hdr[4]; u16 counts[16]; u32 ptrs[16]; u32 items[]}` table |
| at +0xA0 | `(2 + 2*count + 3) & ~3` - a `{u16 count; u16 chunk[]}` visibility list |

Predicting all four from the chunk's own counts and comparing against GT2's
stored pointers is exact on **14,261 of 14,261** retail GT2 chunks.

Applied to GT1 it agrees with an independent byte-signature search on `circuit`
for **219 of 219** chunks - `testline` 0x8A8, `test_in2` 0x77C, `speed`
0x564, `maxspeed` 0x580, `2p_testline` 0x3A0, `2p_test_in2` 0x69C,
`2p_mountain` 0x4F4, `end` 0x32C - **8 of 8**, from the format instead of by
hand. (The commented-out `circuit = 0xF30` in that project's source is also
reproduced: `0xBC4 + 219*4`.)

Note that `prev`/`next` at chunk+0x00 are a genuine graph, not a sequence. It
happens to run 0,1,2,… on the circuits, but `testline`'s chunk 0 has
prev 27 / next 77 - the test and licence layouts branch.

## DIFFERENCE 3 - the texture descriptor is rotated

Both games use a 32-byte descriptor holding two 12-byte UV blocks and a LOD
threshold. GT2 puts the threshold between the blocks at +0x0C; **GT1 puts it
first**:

    +0x00  u16 lod_threshold ; u16 pad
    +0x04  u8 u0, v0 ; u16 clut     entry 0, full resolution
    +0x08  u8 u1, v1 ; u16 tpage
    +0x0C  u8 u2, v2, u3, v3
    +0x10  the same twelve bytes again, entry 1 (the half-size mip)
    +0x1C  u32 0

The twelve bytes are otherwise identical: `circuit`'s first descriptor carries
the same threshold (0x7C0) and the same tpage (0x0E) in both games.

Read at the right offsets, GT1's tpage lands in **11..31 - GT2's exact range**.
Read at GT2's offsets it looks like 30720..31699, which is the clut field.

## DIFFERENCE 4 - textures are a named bundle, not a VRAM replay sidecar

GT2's `.trp` is `u32 count` then TIMs; GT1's bundle puts a name table in front.
Each TIM still carries its own destination VRAM coordinates, so replaying them
into a 512×1024 halfword framebuffer reproduces the memory the descriptors'
tpage/clut fields address. Across all 63 tracks, **4,097 of 4,097** CLUT ids
referenced by a descriptor are provided by that track's own bundle.

## DIFFERENCE 5 - the pool is four times finer, on a four times tighter grid

| | GT2 | GT1 |
|---|---|---|
| pool vertex unit | 1/64 world | **1/256 world** |
| origin | `(Center & 0xFFC00000) >> 10` | **`(Center & 0xFFF00000) >> 8`** |
| grid | 64 world units | **16 world units** |
| remainder box | 4096 pool units | 4096 pool units |

The same twelve bits, split differently between grid and remainder.

Measured against the chunk's own header rather than anything external: a
chunk's `Center` at +0x30 is an absolute 16.16 world position, so a correct
origin puts the pool's centroid on top of it. Sweeping every mask from 2^20 to
2^24 (and none) against pool scales from 1/32 to 1/512 - 60 combinations - this
one wins outright at a **median 3.08 world units**, where GT2's own settings
score 2.78 on GT2 and the runner-up here scores 7.42.

Corroborated on `circuit`, the one course both games ship. At GT2's 1/64 the
median face span is 2,269 pool units against GT2's 573 - a factor of 3.96; at
1/256 that is **8.9 world units against GT2's 8.95**. The path through the chunk
Centers is **4942.5 world units in BOTH games** with a median chunk step of
19.65, which also fixes the world unit at about a metre - Grand Valley is 4.9 km.

### …and GT1's world runs the other way along component 2

GT1's chunk origins match GT2's **219 of 219** on the shared circuit *once
component 2 is negated*. Feeding GT1 through GT2's mapping, which mirrors X
alone, therefore applies one net mirror and turns every face inside out: only
**18.4%** of near-horizontal textured faces end up pointing upward, and the
course renders as black backfaces. Negating **both** X and Y is a rotation
rather than a mirror, so handedness is preserved - the same faces come out
**81.6%** up, against 90.4% for GT2 read with its own settings, and the shared
circuits land in the same orientation in both games.

## What carries over unchanged

The primitive encoding is GT2's: four **9-bit** pool indices at bits 0, 9, 18
and 32, the slot index selecting the primitive type, the GP0 command byte at
record byte 11, strides F3 12 / F4 12 / G3 20 / G4 24 / FT3 12 / FT4 12 /
GT3 20 / GT4 24. Over all 63 tracks and **539,554** primitives, **100%** of
indices resolve inside their own chunk's vertex pool and **100%** of command
bytes match their slot. The texel-centre UV convention and the corner ordering
are GT2's too.

Slots 8 and 9 are present: **5,764 billboards** and **2,857 lamp glares**. The
glare keeps the property that identified it in GT2 - `highway` (Special Stage
Route 5, a night race in GT1 as well) has 246 while the daytime tracks have none.

A chunk carries **two** ShapeData blocks. GT2's importer only ever built the
first; here both are built, the second's pool appended and its indices shifted.
It contributes about 12% of the faces on `circuit`.

## The skydomes live in `BG.DAT`, and `SYSTEM.DAT` says which

A course's sky is not in `COURSE.DAT`. It sits beside it in **`BG.DAT`**,
another `@(#)GT-ARC` with the same alternation the tracks use: **20 entries =
10 skies × {texture bundle, model}**. The model's magic is **`@(#)GT-SKY`**, a
sixth member of the `@(#)GT-` family, version 2.

    +0x00  char magic[10] "@(#)GT-SKY" ; u16 pad
    +0x0C  u32 version                  0x00020000
    +0x10  u8 r, g, b ; u8 0x28         background colour A
    +0x14  u8 r, g, b ; u8 0x28         background colour B
    +0x18  12 bytes, always zero
    +0x24  u32 vertexCount
    +0x28  u16 listCounts[8]            F3 F4 G3 G4 FT3 FT4 GT3 GT4
    +0x38  vertexCount × 8              s16 x, y, z, pad - pad always zero
    then   the eight primitive lists
    then   THE SAME BLOCK AGAIN
    then   u32 count ; char name[16][count]   the textures the sky uses

That colour pair is GT2's `.bso` header exactly, `0x28` terminator and all, and
a record is the same shape: 8 bytes of indices then a PS1 GPU packet beginning
at record+12. Two differences:

* GT2 stores **two** copies of `[OT tag][packet]` inside each record for double
  buffering. GT1 stores one and then **repeats the entire primitive block** -
  byte-for-byte identical on all ten skies.
* Indices are the `.bso`'s **four 12-bit fields** at bits 0-11 and 12-23 of the
  two words, not the roadway's nine. Over **1,238** sky primitives every one
  resolves inside its own vertexCount, against 32.6% read as 9-bit, and decoded
  faces span a median 1,174 units against 7,090 for random triples. The OT tag's
  length byte matches its slot's packet size on **100%** of them, which is what
  pins the strides (`12 + words × 4`).

### `SYSTEM.DAT` is `@(#)GTENV`, the course table

    +0x00  char magic[9] "@(#)GTENV"
    +0x0C  u16 count                    63 - the track count
    +0x48  count × { u8 length; char name[]; }   length counts the NUL too
    then   count × 16-byte records

**Byte 2 of the record is the sky**: the low seven bits index `BG.DAT`, and bit
7 marks a night course. It is completely self-consistent - all 63 courses
resolve to a sky that exists, and the only two values carrying bit 7 (`0x83` for
the `highway` family, `0x85` for `outbahn`) point at two of the three skies whose
background colour is pure black. Special Stage Route 5 and Special Stage Route
11 are exactly GT1's night races. A third check closes the loop across all three
files: every course that carries lamp glare in `COURSE.DAT` is flagged night
here and lands on a black sky in `BG.DAT`.

| sky | colour A | used by |
|---|---|---|
| 0 | 22, 51, 79 | `test_in2` (Deep Forest) |
| 1 | 84, 122, 158 | the Deep Forest / High Speed Ring licence layouts |
| 2 | 0, 136, 255 | `testline` (High Speed Ring) |
| 3 | black | `highway`, `shortway` - night |
| 4 | black | unused |
| 5 | black | `outbahn` - night |
| 6 | 41, 80, 167 | `circuit`, `short` (Grand Valley) |
| 7 | 45, 86, 137 | `autumn`, `mini` |
| 8 | 58, 87, 115 | `mountain`, `speed`, `maxspeed` |
| 9 | 32, 82, 131 | `end` - no textures at all |

**Look the sky up by POSITION, not by name.** Both files enumerate the same 63
courses in the same order, but `COURSE.DAT`'s name field is a fixed 16 bytes
while GTENV's strings are length-prefixed, so `arcade_rev_outbahn` is truncated
in one and not the other - and a name lookup silently loses that one course its
sky.

## A LOD chain that opens with an empty shape draws NOTHING up close

A prop's LOD chain is `(max distance, shape)` ordered nearest-first - all 1,800
chains in the game are distance-ordered, which is what makes the ordering safe
to read. When the FIRST shape is empty, the game deliberately draws nothing
nearby: the object only appears in a band further out.

`circuit`'s LOD 29 switches at **50 and 700 world units**, so between those it
draws a coarse copy of the roadway and inside 50 it draws nothing at all. LOD 30
is 70/600, LOD 28 is 80/328.

Falling through to the next level therefore drops a low-detail duplicate of the
track into the middle of the track. **125 of the 63 tracks' 2,728 instances**
are these, so they go into their own unticked `GT1 Distant Stand-ins`
collection, named `gt1_far_*` rather than `gt1_prop_*`.

An empty level that carries a BILLBOARD list is a different thing and is not
affected - that is how a distant object is swapped for a single sprite.

(The GT2 path had the same bug and is fixed the same way: **398 of its 6,083**
retail instances open with an empty level, 46 on `parma` alone.)

## Props sitting flush with the road: the PS1 had no depth buffer

Not a decode problem, and worth writing down because it looks like one. The
console sorted primitives into an **ordering table** and drew them back to
front - which is why a `@(#)GT-SKY` record carries an explicit `[OT tag]`, and
why matching that tag's length byte to each slot is what pins the sky strides.

With no depth buffer, a prop's ground apron can be authored EXACTLY flush with
the roadway and still render cleanly: draw order decides, not depth. Blender has
a depth buffer, so the same geometry z-fights.

`highway`'s `prop_0051_lod010` is the clearest case. Three of its 109 faces
overlap a roadway face, by **0.02 to 0.03 world units**; everything else on it
is clear. Nothing is misplaced - every face of that prop which sits over the
road is *below* it, and the faces above are all 94+ units away horizontally.
Both games measure identically (median prop base 3.8 units under the nearest
road, 5.5% of prop faces within 1 unit of a road face), which is the point:
GT1's placement is GT2's, and GT2's was validated against the roadway.

There is no draw-priority field to read, either - every record in that prop
carries the same flag bits (`w0` bits 30-31 = 3, `w1` bits 10-31 = 0).

So the importer offers a **prop depth bias**, off by default. Measured across
Special Stage Route 5 by the vertical separation between near-horizontal prop
faces and the road surface beneath them:

| bias | GT1: faces under 0.05 from the road | GT2 |
|---|---|---|
| 0.00 | 4 (closest 0.003) | 6 (closest 0.009) |
| 0.05 | 3 | 4 |
| 0.15 | **0** (closest 0.053) | 1 |
| 0.30 | 0 | **0** (closest 0.196) |

0.15 clears GT1, 0.3 clears both. Note that a *uniform* sink is a blunt
instrument: it separates surfaces that were flush, but nudges others that had a
small gap into one. The table above is the honest measure of what it buys.

## Textures: what a "texture" even is here

`COURSE.DAT` never records a texture. It records, per face, a texture page, a
palette, and the texel coordinates of that face's corners -- which is all the
console needs, because the console draws out of VRAM directly. Nothing says
where one texture ends and the next begins.

It can be recovered anyway. A face's UV corners bound the texture it samples,
and two faces that share a texture produce boxes that overlap. Unioning
overlapping boxes per (page, palette) therefore reassembles the textures, and
the result is the right shape for a PS1 course:

| track | (page, palette) pairs | distinct per-face boxes | recovered textures | texels |
| --- | --- | --- | --- | --- |
| `highway` (SSR5) | 136 | 1,374 | 141 | 497,790 |
| `circuit` (Grand Valley) | 119 | 1,739 | 158 | 461,282 |
| `outbahn` (SSR11) | 129 | 1,539 | 133 | 453,706 |
| median of 63 | 88 | -- | 92 | -- |

Not one recovered tile came out a full page, which is the check that matters:
if the union rule were over-merging it would collapse each page to a single
256x256 block and the numbers would land on the pair count instead.

Two things the grouping must get right:

1. **The palette is part of the identity.** The same 4-bit indices drawn
   through a different CLUT are a different image, so the key is always
   (page, palette). Keying on the page alone would fuse unrelated textures.
2. **Pages do not overlap in VRAM.** A tpage's X base is `(tpage & 0xF) * 64`
   halfwords and a 4-bit page is 64 halfwords wide, so pages tile exactly.
   Nothing is double-counted between them; the duplicates that do turn up are
   two palettes holding the same colours, and those are merged by content hash.

The skydome's textures come from its own bundle in `BG.DAT`, not the course's,
so it is grouped separately -- packing the two together would put textures from
two unrelated VRAM images in one atlas for no gain. Its own numbers are small
and lopsided: `circuit`'s dome references 40 pages that dedup to a **single**
texture.

### Equivalence

The three modes differ only in where the texels live, so the test is whether a
face still reads the same texels. Building `highway`, `circuit` and `testline`
three times each and sampling every textured mesh loop's UV out of its own
material's image: **156,555 loops, 0 differences** between VRAM pages,
individual textures and the atlas. The 63-track sweep additionally checks that
no textured face falls back to a page material, which is how an unrecovered
tile would show up.

One deliberate difference: a cropped tile is sampled `EXTEND`, not `REPEAT`. A
full page can wrap -- there is a page around it -- but a tile has nothing
around it, so a UV landing a hair outside must clamp to the edge texel rather
than jump to the far side of an unrelated texture.


## Other builds: the July 29 1997 prototype

`COURSE.DAT` is not one shape. The earliest known prototype writes the same
format with a shorter header in two places, and reading it with retail's
offsets walks off the end of the buffer.

| | retail | Jul 29 1997 prototype |
| --- | --- | --- |
| model version at +0x0C | `0x001C0000` | `0x001A0000` |
| instance groups start at | 0x194 | **0x110** |
| instance groups present | 33 | **1** |
| chunk header | 0xA4 | **0x78** |
| `world` / `Center` in a chunk | +0x18 / +0x30 | **+0x14 / +0x2C** |
| course table | `SYSTEM.DAT` `@(#)GTENV` | **`SYSTEM.ENV`, plain text** |
| tracks | 63 | 14 |

Both differences are retail ADDING a field:

* the 33-entry instance-group offset array. GT2 keeps it at +0x118 and points
  it at the groups, retail GT1 keeps it and zeroes it, the prototype does not
  have it at all. 33 x 4 = 132 = the 0x194 - 0x110 gap exactly.
* per chunk, a u32 at +0x0C and a second block of ten u32s at +0x6C -- 44
  bytes, and 0xA4 - 0x2C = 0x78. Everything from +0x0C on shifts down by the
  first four, which is why `world` and `Center` both move by 4 and not by 44.

### Detected, not looked up

The layout is chosen by WALKING the chunk table to the end, not by the version
word. Every chunk is located by walking the previous one, so a wrong header
size fails within a chunk or two and the right one walks all of them and lands
inside the file: on the prototype only 0x78 works, with 0x74 and 0x7C both
failing on the first chunk.

One trap, found the hard way. An offset inside the instance groups can read as
a ONE-chunk table that happens to walk, so accepting the first candidate that
validates is wrong -- it cut retail `highway` from 194 chunks to 1. The
candidate that explains the most of the file wins instead, which is safe
precisely because walking N chunks is a strong signature when N is large.

### `SYSTEM.ENV` is the prototype's `@(#)GTENV`

There is no `SYSTEM.DAT`. `SYSTEM.ENV` is a plain `key=value` text file holding
the same three facts:

    course=14
    course.name.0=GRAND VALLEY SPEEDWAY
    course.name.7=HIGH SPEEDRING
    course.bg.7=BG tl_sky2g
    sky=10
    sky.name.2=BG tl_sky2g

So a sky is resolved by NAME through two hops where retail resolves it by index
in one. It checks out on all 14 courses, and the skies it picks carry the same
textures as the retail entries for the same course -- High Speed Ring gets
kumo2/tubo4d1 in both, Deep Forest kumo2/tubo1a1 in both.

The names matter for a second reason: the prototype's texture bundles are named
after TEXTURES, not tracks, so the archive alone yields `1kabe1` twice, `1ki3`
three times and `1douro` twice. `SYSTEM.ENV` has the real ones.

Two of the ten skies are unused by any course -- `BG Test` (bga1/bga5) and
`BG c1_bg` (bg_ab1/bg_ab2), the latter presumably for the Tokyo C1 loop that
never shipped. There is no night flag anywhere in `SYSTEM.ENV`, so night is
reported unknown rather than guessed.

### What the prototype says about the format

Three courses survive to release unchanged, and that is the check that settles
the decode -- the same course read out of two files nine months apart must
produce the same geometry:

| course | prototype | retail | |
| --- | --- | --- | --- |
| High Speed Ring | 9643.5 units / 95 chunks | `testline` 9643.5 / 95 | identical |
| Autumn Ring | 3103.0 / 160 | `autumn` 3103.0 / 160 | identical |
| Special Stage R5 | 3962.5 / 194 | `highway` 3962.5 / 194 | identical |
| Special Stage R11 | 5090.1 / 214 | `outbahn` 5080.8 / 214 | 0.2% revised |
| Grand Valley | 5562.6 / 242 | `circuit` 5168.2 / 219 | **redesigned** |

The pool is unchanged too: sweeping the origin rule against each chunk's own
`Center` picks `0xFFF00000 >> 8` with 1/256 at a median 2.53 world units, the
same winner retail scores 3.08 on, with the runner-up five times worse.

Decode quality matches the retail standard: **100.00% of 373,275 primitive
indices resolve inside their own pool** and 99.99% of 124,425 command bytes
match their slot.


## Importer trap: chunk vertices must stay chunk-local

A chunk's pool is stored relative to its own origin, and there are two places
that origin can be applied: baked into every vertex, or carried on the Blender
object. GT2's importer does the latter, and that is not incidental -- a chunk's
BILLBOARDS are built in a separate pass from its solid geometry, so baking the
offset into the solid vertices leaves the sprite corners without it and drops
every billboard of every chunk on the world origin. The result is a floating
ring of trees at (0, 0) on most tracks, and nothing else visibly wrong.

Keep the vertices local and set `obj.location`; then there is only one place the
offset can be applied and no later stream can forget it.

## Importer trap: the vertex colour attribute name

The shared GT2 material factory samples a colour attribute named exactly
`GT2_Color`. Creating it under any other name leaves the vertex colour reading
as black, and since the material is `texel × vertexColour × 2`, **every textured
face renders solid black** with no other symptom - the images are correct, the
UVs are correct, the node graph is correct.

## The instanced props

Solved. Placements are the 33 groups at 0x194, 28 bytes each and byte-identical
to GT2's: `s16 flags, yaw, unk, lodIndex; s16 scale[4]; s32 pos[3]` in 16.16,
ordered (X, height, Z). GT1 stores a sequential shape INDEX where GT2 stores a
pointer, so the LOD chains resolve through the shape list rather than by address;
the indices form a dense 0..N-1 run in every track that has props.

**A prop ShapeData's header is 0x58 bytes, not the 0x44 a track chunk uses**,
and its vertex pool follows it. That single number is what made this stream look
undecodable: reading a prop pool at +0x44 leaves everything after it 20 bytes
out of step. GT2 states the figure outright and unanimously - its stored
`vertexPtr` is `shapeStart + 88` on all **5,708** retail prop shapes, against
`+ 68` on all 5,508 chunk ShapeData - but it never has to be noticed there,
because GT2 also stores where each list begins.

The extra twenty bytes are not padding: `lod_shape_scale()`'s per-shape exponent
at +0x54 lives in them, and GT1's values there follow GT2's 19..24 distribution.
Read at +0x44 the median prop comes out thousands of units tall; read at +0x58,
**23.8 world units beside a ~15-unit road**, against GT2's ~20.

With the header right, the record is GT2's unchanged - 10-bit indices at bits 0,
10 and 20 plus a fourth in `w1`, UVs inline, strides F3 12 / F4 12 / G3 20 /
G4 24 / FT3 24 / FT4 24 / GT3 32 / GT4 36. Over all 63 tracks and **59,577**
prop primitives, **100%** of command bytes match their slot and **100%** of
indices resolve inside their own vertexCount; read 20 bytes early those are
0.85% and 19.6%. All **2,728** instances resolve a LOD chain.

Two details worth recording:

* The prop stream's flat untextured types use **different command bytes from the
  roadway's**: slot 0 carries 0x21 and slot 1 0x29, not 0x20/0x28. Measured over
  20 retail GT2 courses at 100% each. Testing against the chunk codes is what
  first made slots 0 and 1 look like noise.
* GT1 pads each shape out by a further **four bytes**; GT2 does not. So a shape
  occupies `0x58 + vertexCount*8 + Σ counts*stride + 4` here and the same
  without the `+ 4` there.

**Orientation.** The prop mesh mapping is GT2's unchanged - `(x, y, z)` to
Blender `(-x, -z, y)` with the winding reversed. The roadway needed an extra
negation for GT1 and props do not: a prop's local space is not mirrored between
the games, only the world positions, and those are handled by negating both
horizontal axes of the instance position. Reading a prop's own texture settles
it, as it settled GT2's: with the extra negation the trackside hoardings render
back to front.

That position mapping has an independent check. Of the props on the five
circuits both games ship, **325 match a GT2 prop to within 2 world units** -
87 of 88 on Grand Valley, 67 of 67 on Special Stage Route 5, 41 of 41 on Trial
Mountain - and all **325 carry an identical stored yaw**. The prop meshes
themselves are re-authored, though, so they are no help as a vertex oracle.

The yaw is applied as GT2 applies it, **negated**. Measured the same way:
each placed prop's principal horizontal axis against the heading of the nearest
roadway chunk, restricted to shapes elongated enough for that axis to mean
something. Negating gives a median error of **12.9 degrees with 55.5% inside
15**; leaving it positive gives 31.7 and 40.7% (427 samples at 8:1 elongation,
615 at 3:1 agreeing).

## The second ShapeData is a low-detail copy of the same ground

Every chunk carries two ShapeData blocks. GT2's importer only ever built the
first; building both here made the roadway z-fight with itself, which is what a
doubled track surface in the viewport turned out to be.

The second is a low-detail duplicate, not extra scenery. It covers the first's
bounding box in **every chunk that has one** (95/95 on `testline`, 206/206 on
`outbahn`), while carrying about 15% of the vertices and **9.6% of the
primitives** across the whole game, with a median face span 2.5 to 3.7 times
larger.

So it is imported into its own `GT1 Low-detail World` collection, and that
collection is **unticked in the outliner** - it is in the file, one click away,
and out of the way of the roadway it sits on top of.
