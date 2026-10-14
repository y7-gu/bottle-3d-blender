"""
bottle.py - 矿泉水瓶 BPY 自动生成脚本 (Blender 5.2.x, EEVEE)

流程：
  1. 清空默认场景
  2. 加载二维标签素材，按其宽高比计算瓶身标签带高度（无拉伸）
  3. 车削生成透明瓶身（含标签带边线环，农夫山泉式：椭球弧肩 + 上身水波纹），红色不透明瓶盖
  4. UV：沿背面母线切开的标签带 -> 矩形 (0..1)，接缝藏于背面
  5. 材质：透明玻璃(Transmission 1.0, IOR 1.575)/ 不透明标签 / 不透明瓶盖
  6. EEVEE 渲染：半透明阴影，正面相机（接缝不可见）
  7. 清理临时数据块，保存 .blend 与渲染图
"""

import os
import math
import bmesh
import bpy
from mathutils import Vector

# ========================= CONFIG =========================
LABEL_IMAGE_PATH = r"c:\Users\yhb19\Desktop\kaohe\label.png"
OUTPUT_DIR       = r"C:\Users\yhb19\Documents\Trae-CN\default"
OUTPUT_RENDER    = os.path.join(OUTPUT_DIR, "bottle_render.png")
OUTPUT_BLEND     = os.path.join(OUTPUT_DIR, "bottle.blend")

# 瓶身尺寸 (米) —— 农夫山泉 550ml 风格比例（细高瓶身、长弧肩、短颈）
BODY_RADIUS      = 0.0315     # 瓶身半径
BODY_HEIGHT      = 0.2000     # 圆柱段高度
NECK_RADIUS      = 0.0135
NECK_HEIGHT      = 0.0280     # 瓶颈加长，露出明显瓶颈段
SHOULDER_HEIGHT  = 0.0450     # S 型弧形肩部（两端竖直相切）
WAVE_TOP         = 0.1770     # 波纹带顶部 z（与标签间留光身，仿参考图）
WAVE_HEIGHT      = 0.0300     # 水波纹区高度（农夫山泉标志性浮雕波）
WAVE_COUNT       = 3          # 波浪脊数量
WAVE_AMP         = 0.0008     # 波纹振幅
RIB_BOT          = 0.0280     # 下身环纹起始 z（仿参考图瓶底横纹）
RIB_HEIGHT       = 0.0350     # 环纹区高度
RIB_COUNT        = 3          # 环纹数量
RIB_AMP          = 0.0010     # 环纹振幅
LABEL_TOP_FRAC   = 0.725      # 标签带上沿比例（仿参考图：标签居中）
WATER_FILL_Z     = 0.1850     # 瓶内水位高度（波纹带上方，仿参考图）
CAP_RADIUS       = 0.0168
CAP_HEIGHT       = 0.0135
CAP_LIFT         = 0.0008     # 瓶盖顶高出瓶口
CAP_COLOR        = (1.0, 1.0, 1.0, 1.0)      # 瓶盖颜色：白色

SEGMENTS = 96                 # 圆周分段
FLIP_V   = False              # 标签上下方向微调（若渲染后文字倒置则改 True）

GLASS_BASE_COLOR  = (0.96, 0.97, 0.97, 1.0)   # 近白
GLASS_ROUGHNESS   = 0.02
GLASS_IOR         = 1.575
GLASS_REFRACTION_DEPTH = 0.0030
RENDER_SAMPLES    = 128


# ========================= UTILS =========================
def log(msg):
    print("[bottle] " + str(msg))


def set_socket(node, names, value):
    """按多个候选名找到 socket 并赋值。"""
    for n in names:
        if n in node.inputs:
            inp = node.inputs[n]
            try:
                inp.default_value = value
            except Exception:
                # 颜色等需要序列
                try:
                    for i, v in enumerate(value):
                        inp.default_value[i] = v
                except Exception:
                    pass
            return True
    return False


def clean_scene():
    """删除默认物体并清理孤立数据块。"""
    # 删除所有对象
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # 清理孤立数据
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                 bpy.data.curves, bpy.data.cameras, bpy.data.lights,
                 bpy.data.textures, bpy.data.node_groups):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)
    # 新场景集合
    if not bpy.context.scene.collection.objects:
        pass
    log("scene cleaned")


