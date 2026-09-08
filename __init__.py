# SPDX-License-Identifier: MIT
r"""Gran Turismo PSX Course Importer

Handles the two PlayStation 1 games:

  GT1   `@(#)GT-ARC` COURSE.DAT (63 `@(#)GT-PS` v0x1C models, and the
        July 29 1997 prototype's 14 v0x1A ones), `BG.DAT` skydomes, and the
        course table from `SYSTEM.DAT` (`@(#)GTENV`) or `SYSTEM.ENV`
  GT2   `@(#)GT-PS` `.tro` track objects and `BG\0\0` `.bso` skyboxes
"""

bl_info = {
    "name": "Gran Turismo PSX Course Importer",
    "author": "Team Pepega",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "File > Import > Gran Turismo Course (PS1)",
    "description": "Importer for the PlayStation 1 Gran Turismo course formats: "
                   "GT1 (COURSE.DAT + BG.DAT skydomes + SYSTEM.DAT/SYSTEM.ENV course "
                   "table, retail and the Jul 1997 prototype) "
                   "and GT2 (@(#)GT-PS .tro track objects + .bso skyboxes), with "
                   "geometry, world placement, instanced LOD props, billboard "
                   "sprites, night lamp glare, skies and PS1 VRAM texture recovery.",
    "category": "Import-Export",
}

import gzip
import os
from typing import Tuple

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper


# ===========================================================================
# Container reading
# ===========================================================================
# The PS1 courses are raw, but both games' files are commonly extracted from
# the disc gzipped (`.tro.gz`), and GT2's own `.trp`/`.bsp` sidecar reader
# already unwraps that itself.
def read_course_file_bytes(filepath: str) -> Tuple[bytes, str, str]:
    with open(filepath, "rb") as f:
        raw = f.read()

    if raw.startswith(b"\x1F\x8B"):
        try:
            data = gzip.decompress(raw)
        except Exception as exc:
            raise ValueError(
                f"File looks gzip-compressed, but decompression failed: {exc}") from exc
        return data, "gzip", f"gzip {len(raw)} bytes -> {len(data)} bytes"

    return raw, "raw", f"raw {len(raw)} bytes"


# The magics this add-on deliberately does not handle, so an unsupported file
# gets told what it actually is rather than "no model data found".
_NOT_PS1 = (
    (b"PACB", "a PS3 course package (GT HD / GT5 Prologue / GT5 / GT6)"),
    (b"MDLS", "a PS2 ModelSet2 container (GT4 Prologue / retail GT4)"),
    (b"GTM1", "a PS2 GTM1 model set (retail GT3)"),
    (b"GTM0", "a PS2 GTM0 model set (GT2000 / early GT3)"),
    (b"GTC0", "a PS2 GTC0 course (GT2000 / early GT3)"),
)


def _describe_unsupported(data: bytes) -> str:
    head = data[:4]
    for magic, what in _NOT_PS1:
        if head == magic or (magic in (b"MDLS", b"GTM1", b"GTM0") and data.find(magic) >= 0):
            return (f"This looks like {what}. This add-on is the PS1-only build "
                    f"(GT1 and GT2);")
    return ("Not a PS1 Gran Turismo course: expected a GT1 '@(#)GT-ARC' archive "
            "(COURSE.DAT), a GT2 '@(#)GT-PS' .tro track object, or a GT2 'BG' .bso "
            "skybox.")


