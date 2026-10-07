"""Small EEVEE render setups for previews and pose checks."""
import bpy
from mathutils import Vector


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_lights(scene, scale=1.0, center=(0.0, 0.0, 1.0)):
    cx, cy, cz = center
    for name, offset, power, size in (("Key", (-2.2, -3.0, 1.6), 600, 2.5),
                                      ("Fill", (2.6, -2.2, 0.6), 260, 3.0),
                                      ("Rim", (0.8, 3.0, 1.8), 520, 2.0)):
        data = bpy.data.lights.new("tak." + name, "AREA")
        data.energy = power * scale * scale
        data.shape = "DISK"
        data.size = size * scale
        obj = bpy.data.objects.new("tak." + name, data)
        scene.collection.objects.link(obj)
        obj.location = (cx + offset[0] * scale, cy + offset[1] * scale, cz + offset[2] * scale)
        look_at(obj, center)
    world = scene.world or bpy.data.worlds.new("tak.World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.33, 0.35, 0.38, 1.0)
        bg.inputs["Strength"].default_value = 0.6


def setup_render(scene, width, height, transparent=False, samples=32):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scene.render.film_transparent = transparent
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in \
        [i.name for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items] else "None"
    try:
        scene.eevee.taa_render_samples = samples
    except AttributeError:
        pass


def camera(scene, location, target, lens=50.0, name="tak.Camera"):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_start = 0.01
    cam = bpy.data.objects.new(name, data)
    scene.collection.objects.link(cam)
    cam.location = location
    look_at(cam, target)
    scene.camera = cam
    return cam


def render_to(scene, path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def bounds(objects):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        mw = obj.matrix_world
        for v in mesh.vertices:
            p = mw @ v.co
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
        ev.to_mesh_clear()
    return lo, hi


def preview(scene, objects, path, width=600, height=800):
    lo, hi = bounds(objects)
    height_m = hi.z - lo.z
    center = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z + height_m * 0.5)
    setup_lights(scene, scale=max(height_m / 1.8, 0.5), center=center)
    setup_render(scene, width, height)
    distance = height_m * 2.6
    cam = camera(scene, (center[0] + distance * 0.28, center[1] - distance, center[2] + height_m * 0.06),
                 center, lens=50.0, name="tak.Preview")
    cam.data.sensor_fit = "VERTICAL"
    render_to(scene, path)
    return height_m