def purge_orphans():
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                 bpy.data.curves, bpy.data.cameras, bpy.data.lights,
                 bpy.data.node_groups, bpy.data.textures):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


# ========================= MATERIALS =========================
def make_glass_material():
    mat = bpy.data.materials.new("BottleGlass")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 300)
    out.location = (600, 300)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_socket(bsdf, ["Base Color"], GLASS_BASE_COLOR)
    set_socket(bsdf, ["Roughness"], GLASS_ROUGHNESS)
    set_socket(bsdf, ["Transmission Weight", "Transmission"], 1.0)
    set_socket(bsdf, ["IOR"], GLASS_IOR)
    set_socket(bsdf, ["Specular IOR Level", "Specular"], 0.5)
    # EEVEE 折射 / 透明阴影
    try: mat.use_raytrace_refraction = True   # 5.2 EEVEE 光线追踪折射（关键）
    except Exception: pass
    try: mat.use_screen_refraction = True     # 兼容旧版屏幕折射
    except Exception: pass
    try: mat.use_transparent_shadow = True
    except Exception: pass
    try: mat.blend_method = 'OPAQUE'
    except Exception: pass
    try: mat.refraction_depth = GLASS_REFRACTION_DEPTH
    except Exception: pass
    return mat


def make_label_material(image):
    mat = bpy.data.materials.new("Label")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "LabelUV"
    tex.image = image
    try: tex.interpolation = 'Linear'
    except Exception: pass
    tex.location = (-400, 300)
    uv.location = (-700, 200)
    bsdf.location = (100, 300)
    out.location = (400, 300)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in bsdf.inputs:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_socket(bsdf, ["Roughness"], 0.45)
    try: mat.blend_method = 'OPAQUE'
    except Exception: pass
    try: mat.use_transparent_shadow = True
    except Exception: pass
    return mat


def make_cap_material():
    mat = bpy.data.materials.new("Cap")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_socket(bsdf, ["Base Color"], CAP_COLOR)
    set_socket(bsdf, ["Roughness"], 0.55)          # 哑光：避免强光白色高光把红色冲成粉彩
    set_socket(bsdf, ["Specular IOR Level", "Specular"], 0.15)
    return mat


def make_ground_material():
    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_socket(bsdf, ["Base Color"], (0.88, 0.82, 0.72, 1.0))   # 暖米色台面（仿参考图）
    set_socket(bsdf, ["Roughness"], 0.7)
    return mat


def make_backdrop_material():
    """白色棚拍背景幕（仿参考图产品摄影布光）。"""
    mat = bpy.data.materials.new("Backdrop")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 0.86, 0.62, 1.0)   # 高饱和暖米色（AgX 会去饱和，需过饱和补偿）
    emit.inputs["Strength"].default_value = 1.5
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