# ===========================================================================
# Dispatcher
# ===========================================================================
def import_psx_course(
    filepath: str,
    context: bpy.types.Context,
    *,
    import_textures: bool = True,
    gt1_track: int = 0,
    gt1_import_sprites: bool = True,
    gt1_import_glare: bool = True,
    gt1_import_lod_world: bool = True,
    gt1_import_props: bool = True,
    gt1_import_sky: bool = True,
    gt1_sky_radius: float = 1500.0,
    gt1_texture_mode: str = "PAGE",
    gt2_import_props: bool = True,
    gt2_import_sky: bool = True,
    gt2_import_glare: bool = True,
    gt2_sky_radius: float = 1500.0,
    gt2_texture_mode: str = "PAGE",
    prop_depth_bias: float = 0.0,
    report=print,
) -> Tuple[int, int, int, int]:
    """Route a PS1 course file to its importer. Returns (objects, verts, faces, shapes).

    There is no scale/axis group here. The PS1 paths never took one: both
    modules apply their own coordinate convention internally, so the full
    add-on's Axes/Coordinates options are not forwarded to GT1 or GT2 and
    carrying them would only offer settings that do nothing.
    """
    data, input_encoding, input_note = read_course_file_bytes(filepath)

    # --- GT1 COURSE.DAT ------------------------------------------------------
    # Gran Turismo 1 keeps every track in one `@(#)GT-ARC` archive at the disc
    # root: retail is 126 entries, alternating a texture bundle and a
    # `@(#)GT-PS` model of version 0x001C0000 -- the same magic GT2 uses at
    # 0x001F0000. The format is GT2's with an 8-byte-shorter header and,
    # crucially, NO baked pointers at all; every section is found by walking.
    # That is also how the build is identified: gt1.py picks the header shape by
    # walking the chunk table to the end rather than reading the version word,
    # so the Jul 1997 prototype's 14 shorter-header courses import too, and an
    # unreadable model comes back as a message instead of a traceback.
    # See gt1.py.
    if data[:10] == b"@(#)GT-ARC":
        from . import gt1
        return gt1.import_gt1_course(filepath, data, context, track=gt1_track,
                                     report=report,
                                     import_textures=import_textures,
                                     import_sprites=gt1_import_sprites,
                                     import_glare=gt1_import_glare,
                                     import_lod_world=gt1_import_lod_world,
                                     import_props=gt1_import_props,
                                     import_sky=gt1_import_sky,
                                     sky_radius=gt1_sky_radius,
                                     prop_depth_bias=prop_depth_bias,
                                     texture_mode=gt1_texture_mode)

    # --- GT2 .tro (PS1 TRack Object) ----------------------------------------
    # Both halves are ground-truth anchored, read out of GT2.OVL's own chunk
    # renderer: the primitive encoding (four 9-bit indices) validated on 699,229
    # primitives across all 126 retail courses, and chunk placement (pool origin
    # = (Center & 0xFFC00000) >> 10, pool ordered X,Z,Y). Both geometry streams
    # import -- roadway chunks and instanced LOD props -- with textures bound by
    # replaying the `.trp` sidecar into a PS1 VRAM image and addressing it
    # through each primitive's tpage/clut. See gt2.py and GT2_TRO_FORMAT_NOTES.md.
    if data[:9] == b"@(#)GT-PS":
        from . import gt2
        return gt2.import_gt2_tro(filepath, data, context, report=report,
                                  import_textures=import_textures,
                                  import_props=gt2_import_props,
                                  import_sky=gt2_import_sky,
                                  import_glare=gt2_import_glare,
                                  sky_radius=gt2_sky_radius,
                                  prop_depth_bias=prop_depth_bias,
                                  texture_mode=gt2_texture_mode)

    # GT2 skybox: bgsobj/<name>.bso, with its textures in the matching .bsp.
    # Importing a course picks its own sky up automatically through .crsinfo;
    # this path is for opening one directly.
    if data[:4] == b"BG\x00\x00":
        from . import gt2
        return gt2.import_gt2_bso(filepath, data, context, report=report,
                                  import_textures=import_textures,
                                  sky_radius=gt2_sky_radius,
                                  texture_mode=gt2_texture_mode)

    raise ValueError(_describe_unsupported(data))


# ===========================================================================
# GT1 track dropdown
# ===========================================================================
# All 63 GT1 tracks live in one archive, so the track is picked in the UI rather
# than by choosing a file. The list is read out of whichever archive is selected
# (a demo disc enumerates its own set, not retail's 63) and cached on the file's
# identity so the enum callback stays cheap - Blender calls it on every redraw.
_GT1_TRACK_CACHE = {}
_GT1_NO_TRACKS = [("0", "<no GT1 archive selected>", "")]


def _gt1_track_items(self, context):
    path = getattr(self, "filepath", "") or ""
    try:
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
    except OSError:
        return _GT1_NO_TRACKS
    hit = _GT1_TRACK_CACHE.get(key)
    if hit is not None:
        return hit
    items = _GT1_NO_TRACKS
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            if head[:10] == b"@(#)GT-ARC":
                fh.seek(0)
                from . import gt1
                names = gt1.track_names(fh.read())
                if names:
                    items = [(str(i), f"{i:2d}  {n}", f"Track {i}: {n}")
                             for i, n in enumerate(names)]
    except Exception:
        items = _GT1_NO_TRACKS
    _GT1_TRACK_CACHE.clear()          # only the current file is worth keeping
    _GT1_TRACK_CACHE[key] = items
    return items


