# Gran Turismo PSX Course Importer for Blender

A Blender add-on that imports the **PlayStation 1** Gran Turismo course formats
— GT1 and GT2 — with geometry, world placement, instanced LOD props, billboard
sprites, night lamp glare, skies and PS1 VRAM texture recovery.

## AI/LLM Usage Disclosure

This add-on was made with AI/LLM assistance. It was used to:

- analyze game code and existing tool code and structures (some based on our own internal work, some based on other people's work; see CREDITS.md)
- help with Blender's Python API
- data analysis
- documentation

## Supported games and formats

| Game | Platform | Container / model format | Textures | Status |
| --- | --- | --- | --- | --- |
| Gran Turismo 1 | PS1 | `@(#)GT-ARC` `COURSE.DAT` (63 `@(#)GT-PS` v0x1C models), `BG.DAT` (`@(#)GT-SKY` domes), `SYSTEM.DAT` (`@(#)GTENV` course table) | named TIM bundle per track (PS1 TIM into a 512x1024 VRAM replay) | roadway chunks + world placement + instanced LOD props + billboard sprites + night lamp glare + low-detail world + skydome + textures + vertex colour |
| Gran Turismo 2 | PS1 | `@(#)GT-PS` `.tro` track object, `BG\0\0` `.bso` skybox | `.trp` / `.bsp` sidecars (PS1 TIM into a 512x1024 VRAM replay) | roadway chunks + world placement + instanced LOD props + billboard sprites + night lamp glare + skybox + textures + vertex colour |

Files may be gzipped; decompression is automatic. Formats are recognised by
content, not by extension.

## What's not supported

This add-on currently does not support importing of:

- Collision
- AI pathing
- Checkpoints

## Installation

Download the latest release zip and then drag and drop the zip file into Blender.

Then go to: Edit > Preferences > Add-ons and enable **Gran Turismo PSX Course Importer**. 

Import via File > Import > Gran Turismo Course (PS1: GT1/GT2).

It registers its own operator (`import_scene.gt_psx_course`) and its own menu
entry.

## Import options

### General
- **Import textures**: decode the course's PS1 textures. GT1 reads the named
  TIM bundle paired with the track inside `COURSE.DAT`; GT2 replays the
  same-name `.trp` sidecar. Both go into a 512x1024 VRAM image that each face
  addresses through its own tpage/clut.

There is no Axes/Coordinates group. The PS1 paths never took one — both modules
apply their own coordinate convention internally. Carrying them here would
only offer settings that do nothing.

### GT1
All 63 tracks live in a single `COURSE.DAT` at the disc root, so point the
importer at that file and pick one from the **GT1 track** dropdown, which fills
in with the track names as soon as an `@(#)GT-ARC` archive is selected. The list
is read out of the archive in front of it, so a demo disc enumerates its own set
rather than retail's 63. Selecting anything else leaves a plain numeric index in
its place, and a script that passes `gt1_track` explicitly still overrides the
dropdown.

The names are not descriptions: `circuit` is Grand Valley Speedway, `testline`
is High Speed Ring, `highway` is Special Stage Route 5. The full list is in
`GT1_COURSE_FORMAT_NOTES.md` and is printed to the console on import.

- **GT1 textures** — `VRAM pages` / `Individual textures` / `Single atlas`.
- **Import GT1 instanced props**, **skydome** + **sky radius**, **billboards**,
  **lamp glare**, **low-detail world**.

### GT2
- **GT2 textures** — the same three modes, on the same reasoning.
- **Import GT2 instanced props**, **skybox** + **sky radius**, **lamp glare**.

The skybox is a separate file (`bgsobj/<name>.bso` plus its `.bsp` textures) and
`.crsinfo` says which of the 34 skies a course uses, so it needs `bgsobj/` and
`.crsinfo` alongside `crsobj/`. With only `crsobj` extracted it reports and moves
on. A `.bso` can also be opened directly.

### Shared
- **Prop depth bias**: how far to sink instanced props so their ground surfaces
  do not z-fight with the roadway. The PS1 had no depth buffer — it sorted
  primitives into an ordering table and drew back to front — so a prop's apron
  could be authored flush with the road and still render cleanly. Measured on
  Special Stage Route 5: 0.15 clears GT1, 0.3 clears both. 0 leaves the geometry
  exactly as authored.