# ========================= BUILD: BOTTLE BODY =========================
def build_bottle(z_label_low, z_label_high, cut_seg):
    z_wave_bot    = WAVE_TOP - WAVE_HEIGHT
    z_shoulder_top = BODY_HEIGHT + SHOULDER_HEIGHT
    z_neck_top    = z_shoulder_top + NECK_HEIGHT
    shoulder_steps = 16
    wave_steps    = 36
    rib_steps     = 24

    # 侧面轮廓 (r, z)：底(圆角) -> 下身环纹 -> 标签带 -> 光身 -> 水波纹 -> S 弧肩 -> 颈
    profile = []
    profile.append((0.0, 0.0))                                  # 底面中心
    profile.append((BODY_RADIUS - 0.0015, 0.0))                 # 底面外缘(内收)
    profile.append((BODY_RADIUS - 0.0002, 0.0010))              # 底部圆角
    profile.append((BODY_RADIUS, 0.0024))                       # 圆角结束接瓶壁
    for i in range(1, rib_steps + 1):                             # 下身环纹（仿参考图瓶底横纹）
        t = i / rib_steps
        r = BODY_RADIUS + RIB_AMP * math.sin(2.0 * math.pi * RIB_COUNT * t)
        profile.append((r, RIB_BOT + RIB_HEIGHT * t))
    idx_label_low = len(profile)
    profile.append((BODY_RADIUS, z_label_low))                  # 标签下沿
    profile.append((BODY_RADIUS, z_label_high))                 # 标签上沿
    idx_label_high = len(profile) - 1
    profile.append((BODY_RADIUS, z_wave_bot))                   # 光身到波纹起
    for i in range(1, wave_steps + 1):                            # 上身水波纹（农夫山泉标志性浮雕波）
        t = i / wave_steps
        r = BODY_RADIUS + WAVE_AMP * math.sin(2.0 * math.pi * WAVE_COUNT * t)
        profile.append((r, z_wave_bot + WAVE_HEIGHT * t))
    profile.append((BODY_RADIUS, BODY_HEIGHT))                  # 波纹结束回瓶壁
    for i in range(1, shoulder_steps + 1):                        # S 弧肩：余弦缓动，两端竖直相切，全程光滑无折角
        t = i / shoulder_steps
        e = 0.5 - 0.5 * math.cos(t * math.pi)
        r = NECK_RADIUS + (BODY_RADIUS - NECK_RADIUS) * (1.0 - e)
        profile.append((r, BODY_HEIGHT + SHOULDER_HEIGHT * t))
    profile.append((NECK_RADIUS, z_neck_top))                   # 颈顶
    profile.append((0.0, z_neck_top))                           # 顶面中心

    mesh = bpy.data.meshes.new("BottleBody")
    obj = bpy.data.objects.new("BottleBody", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("LabelUV")

    # 建环
    rings = []
    for (r, z) in profile:
        ring = []
        if r < 1e-6:
            ring.append(bm.verts.new((0.0, 0.0, z)))
        else:
            for s in range(SEGMENTS):
                a = (s / SEGMENTS) * 2.0 * math.pi
                ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z)))
        rings.append(ring)

    # 连接相邻环
    for i in range(len(rings) - 1):
        r0 = rings[i]
        r1 = rings[i + 1]
        is_band = (i == idx_label_low)  # 标签带位于 idx_label_low 与 idx_label_high 之间
        if len(r0) == 1 and len(r1) > 1:
            for s in range(SEGMENTS):
                a = r1[s]
                b = r1[(s + 1) % SEGMENTS]
                bm.faces.new((r0[0], a, b))
        elif len(r1) == 1 and len(r0) > 1:
            for s in range(SEGMENTS):
                a = r0[s]
                b = r0[(s + 1) % SEGMENTS]
                bm.faces.new((a, b, r1[0]))
        else:
            for s in range(SEGMENTS):
                v0 = r0[s]
                v1 = r0[(s + 1) % SEGMENTS]
                v2 = r1[(s + 1) % SEGMENTS]
                v3 = r1[s]
                f = bm.faces.new((v0, v1, v2, v3))
                if is_band:
                    pos = (s - cut_seg) % SEGMENTS
                    u_start = pos / SEGMENTS
                    u_end = (pos + 1) / SEGMENTS
                    v_low, v_high = 0.0, 1.0
                    if FLIP_V:
                        v_low, v_high = v_high, v_low
                    loops = f.loops
                    loops[0][uv_layer].uv = (u_start, v_low)   # low start
                    loops[1][uv_layer].uv = (u_end,   v_low)   # low end
                    loops[2][uv_layer].uv = (u_end,   v_high)  # high end
                    loops[3][uv_layer].uv = (u_start, v_high)  # high start

    # 重算外法线，平滑着色
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.uv_layers["LabelUV"].active_render = True
    mesh.uv_layers["LabelUV"].active = True

    return obj, z_neck_top, z_shoulder_top


# ========================= BUILD: CAP =========================
def build_cap(z_neck_top):
    cap_top = z_neck_top + CAP_LIFT
    cap_center_z = cap_top - CAP_HEIGHT / 2.0
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=CAP_RADIUS,
                                        depth=CAP_HEIGHT, location=(0, 0, cap_center_z))
    cap = bpy.context.object
    cap.name = "Cap"
    # 倒角顶边
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    bevel = cap.modifiers.new("Bevel", 'BEVEL')
    bevel.width = 0.0008
    bevel.segments = 3
    bevel.limit_method = 'ANGLE'
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    for p in cap.data.polygons:
        p.use_smooth = True
    return cap


def build_neck_ring(z):
    """瓶颈支撑环：让瓶颈段更真实、结构感更强。"""
    bpy.ops.mesh.primitive_torus_add(major_radius=NECK_RADIUS + 0.0016,
                                     minor_radius=0.0009,
                                     location=(0, 0, z))
    ring = bpy.context.object
    ring.name = "NeckRing"
    bpy.ops.object.shade_smooth()
    return ring