# ===========================================================================
# Operator
# ===========================================================================
class IMPORT_SCENE_OT_gt_psx_course(bpy.types.Operator, ImportHelper):
    """Import a PlayStation 1 Gran Turismo course

    Recognised by content, not extension: a GT1 `@(#)GT-ARC` COURSE.DAT, a GT2
    `@(#)GT-PS` .tro track object, or a GT2 .bso skybox. Gzipped files are
    unwrapped automatically.
    """

    bl_idname = "import_scene.gt_psx_course"
    bl_label = "Import Gran Turismo Course (PS1)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""

    filter_glob: StringProperty(
        default="*;*.dat;*.DAT;*.tro;*.trp;*.bso;*.bsp;*.gz",
        options={"HIDDEN"},
    )

    import_textures: BoolProperty(
        name="Import textures",
        description="Decode the course's PS1 textures. GT1 reads the named TIM "
                    "bundle paired with the track inside COURSE.DAT; GT2 replays "
                    "the same-name .trp sidecar. Both go into a 512x1024 VRAM "
                    "image that each face addresses through its own tpage/clut.",
        default=True,
    )

    # --- GT1 ----------------------------------------------------------------
    gt1_track_enum: EnumProperty(
        name="GT1 track",
        description="Which track to import. The list is read out of the "
                    "archive you have selected, so demo discs enumerate their "
                    "own set rather than retail's 63",
        items=_gt1_track_items,
    )

    gt1_track: IntProperty(
        name="GT1 track",
        description="Which track to import from COURSE.DAT, by index. Retail "
                    "holds 63 and the July 1997 prototype 14, so the dropdown "
                    "above is the easier way in; this is the escape hatch for "
                    "scripts and for archives the dropdown cannot read. Retail "
                    "0 is circuit (Grand Valley Speedway), 16 highway (Special "
                                                                            
                    "Stage Route 5), 32 testline (High Speed Ring). The names "
                    "are printed to the console on import.",
        default=0, min=0, max=255,
    )

    gt1_texture_mode: EnumProperty(
        name="GT1 textures",
        description="How to bring the course's textures across",
        items=(
            ("PAGE", "VRAM pages",
             "One 256x256 image per (texture page, palette) pair - what the "
             "console actually addresses, and what every UV in the file is "
             "relative to. Exact, but a track carries over a hundred of them "
             "and each material shows a whole page"),
            ("INDIVIDUAL", "Individual textures",
             "One image per texture, cropped to just that texture. Extents are "
             "not stored anywhere, so they are recovered by unioning the UV "
             "boxes of the faces that sample each page: highway's 1,374 boxes "
             "collapse to 141 textures. A palette is part of a texture's "
             "identity, so the same pixels drawn through two palettes stay two "
             "textures; identical images are merged"),
            ("ATLAS", "Single atlas",
             "The same recovered textures, packed once each into one image "
             "behind one material. Duplicates are dropped by content, so "
             "nothing repeats. A retail course lands in 1024x600 or so"),
        ),
        default="PAGE",
    )

    gt1_import_props: BoolProperty(
        name="Import GT1 instanced props",
        description="The buildings, signs, trees and grandstands the track "
                    "places around the roadway, each drawn at its most "
                    "detailed LOD level",
        default=True,
    )

    gt1_import_sky: BoolProperty(
        name="Import GT1 skydome",
        description="The course's sky, from BG.DAT beside COURSE.DAT. Which of "
                    "the ten a track uses comes from SYSTEM.DAT's @(#)GTENV "
                    "course table",
        default=True,
    )

    gt1_sky_radius: FloatProperty(
        name="GT1 sky radius",
        description="World radius to scale the dome to. There is no true scale "
                    "to recover - a skydome is drawn on the camera's rotation "
                    "with its translation dropped, so only each vertex's "
                    "direction matters",
        default=1500.0, min=1.0, soft_max=20000.0,
    )

    gt1_import_sprites: BoolProperty(
        name="Import GT1 billboards",
        description="Camera-facing tree and bush sprites (ShapeData slot 8). "
                    "5,764 across the 63 tracks.",
        default=True,
    )

    gt1_import_glare: BoolProperty(
        name="Import GT1 lamp glare",
        description="The glowing orbs on night-track lamp posts (ShapeData "
                    "slot 9), rebuilt as emissive quads the way the GT2 path "
                    "does. Only the night layouts have any - highway has 246, "
                    "daytime tracks none.",
        default=True,
    )

    gt1_import_lod_world: BoolProperty(
        name="Import GT1 low-detail world",
        description="The second ShapeData every chunk carries: a low-detail "
                    "copy of the same ground, about 10% of the faces with much "
                    "larger polygons. It lands on top of the roadway, so it "
                    "goes into its own collection and that collection is "
                    "unticked in the outliner -- leaving it enabled z-fights "
                    "with the track",
        default=True,
    )

    # --- GT2 ----------------------------------------------------------------
    gt2_texture_mode: EnumProperty(
        name="GT2 textures",
        description="How to bring the course's textures across. Same three "
                    "modes as GT1: the .tro stores a page, a palette and "
                    "corner texels per face, exactly as COURSE.DAT does",
        items=(
            ("PAGE", "VRAM pages",
             "One 256x256 image per (texture page, palette) pair - what the "
             "console addresses, and what every UV in the file is relative to. "
             "Exact, but a course carries over a hundred of them and each "
             "material shows a whole page"),
            ("INDIVIDUAL", "Individual textures",
             "One image per texture, cropped to just that texture. Extents are "
             "not stored anywhere, so they are recovered by unioning the UV "
             "boxes of the faces that sample each page. A palette is part of a "
             "texture's identity, so the same pixels drawn through two "
             "palettes stay two textures; identical images are merged"),
            ("ATLAS", "Single atlas",
             "The same recovered textures, packed once each into one image "
             "behind one material. Duplicates are dropped by content, so "
             "nothing repeats. The skydome has its own .bsp, so it gets its "
             "own atlas"),
        ),
        default="PAGE",
    )

    gt2_import_props: BoolProperty(
        name="Import GT2 instanced props",
        description="Import the LOD prop instances a GT2 .tro places around the "
                    "roadway - buildings, signs, trees and grandstands - each at "
                    "its most detailed level. Turn off to load the roadway "
                    "chunks alone.",
        default=True,
    )

    gt2_import_sky: BoolProperty(
        name="Import GT2 skybox",
        description="Also import the course's skydome. It is a separate file - "
                    "bgsobj/<name>.bso plus its .bsp textures - and .crsinfo "
                    "says which of the 34 skies a course uses, so this needs the "
                    "game volume's bgsobj/ and .crsinfo next to crsobj/. "
                    "Silently does nothing when only crsobj was extracted.",
        default=True,
    )

    gt2_sky_radius: FloatProperty(
        name="GT2 sky radius",
        description="World radius to scale the skydome to. There is no true "
                    "scale to recover - a skybox is drawn on the camera's "
                    "rotation with its translation dropped, so only each "
                    "vertex's direction matters. 1500 clears GT2's widest "
                    "course.",
        default=1500.0, min=1.0, soft_max=20000.0,
    )

    gt2_import_glare: BoolProperty(
        name="Import GT2 lamp glare",
        description="Import the glowing orbs on night-track lamp posts "
                    "(ShapeData slot 9) as emissive billboards. GT2 generates "
                    "these at runtime around a stored point, colour and size, "
                    "so they are rebuilt rather than textured - the sprite "
                    "exists in no file. Only 17 of the 126 courses have any, "
                    "all of them night or evening layouts.",
        default=True,
    )

    # --- Shared -------------------------------------------------------------
    prop_depth_bias: FloatProperty(
        name="Prop depth bias",
        description="How far to sink instanced props, to stop their ground "
                    "surfaces z-fighting with the roadway. The PS1 had no depth "
                    "buffer - it sorted primitives into an ordering table and "
                    "drew back to front - so a prop's apron could be authored "
                    "flush with the road and still render cleanly; a depth "
                    "buffer cannot separate that. Measured on Special Stage "
                    "Route 5: at 0 the closest prop surface sits 0.003 world "
                    "units from the road in GT1 and 0.009 in GT2. 0.15 clears "
                    "GT1, 0.3 clears both. 0 leaves the geometry exactly as "
                    "authored",
        default=0.0, min=0.0, soft_max=1.0, step=1, precision=3,
    )

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="General", icon="PREFERENCES")
        box.prop(self, "import_textures")

        box = layout.box()
        box.label(text="GT1 (COURSE.DAT)", icon="FILE_3D")
        # The dropdown only has anything to offer once a GT-ARC is selected;
        # until then, fall back to the index so the operator stays usable from
        # a script or a re-run.
        if _gt1_track_items(self, context) is not _GT1_NO_TRACKS:
            box.prop(self, "gt1_track_enum")
        else:
            box.prop(self, "gt1_track")
        box.prop(self, "gt1_texture_mode")
        box.prop(self, "gt1_import_props")
        if self.gt1_import_props:
            box.prop(self, "prop_depth_bias")
        box.prop(self, "gt1_import_sky")
        if self.gt1_import_sky:
            box.prop(self, "gt1_sky_radius")
        box.prop(self, "gt1_import_sprites")
        box.prop(self, "gt1_import_glare")
        box.prop(self, "gt1_import_lod_world")
        box.label(text="Every track lives in one archive; pick one above.",
                  icon="INFO")

        box = layout.box()
        box.label(text="GT2 (@(#)GT-PS .tro)", icon="FILE_3D")
        box.prop(self, "gt2_texture_mode")
        box.prop(self, "gt2_import_props")
        if self.gt2_import_props:
            box.prop(self, "prop_depth_bias")
        box.prop(self, "gt2_import_sky")
        if self.gt2_import_sky:
            box.prop(self, "gt2_sky_radius")
        box.prop(self, "gt2_import_glare")
        box.label(text="Textures come from the same-name .trp sidecar;",
                  icon="INFO")
        box.label(text="the sky from bgsobj/ + .crsinfo, if present.")

    def _gt1_effective_track(self, context):
        """The track index to import: the dropdown when it has a real list.

        A caller that passes `gt1_track` explicitly means it -- scripts predate
        the dropdown -- so an explicitly set index wins over the enum.
        """
        if self.properties.is_property_set("gt1_track"):
            return self.gt1_track
        if _gt1_track_items(self, context) is _GT1_NO_TRACKS:
            return self.gt1_track
        try:
            return int(self.gt1_track_enum)
        except (TypeError, ValueError):
            return self.gt1_track

    def execute(self, context):
        try:
            objects, verts, faces, shapes = import_psx_course(
                filepath=self.filepath,
                context=context,
                import_textures=self.import_textures,
                gt1_track=self._gt1_effective_track(context),
                gt1_import_sprites=self.gt1_import_sprites,
                gt1_import_glare=self.gt1_import_glare,
                gt1_import_lod_world=self.gt1_import_lod_world,
                gt1_import_props=self.gt1_import_props,
                gt1_import_sky=self.gt1_import_sky,
                gt1_sky_radius=self.gt1_sky_radius,
                gt1_texture_mode=self.gt1_texture_mode,
                gt2_import_props=self.gt2_import_props,
                gt2_import_sky=self.gt2_import_sky,
                gt2_import_glare=self.gt2_import_glare,
                gt2_sky_radius=self.gt2_sky_radius,
                gt2_texture_mode=self.gt2_texture_mode,
                prop_depth_bias=self.prop_depth_bias,
                report=print,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"PS1 course import failed: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"},
                    f"Imported {objects} object(s), {shapes} shape(s), "
                    f"{verts} verts, {faces} faces")
        return {"FINISHED"}


# ===========================================================================
# Viewport helpers
# ===========================================================================
# Both are generic material cleanups rather than format code, and both earn
# their place on PS1 output: the courses import a lot of alpha-blended sprite
# and glare quads, and in VRAM-page texture mode every UV is relative to a
# 256x256 page, so a clamped texture node shows the wrong thing at the seams.
def psx_disable_transparent_back_on_materials() -> int:
    """Apply the material-preview cleanup to every material in the file."""
    count = 0
    for mat in bpy.data.materials:
        try:
            mat.show_transparent_back = False
        except Exception:
            pass
        try:
            mat.use_backface_culling = False
        except Exception:
            pass
        count += 1
    return count


def psx_set_image_texture_nodes_repeat() -> int:
    """Set every image texture node's extension to Repeat."""
    count = 0
    for mat in bpy.data.materials:
        if not getattr(mat, "node_tree", None):
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                try:
                    node.extension = "REPEAT"
                    count += 1
                except Exception:
                    pass
    return count


class GT_PSX_OT_disable_transparent_back(bpy.types.Operator):
    """Disable Show Backface / backface culling on every material"""

    bl_idname = "gt_psx.disable_transparent_back"
    bl_label = "GT PSX: Disable Transparent Back on Materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = psx_disable_transparent_back_on_materials()
        self.report({"INFO"}, f"Updated {count} material(s)")
        return {"FINISHED"}


class GT_PSX_OT_set_texture_nodes_repeat(bpy.types.Operator):
    """Set all image texture nodes in the file to Repeat extension"""

    bl_idname = "gt_psx.set_texture_nodes_repeat"
    bl_label = "GT PSX: Set Image Texture Nodes to Repeat"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = psx_set_image_texture_nodes_repeat()
        self.report({"INFO"}, f"Set {count} image texture node(s) to Repeat")
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_gt_psx_course.bl_idname,
                         text="Gran Turismo Course (PS1: GT1/GT2)")


classes = (
    IMPORT_SCENE_OT_gt_psx_course,
    GT_PSX_OT_disable_transparent_back,
    GT_PSX_OT_set_texture_nodes_repeat,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