def build_water():
    """瓶内水体：顶面即水位线（仿参考图装水效果）。"""
    depth = WATER_FILL_Z - 0.005
    bpy.ops.mesh.primitive_cylinder_add(vertices=96,
                                        radius=BODY_RADIUS - 0.0030,
                                        depth=depth,
                                        location=(0, 0, 0.005 + depth / 2.0))
    w = bpy.context.object
    w.name = "Water"
    for p in w.data.polygons:
        p.use_smooth = True
    return w


def make_water_material():
    """清水：淡青透明（Alpha 混合避免与瓶身双层折射产生瑕疵）。"""
    mat = bpy.data.materials.new("Water")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_socket(bsdf, ["Base Color"], (0.72, 0.90, 0.94, 1.0))
    set_socket(bsdf, ["Roughness"], 0.05)
    set_socket(bsdf, ["Alpha"], 0.50)
    try: mat.blend_method = 'BLEND'
    except Exception: pass
    try: mat.use_transparent_shadow = True
    except Exception: pass
    try: mat.shadow_method = 'NONE'
    except Exception: pass
    return mat


# ========================= BUILD: GROUND =========================
def build_ground():
    bpy.ops.mesh.primitive_plane_add(size=0.6, location=(0, 0, -0.0008))
    g = bpy.context.object
    g.name = "Ground"
    return g


def build_backdrop():
    """背景幕：瓶身后方的自发光渐变板，用于体现玻璃折射。"""
    bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 0.30, 0.14))
    b = bpy.context.object
    b.name = "Backdrop"
    b.rotation_euler = (math.radians(90), 0, 0)  # 立起来，法线朝 -Y（朝向相机）
    return b


# ========================= ASSIGN MATERIALS =========================
def assign_body_materials(body, glass_mat, label_mat, z_label_low, z_label_high):
    body.data.materials.append(glass_mat)   # slot 0
    body.data.materials.append(label_mat)  # slot 1
    eps = 1e-5
    for p in body.data.polygons:
        cz = p.center.z
        if (z_label_low - eps) <= cz <= (z_label_high + eps):
            p.material_index = 1
        else:
            p.material_index = 0


# ========================= CAMERA & LIGHTS =========================
def setup_camera():
    z_center = (BODY_HEIGHT + NECK_HEIGHT + SHOULDER_HEIGHT) / 2.0 + 0.02
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 55.0
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    cam_obj.location = (0.0, -0.68, z_center)   # 全瓶入画且瓶占画面主体（仿参考图）
    target = Vector((0.0, 0.0, z_center - 0.02))
    direction = target - cam_obj.location
    rot = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot.to_euler()
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    return cam_obj


def setup_lights():
    # 主光：区域光，前上方，软阴影（半透明阴影）
    key_data = bpy.data.lights.new("Key", type='AREA')
    key_data.energy = 55.0
    key_data.size = 0.35
    key_data.use_shadow = True
    try: key_data.color = (1.0, 0.95, 0.88)   # 暖色主光（仿参考图）
    except Exception: pass
    try: key_data.shadow_soft_size = 0.15
    except Exception: pass
    key = bpy.data.objects.new("Key", key_data)
    key.location = (-0.18, -0.28, 0.42)       # 主光来自左前，阴影投向右侧（仿参考图）
    d = Vector((0, 0, 0.12)) - key.location
    key.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.collection.objects.link(key)

    # 辅光：太阳，背上方，勾边
    fill_data = bpy.data.lights.new("Fill", type='SUN')
    fill_data.energy = 1.2
    fill_data.use_shadow = False
    fill = bpy.data.objects.new("Fill", fill_data)
    fill.location = (-0.3, 0.4, 0.6)
    fill.rotation_euler = (math.radians(55), math.radians(-20), math.radians(40))
    bpy.context.collection.objects.link(fill)
    return key, fill


def setup_world():
    """世界背景：中性中灰，让自发光背景幕成为主背景。"""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Color"].default_value = (0.94, 0.86, 0.72, 1.0)   # 暖色环境光（仿参考图）
    bg.inputs["Strength"].default_value = 0.7
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return world


# ========================= RENDER =========================
def setup_render():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 1440            # 横幅构图（仿参考图）
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    try: scene.view_settings.view_transform = 'AgX'        # AgX 动态范围好；瓶盖靠加深基础色保饱和
    except Exception: pass
    try: scene.view_settings.look = 'None'
    except Exception: pass
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    ee = scene.eevee
    try: ee.taa_render_samples = RENDER_SAMPLES
    except Exception: pass
    try: ee.taa_samples = 32
    except Exception: pass
    try: ee.use_fast_gi = True
    except Exception: pass
    try: ee.gi_diffuse_bounces = 2
    except Exception: pass
    try: ee.use_raytracing = True                # 5.2 EEVEE 光线追踪总开关（折射必需）
    except Exception: pass
    try: ee.shadow_ray_count = 4
    except Exception: pass
    try: ee.shadow_step_count = 12
    except Exception: pass
    try: ee.shadow_resolution_scale = 1.0
    except Exception: pass
    try:
        if hasattr(ee, "ray_tracing_options"):
            rto = ee.ray_tracing_options
            for attr, val in (("resolution_scale", '1'), ("screen_trace_quality", 0.5),
                              ("screen_trace_thickness", 0.10), ("trace_max_roughness", 0.6),
                              ("use_denoise", True)):
                try: setattr(rto, attr, val)
                except Exception: pass
    except Exception: pass


# ========================= MAIN =========================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. 清空场景
    clean_scene()

    # 2. 加载标签素材并按宽高比计算标签带高度
    if not os.path.isfile(LABEL_IMAGE_PATH):
        raise RuntimeError("标签素材未找到: %s" % LABEL_IMAGE_PATH)
    image = bpy.data.images.load(LABEL_IMAGE_PATH, check_existing=True)
    img_w, img_h = image.size[0], image.size[1]
    if not img_w or not img_h:
        # 强制重载
        image.reload()
        img_w, img_h = image.size[0], image.size[1]
    aspect = (img_w / img_h) if img_h else 3.5
    log("label image %dx%d aspect=%.4f" % (img_w, img_h, aspect))

    circumference = 2.0 * math.pi * BODY_RADIUS
    band_height = circumference / aspect
    if band_height > BODY_HEIGHT * 0.55:
        band_height = BODY_HEIGHT * 0.55
    z_label_high = BODY_HEIGHT * LABEL_TOP_FRAC   # 仿参考图：标签带偏上放置，下部留透明瓶身
    z_label_low  = z_label_high - band_height
    log("band height=%.4f z_low=%.4f z_high=%.4f" % (band_height, z_label_low, z_label_high))

    # 背面母线：相机在 -Y，背面为 +Y，即角度 pi/2 -> s = SEG/4
    cut_seg = SEGMENTS // 4

    # 3. 建模（农夫山泉式：无螺纹，S 弧肩 + 明显瓶颈 + 支撑环）
    body, z_neck_top, z_shoulder_top = build_bottle(z_label_low, z_label_high, cut_seg)
    cap = build_cap(z_neck_top)
    neck_ring = build_neck_ring(z_shoulder_top + 0.004)
    water = build_water()
    ground = build_ground()
    backdrop = build_backdrop()

    # 4. 材质
    glass_mat  = make_glass_material()
    label_mat  = make_label_material(image)
    water_mat  = make_water_material()
    cap_mat    = make_cap_material()
    ground_mat = make_ground_material()
    backdrop_mat = make_backdrop_material()

    assign_body_materials(body, glass_mat, label_mat, z_label_low, z_label_high)
    neck_ring.data.materials.append(glass_mat)
    water.data.materials.append(water_mat)
    cap.data.materials.append(cap_mat)
    ground.data.materials.append(ground_mat)
    backdrop.data.materials.append(backdrop_mat)

    # 5. 相机 / 灯 / 世界
    setup_camera()
    setup_lights()
    setup_world()

    # 6. 渲染设置
    setup_render()

    # 7. 保存 .blend
    try:
        bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_BLEND)
        log("saved blend: %s" % OUTPUT_BLEND)
    except Exception as e:
        log("save blend failed: %s" % e)

    # 8. 渲染
    bpy.context.scene.render.filepath = OUTPUT_RENDER
    log("rendering -> %s" % OUTPUT_RENDER)
    bpy.ops.render.render(write_still=True)
    log("render done")

    # 9. 清理孤立数据块
    purge_orphans()
    log("done.")


if __name__ == "__main__":
    main()
