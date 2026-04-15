#!/usr/bin/env python3
"""
font2bezier.py  --  WOFF/TTF -> analytical bezier SDF GLSL

COMPILE-OPTIMISED:
  SDF functions  : const array + loop (not unrolled blocks)
  Glyph tables   : switch() (not if-chain)
  3D BVH         : global box -> per-glyph box -> bezier SDF

2D mode  --  NEVESD-compatible API, no texture, no Buffer A
             vec2 sc = vec2(x,y) in mainImage — animate freely

3D mode  --  Raymarched extrusion, Phong+Fresnel+cubemap
             makeStr3D / _end3D  : change text at runtime
             vec2 sc in sceneSDF : scale/animate text freely
             Mouse drag = orbit   |  release = auto pendulum

Demo mode --  --demo
             Bezier SDF font + opCutDispersal (Sébastien Durand 2022)
             Animated fractal break-apart effect, fully standalone
             No iChannel required.  Single-tab Shadertoy paste.
             Mouse drag = orbit   |  auto rotation when idle

Spell mode -- --spell
             Fontskin-style sequential character reveal animation.
             Each glyph sweeps in using an angular outline-progress
             approximation, with a bright frontier flash and outer glow.
             Fully standalone — no iChannel, no Buffer A.
"""
import sys, math, os, argparse
sys.path.insert(0, '/usr/local/lib/python3.12/dist-packages')
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.boundsPen import BoundsPen

ap = argparse.ArgumentParser()
ap.add_argument('woff')
ap.add_argument('--chars',   default='Hello World')
ap.add_argument('--size',    type=int,   default=48)
ap.add_argument('--scale',   default='1.0,1.0', help='2D vec2 sc e.g. 1.5,2.0')
ap.add_argument('--out',     default=None, metavar='DIR')
ap.add_argument('--extrude', type=float, default=None, metavar='DEPTH')
ap.add_argument('--bevel',   type=float, default=0.018)
ap.add_argument('--all-glyphs', action='store_true')
# ── fire mode ────────────────────────────────────────────────────────────────
ap.add_argument('--fire',           action='store_true',
                help='Generate rune-style fire shader (standalone, no buffer)')
ap.add_argument('--fire-ch',        type=float, default=0.13,
                help='Text height as fraction of screen height (default 0.13)')
ap.add_argument('--fire-sc',        default='1.0,2.5',
                help='vec2 sc scale for fire text (default 1.0,2.5)')
ap.add_argument('--fire-power',     type=float, default=0.5,
                help='Fire _Power constant (default 0.5)')
ap.add_argument('--fire-maxlen',    type=float, default=0.08,
                help='Fire _MaxLength — spread radius in screen units (default 0.08)')
ap.add_argument('--fire-dumping',   type=float, default=2.0,
                help='Fire _Dumping — falloff sharpness (default 2.0)')
ap.add_argument('--fire-slide',     type=float, default=1.5,
                help='Slide offset in lab-space units (default 1.5)')
ap.add_argument('--fire-slide-time',type=float, default=5.0,
                help='Seconds to slide in / out (default 5.0)')
ap.add_argument('--fire-hold-time', type=float, default=20.0,
                help='Seconds to hold at centre (default 20.0)')
# ── demo mode ─────────────────────────────────────────────────────────────────
ap.add_argument('--demo',           action='store_true',
                help='Generate cut-dispersal demo: font + animated fractal break-apart. '
                     'Standalone single-tab Shadertoy paste, no iChannel required.')
ap.add_argument('--demo-depth',     type=float, default=0.15,
                help='Extrusion depth for --demo (default 0.15)')
ap.add_argument('--demo-iters',     type=int,   default=5,
                help='opCutDispersal recursion depth for --demo (default 5, range 3-7)')
ap.add_argument('--demo-speed',     type=float, default=0.3,
                help='Break-apart animation speed multiplier (default 0.3)')
ap.add_argument('--demo-kdiv',      default='0.56,0.28,0.56',
                help='Gap widths vec3 kdiv for opCutDispersal (default 0.56,0.28,0.56)')
# ── spell mode ────────────────────────────────────────────────────────────────
ap.add_argument('--spell',           action='store_true',
                help='Generate Fontskin-style sequential character reveal animation')
ap.add_argument('--spell-ch',        type=float, default=0.12,
                help='Text height as fraction of screen height (default 0.12)')
ap.add_argument('--spell-draw',      type=float, default=3.0,
                help='Seconds to draw all characters (default 3.0)')
ap.add_argument('--spell-pause',     type=float, default=1.5,
                help='Hold time after full reveal before restart (default 1.5)')
ap.add_argument('--spell-color',     default='0.41,0.58,0.74',
                help='Base text color R,G,B (default 0.41,0.58,0.74 = steel blue)')
ap.add_argument('--spell-hue-speed', type=float, default=0.1,
                help='Hue drift speed multiplier (default 0.1, set 0 to disable)')
ap.add_argument('--spell-glow',      type=float, default=4.0,
                help='Outer glow radius in font units (default 4.0)')
# ── matrix mode ───────────────────────────────────────────────────────────────
ap.add_argument('--matrix',           action='store_true',
                help='Generate DisAInformation-style energy ripple + sweep effect '
                     '(always-on, no reveal — text pulses in size and sweeps a '
                     'diagonal highlight using time-based sideAngle)')
ap.add_argument('--matrix-ch-base',  type=float, default=0.10,
                help='Base character height as fraction of screen height (default 0.10)')
ap.add_argument('--matrix-ch-amp',   type=float, default=0.15,
                help='Character height animation amplitude (default 0.15)')
ap.add_argument('--matrix-ch-speed', type=float, default=0.30,
                help='Character height animation speed multiplier (default 0.30)')
ap.add_argument('--matrix-color',    default='0.020,0.263,0.082',
                help='Primary color R,G,B (default 0.020,0.263,0.082 = dark green)')
ap.add_argument('--matrix-glow',     type=float, default=20.0,
                help='Aura glow radius in font units (default 20.0)')
ap.add_argument('--matrix-tbuf',     type=float, default=0.70,
                help='Outline SDF buffer threshold 0-1 (default 0.70)')
ap.add_argument('--matrix-tgamma',   type=float, default=0.08,
                help='Outline smoothstep gamma (default 0.08)')
# ── sweep mode ────────────────────────────────────────────────────────────────
ap.add_argument('--sweep',               action='store_true',
                help='Animated tilted sweep bands over text. '
                     'Single-tab Shadertoy, no Buffer A. RGSS antialiased. '
                     'Ported from Fontskin doc6 preset.')
ap.add_argument('--sweep-ch',            type=float, default=0.23,
                help='Text height as fraction of screen height (default 0.23)')
ap.add_argument('--sweep-aura',          type=float, default=30.0,
                help='Aura radius in font units (default 30.0)')
ap.add_argument('--sweep-speed',         type=float, default=1.5,
                help='Sweep wave speed multiplier (default 1.5)')
ap.add_argument('--sweep-wave-width',    type=float, default=0.5,
                help='Sweep wave spatial period as screen fraction (default 0.5)')
ap.add_argument('--sweep-angle',         type=float, default=-20.0,
                help='Sweep band angle in degrees (0=horizontal, 90=vertical, default -20)')
ap.add_argument('--sweep-cr-power',     type=float, default=0.42,
                help='Exponent on Cr in wave denominator (default 0.42; higher=narrower bands)')
ap.add_argument('--sweep-highlight',    type=float, default=2.0,
                help='Highlight intensity multiplier — higher = brighter sweep bands (default 2.0)')
ap.add_argument('--sweep-pause',        type=float, default=0.0,
                help='Pause between sweep passes 0-1 (default 0=continuous, 0.7=long gap)')
ap.add_argument('--sweep-sup-scale',    type=float, default=0.35,
                help='Size of special symbols (® ™ ©) as fraction of normal (default 0.35)')
ap.add_argument('--sweep-sup-elev',     type=float, default=0.40,
                help='Elevation of special symbols as fraction of glyph height (default 0.40)')
ap.add_argument('--sweep-sup-kern',     type=float, default=0.35,
                help='Pull special symbols towards preceding char, fraction of glyph width (default 0.35)')
ap.add_argument('--sweep-base-color',    default='0.0,0.2,0.2',
                help='Base aura color R,G,B (default 0.0,0.2,0.2 = dark teal)')
ap.add_argument('--sweep-primary-color', default='0.05,0.1,0.1',
                help='Primary stroke color R,G,B (default 0.05,0.1,0.1 = dark teal)')
ap.add_argument('--sweep-secondary-color', default='0.478,0.275,0.175',
                help='Deep-interior accent R,G,B (default 0.478,0.275,0.175 = warm brown)')
# ── sweep-3d mode ─────────────────────────────────────────────────────────────
ap.add_argument('--sweep-3d',           action='store_true',
                help='Raymarched extruded 3D version of the sweep effect. '
                     'Reuses all --sweep color/animation/wave params. '
                     'Mouse drag=orbit, idle=auto-rotate. No Buffer A needed.')
ap.add_argument('--sweep-3d-depth',     type=float, default=0.15,
                help='Extrusion depth in world units (default 0.15)')
ap.add_argument('--sweep-3d-bevel',     type=float, default=0.018,
                help='Bevel/round radius at font edges (default 0.018)')
ap.add_argument('--sweep-3d-ty',        type=float, default=0.0,
                help='Vertical shift of text in world units — negative = down (default 0)')
ap.add_argument('--sweep-3d-dist',      type=float, default=3.8,
                help='Camera distance from text (default 3.8, larger = further away)')
# ── voodoo mode ────────────────────────────────────────────────────────────────
ap.add_argument('--voodoo',           action='store_true',
                help='Generate fractal-fold "VooDoo" glyph effect. '
                     'Single-tab Shadertoy, no Buffer A needed. '
                     'Fractal domain driven by outline arc-progress x SDF depth.')
ap.add_argument('--voodoo-ch',        type=float, default=0.12,
                help='Text height as fraction of screen height (default 0.12)')
ap.add_argument('--voodoo-color',     default='0.0,0.0,0.0',
                help='Cosine palette phase shift R,G,B. (0,0,0) = white/gray; '
                     '(0,0.333,0.667) = rainbow (default 0.0,0.0,0.0)')
ap.add_argument('--voodoo-speed',     type=float, default=0.4,
                help='Animation speed multiplier (default 0.4)')
ap.add_argument('--voodoo-iters',     type=int,   default=4,
                help='Fractal fold iterations (default 4, range 2-8)')

args = ap.parse_args()

try:    sc_x, sc_y = (float(x) for x in args.scale.split(','))
except: ap.error('--scale must be X,Y e.g. 1.5,2.0')
try:    fire_sc_x, fire_sc_y = (float(x) for x in args.fire_sc.split(','))
except: ap.error('--fire-sc must be X,Y e.g. 1.0,2.5')
try:    demo_kdiv_x, demo_kdiv_y, demo_kdiv_z = (float(x) for x in args.demo_kdiv.split(','))
except: ap.error('--demo-kdiv must be X,Y,Z e.g. 0.56,0.28,0.56')
try:    spell_r, spell_g, spell_b = (float(x) for x in args.spell_color.split(','))
except: ap.error('--spell-color must be R,G,B e.g. 0.41,0.58,0.74')
try:    matrix_r, matrix_g, matrix_b = (float(x) for x in args.matrix_color.split(','))
except: ap.error('--matrix-color must be R,G,B e.g. 0.020,0.263,0.082')
try:    sweep_br, sweep_bg, sweep_bb = (float(x) for x in args.sweep_base_color.split(','))
except: ap.error('--sweep-base-color must be R,G,B e.g. 0.059,0.008,0.196')
try:    sweep_pr, sweep_pg, sweep_pb = (float(x) for x in args.sweep_primary_color.split(','))
except: ap.error('--sweep-primary-color must be R,G,B e.g. 0.0,0.0,0.0')
try:    sweep_sr, sweep_sg, sweep_sb = (float(x) for x in args.sweep_secondary_color.split(','))
except: ap.error('--sweep-secondary-color must be R,G,B e.g. 0.278,0.275,0.275')
try:    voodoo_cr, voodoo_cg, voodoo_cb = (float(x) for x in args.voodoo_color.split(','))
except: ap.error('--voodoo-color must be R,G,B e.g. 0.0,0.333,0.667')

outdir = os.path.abspath(args.out) if args.out else os.getcwd()
os.makedirs(outdir, exist_ok=True)

font = TTFont(args.woff)
UPM  = font['head'].unitsPerEm
cmap = font.getBestCmap()
hmtx = font['hmtx'].metrics
gs   = font.getGlyphSet()
name = os.path.splitext(os.path.basename(args.woff))[0]
SZ   = args.size;  PS = SZ / UPM

os2     = font.get('OS/2')
asc_fu  = os2.sTypoAscender if os2 else int(UPM*.8)
dsc_fu  = os2.sTypoDescender if os2 else -int(UPM*.2)
LINE_H  = (asc_fu - dsc_fu) * PS
FONT_BASE = (-dsc_fu) * PS

print(f"Font: {name}  UPM={UPM}  SZ={SZ}px")
print(f"LINE_H={LINE_H:.2f}  FONT_BASE={FONT_BASE:.2f}")

# ── geometry ────────────────────────────────────────────────────────────────
def midpt(a,b): return ((a[0]+b[0])/2,(a[1]+b[1])/2)
def cubic_to_quads(p0,p1,p2,p3,d=0):
    if d>=5:
        m01=midpt(p0,p1);m12=midpt(p1,p2);m23=midpt(p2,p3)
        m012=midpt(m01,m12);m123=midpt(m12,m23);mid=midpt(m012,m123)
        return [(p0,m012,mid),(mid,m123,p3)]
    q1=((3*p1[0]-p0[0])/2,(3*p1[1]-p0[1])/2)
    q2=((3*p2[0]-p3[0])/2,(3*p2[1]-p3[1])/2)
    if math.hypot(q1[0]-q2[0],q1[1]-q2[1])<0.5:
        return [(p0,((q1[0]+q2[0])/2,(q1[1]+q2[1])/2),p3)]
    m01=midpt(p0,p1);m12=midpt(p1,p2);m23=midpt(p2,p3)
    m012=midpt(m01,m12);m123=midpt(m12,m23);mid=midpt(m012,m123)
    return cubic_to_quads(p0,m01,m012,mid,d+1)+cubic_to_quads(mid,m123,m23,p3,d+1)
def fu2fp(pt): return (pt[0]*PS, pt[1]*PS+FONT_BASE)

# Synthetic glyph contour store — checked by get_contours before hitting the font
_synth_data = {}   # glyph_name -> list of contour segments

def get_contours(gname):
    # Synthetic glyphs (e.g. ® built from circles + scaled R)
    if gname in _synth_data:
        return _synth_data[gname]
    try:
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        pen = DecomposingRecordingPen(gs)
    except (ImportError, AttributeError):
        pen = RecordingPen()
    try: gs[gname].draw(pen)
    except: return []
    out=[]; segs=[]; cur=(0,0); start=(0,0)
    for op,vals in pen.value:
        if op=='moveTo':
            if segs: out.append(segs); segs=[]
            start=cur=fu2fp(vals[0])
        elif op=='lineTo':
            for pt in vals:
                e=fu2fp(pt)
                if e!=cur: segs.append(('L',cur,e)); cur=e
        elif op=='qCurveTo':
            pts=[fu2fp(v) for v in vals]; offs,on=pts[:-1],pts[-1]
            if not offs:
                if on!=cur: segs.append(('L',cur,on))
            elif len(offs)==1: segs.append(('Q',cur,offs[0],on))
            else:
                p0=cur
                for i,off in enumerate(offs):
                    p2=on if i+1==len(offs) else midpt(off,offs[i+1])
                    segs.append(('Q',p0,off,p2)); p0=p2
            cur=on
        elif op=='curveTo':
            cpts=[fu2fp(v) for v in vals]
            for q in cubic_to_quads(cur,cpts[0],cpts[1],cpts[2]):
                segs.append(('Q',q[0],q[1],q[2]))
            cur=cpts[-1]
        elif op in ('endPath','closePath'):
            if cur!=start: segs.append(('L',cur,start))
            if segs: out.append(segs); segs=[]
    if segs: out.append(segs)
    return out
def glyph_bbox(gname):
    if gname in _synth_data:
        # compute bbox from synthetic contour segments
        xs=[]; ys=[]
        for segs in _synth_data[gname]:
            for seg in segs:
                for p in seg[1:]:
                    xs.append(p[0]); ys.append(p[1])
        if xs: return (min(xs),min(ys),max(xs),max(ys))
        return (0,FONT_BASE,1,FONT_BASE+1)
    pen=BoundsPen(gs)
    try: gs[gname].draw(pen)
    except: return (0,FONT_BASE,1,FONT_BASE+1)
    if pen.bounds is None: return (0,FONT_BASE,1,FONT_BASE+1)
    x0,y0,x1,y1=pen.bounds
    return (x0*PS,y0*PS+FONT_BASE,x1*PS,y1*PS+FONT_BASE)
def v(p): return f"vec2({p[0]:.4f},{p[1]:.4f})"

def _circle_segs(cx, cy, r, n=24, cw=False):
    """Circle as line segments in get_contours() format."""
    pts = [(cx + r*math.cos(math.tau*i/n * (-1 if cw else 1)),
            cy + r*math.sin(math.tau*i/n * (-1 if cw else 1)))
           for i in range(n)]
    return [('L', pts[i], pts[(i+1)%n]) for i in range(n)]

def _build_synth_reg():
    """Synthesize ® = circle ring + scaled R.  Registers into cmap + _synth_data."""
    SYNTH = '__reg__'
    os2    = font.get('OS/2')
    cap_h  = (getattr(os2, 'sCapHeight', None) or int(UPM * 0.7)) * PS
    # Ring geometry: sits at cap-height centre
    cy     = FONT_BASE + cap_h * 0.5
    adv_w  = cap_h * 1.05           # advance slightly wider than a square
    cx     = adv_w * 0.5
    r_out  = cap_h * 0.46
    r_in   = cap_h * 0.32
    contours = [
        _circle_segs(cx, cy, r_out, 28, cw=False),   # outer ring (CCW)
        _circle_segs(cx, cy, r_in,  28, cw=True),    # inner hole (CW)
    ]
    # Scale the font's R glyph to fit inside the inner circle
    if ord('R') in cmap:
        r_conts = get_contours(cmap[ord('R')])
        if r_conts:
            xs=[p for seg in [s for c in r_conts for s in c] for p in (seg[1][0],seg[-1][0])]
            ys=[p for seg in [s for c in r_conts for s in c] for p in (seg[1][1],seg[-1][1])]
            bx0,by0,bx1,by1 = min(xs),min(ys),max(xs),max(ys)
            bw,bh = bx1-bx0, by1-by0
            scale  = (r_in * 1.25) / max(bw, bh) if max(bw,bh) > 0 else 1.0
            ox = cx - (bx0 + bw/2)*scale
            oy = cy - (by0 + bh/2)*scale
            def xf(pt): return (pt[0]*scale+ox, pt[1]*scale+oy)
            for cont in r_conts:
                contours.append([
                    (seg[0],) + tuple(xf(p) for p in seg[1:])
                    for seg in cont])
    _synth_data[SYNTH] = contours
    cmap[0xae] = SYNTH
    # Register advance width so meta_vals picks it up
    hmtx[SYNTH] = (int(adv_w / PS), 0)
    print(f"  Synthesized ® glyph  cap_h={cap_h:.1f}px  adv={adv_w:.1f}px")

# ── SDF generators ───────────────────────────────────────────────────────────
def _sdf_body(out, contours, safe=None):
    Ls=[]; Qs=[]
    for segs in contours:
        for seg in segs:
            if seg[0]=='L': Ls.append((seg[1],seg[2]))
            else:           Qs.append((seg[1],seg[2],seg[3]))
    out.append("  float d=1e9; int w=0;")
    if Ls:
        n=len(Ls)
        data=','.join(f"vec4({a[0]:.4f},{a[1]:.4f},{b[0]:.4f},{b[1]:.4f})" for a,b in Ls)
        out.append(f"  const vec4 LS[{n}]=vec4[]({data});")
        out.append(f"  for(int i=0;i<{n};i++){{vec2 a=LS[i].xy,b=LS[i].zw;d=min(d,LD(p,a,b));w+=LW(p,a,b);}}")
    if Qs:
        n=len(Qs)
        da=','.join(f"vec4({a[0]:.4f},{a[1]:.4f},{c[0]:.4f},{c[1]:.4f})" for a,c,b in Qs)
        db=','.join(f"vec2({b[0]:.4f},{b[1]:.4f})" for a,c,b in Qs)
        out.append(f"  const vec4 QA[{n}]=vec4[]({da});")
        out.append(f"  const vec2 QB[{n}]=vec2[]({db});")
        out.append(f"  for(int i=0;i<{n};i++){{vec2 a=QA[i].xy,b=QA[i].zw,c=QB[i];d=min(d,QD(p,a,b,c));w+=QW(p,a,b,c);}}")
    out.append("  return d*(w!=0?-1.:1.);}")

def _bbox_params(contours):
    all_pts=[pt for segs in contours for seg in segs for pt in seg[1:]]
    xs=[p[0] for p in all_pts]; ys=[p[1] for p in all_pts]; pad=0.5
    return ((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,
            (max(xs)-min(xs))/2+pad,(max(ys)-min(ys))/2+pad)

def gen_sdf_fn(fn, contours):
    if not any(seg for segs in contours for seg in segs):
        return f"float {fn}(vec2 p){{return 1e9;}}"
    cx,cy,rx,ry=_bbox_params(contours)
    out=[f"float {fn}(vec2 p){{"]
    out.append(f"  if(!all(lessThan(abs(p-{v((cx,cy))}),{v((rx,ry))}))) return 1e9;")
    _sdf_body(out,contours)
    return '\n'.join(out)

def gen_sdf_fn_fire(fn, contours):
    if not any(seg for segs in contours for seg in segs):
        return f"float {fn}(vec2 p){{return 1e9;}}"
    out=[f"float {fn}(vec2 p){{"]
    _sdf_body(out,contours)
    return '\n'.join(out)

def gen_sdf_fn_3d(fn, contours, bevel_fp=0.0):
    if not any(seg for segs in contours for seg in segs):
        return f"float {fn}(vec2 p){{return 1e9;}}"
    cx,cy,rx,ry=_bbox_params(contours)
    safe=bevel_fp+0.08
    out=[f"float {fn}(vec2 p){{"]
    out.append(f"  vec2 _bq=abs(p-{v((cx,cy))})-{v((rx,ry))};")
    out.append(f"  if(any(greaterThanEqual(_bq,vec2(0.)))) return max(length(max(_bq,0.)),{safe:.4f});")
    _sdf_body(out,contours)
    return '\n'.join(out)

def tbl(fn, entries, side_effect=''):
    L=[f"vec4 {fn}(int c){{"]
    if side_effect: L.append(f"  {side_effect}")
    L.append("  switch(c){")
    for code,vals in sorted(entries.items()):
        L.append(f"  case {code}: return vec4({','.join(f'{vv:.4f}' for vv in vals)});")
    L.append("  default: return vec4(0.);\n  }\n}")
    return '\n'.join(L)

def adv_tbl(entries):
    L=["float getGlyphAdv(int c){","  switch(c){"]
    for code,vals in sorted(entries.items()):
        L.append(f"  case {code}: return {vals[2]:.4f};")
    L.append("  default: return 0.;\n  }\n}")
    return '\n'.join(L)

def glyph_sdf_dispatch(glyph_fns):
    L=["float glyphSDF(int code, vec2 p){","  switch(code){"]
    for code,fn in sorted(glyph_fns.items()):
        L.append(f"  case {code}: return {fn}(p);")
    L.append("  default: return 1e9;\n  }\n}")
    return '\n'.join(L)

# ── process characters ───────────────────────────────────────────────────────
# Decode \uXXXX and \xXX escape sequences typed literally in --chars
import re as _re
def _decode_escapes(s):
    s = _re.sub(r'\\[uU]([0-9a-fA-F]{4,8})',
                lambda m: chr(int(m.group(1), 16)), s)
    s = _re.sub(r'\\x([0-9a-fA-F]{2})',
                lambda m: chr(int(m.group(1), 16)), s)
    return s
chars = _decode_escapes(args.chars)

# Known shorthand substitutions: typed_form -> (unicode_char, display_name)
_SPECIAL = {
    '(R)' : ('\u00ae', 'REGISTERED SIGN ®'),
    '(r)' : ('\u00ae', 'REGISTERED SIGN ®'),
    '(TM)': ('\u2122', 'TRADE MARK SIGN ™'),
    '(tm)': ('\u2122', 'TRADE MARK SIGN ™'),
    '(C)' : ('\u00a9', 'COPYRIGHT SIGN ©'),
    '(c)' : ('\u00a9', 'COPYRIGHT SIGN ©'),
    '(P)' : ('\u2117', 'SOUND RECORDING ℗'),
}
for shorthand, (uchar, label) in _SPECIAL.items():
    if shorthand in chars:
        chars = chars.replace(shorthand, uchar)

# Report special character status
_used_special = {uc: label for (_, (uc, label)) in _SPECIAL.items() if uc in chars}
if _used_special:
    print("\nSpecial characters:")
    for uc, label in _used_special.items():
        code = ord(uc)
        if code in cmap:
            print(f"  U+{code:04X} {label}  -> found in font")
        else:
            # Only ® has synthesis support; others will be skipped (rendered as space)
            if code == 0xae:
                print(f"  U+{code:04X} {label}  -> NOT in font, synthesizing from R + circle ring")
            else:
                print(f"  U+{code:04X} {label}  -> NOT in font, will render as space")
                print(f"           (tip: check if font has this glyph or use a different font)")

# (R) → synthesize ® from circles + scaled R if not in font
if '\u00ae' in chars and 0xae not in cmap:
    _build_synth_reg()

# Warn about any characters not found in the font
_missing = [c for c in chars if c != ' ' and ord(c) not in cmap]
if _missing:
    _miss_str = ' '.join(f"'{c}' U+{ord(c):04X}" for c in dict.fromkeys(_missing))
    print(f"\nWARNING: These characters are NOT in the font and will be skipped:")
    print(f"  {_miss_str}")
    print(f"  The font only contains {len(cmap)} glyphs.")
    print(f"  Try: --chars \"{args.chars.replace(chr(ord(_missing[0])), '')}\"")
    print()
ucodes     = sorted(cmap.keys()) if args.all_glyphs else \
             sorted(set(ord(c) for c in chars if ord(c) in cmap))
ucodes_sdf = sorted(set(ord(c) for c in chars if ord(c) in cmap))
if args.all_glyphs:
    print(f"--all-glyphs: {len(ucodes)} glyphs in tables, "
          f"{len(ucodes_sdf)} SDF functions (--chars only)")

glyph_fns={}; rect_vals={}; meta_vals={}; all_fn_src=[]; glyph_bboxes={}

for code in ucodes:
    gname=cmap[code]
    if gname not in gs and gname not in _synth_data: continue
    adv_fp=hmtx.get(gname,(UPM//2,0))[0]*PS
    if code==32:
        meta_vals[code]=(0.0,0.0,adv_fp,0.0)
        rect_vals[code]=(0.0,FONT_BASE,0.01,0.01); continue
    x0,y0,x1,y1=glyph_bbox(gname)
    meta_vals[code]=(x0,LINE_H-y1,adv_fp,y1-y0)
    rect_vals[code]=(x0,y0,x1-x0,y1-y0)

for code in ucodes_sdf:
    gname=cmap[code]
    if (gname not in gs and gname not in _synth_data) or code==32: continue
    if code not in meta_vals: continue
    contours=get_contours(gname)
    if contours:
        fn=f"sdf{code}"; glyph_fns[code]=fn
        all_fn_src.append(gen_sdf_fn(fn,contours))
        all_pts=[pt for segs in contours for seg in segs for pt in seg[1:]]
        _xs=[p[0] for p in all_pts]; _ys=[p[1] for p in all_pts]
        glyph_bboxes[code]=((min(_xs)+max(_xs))/2,(min(_ys)+max(_ys))/2,
                            (max(_xs)-min(_xs))/2+0.5,(max(_ys)-min(_ys))/2+0.5)
        print(f"  '{chr(code)}' U+{code:04X}: {len(contours)} contour(s), "
              f"{sum(len(s) for s in contours)} segs")

total_adv=sum(meta_vals.get(ord(c),(0,0,0,0))[2] for c in chars if ord(c) in cmap)
rect_tbl =tbl("getGlyphRect",rect_vals,"_GC=c;")
meta_tbl =tbl("getGlyphMeta",meta_vals)
disp='\n'.join(f"  if(_GC=={code}) return {fn}(p);" for code,fn in sorted(glyph_fns.items()))

def char_tok(c):
    if c==' ': return '_'
    if c.isalpha(): return '_'+c
    M={'.':'_DOT',',':'_COM','-':'_SUB',':':'_COL',';':'_SEM','!':'_EX',
       '?':'_QUE','(':'_LPR',')':'_RPR',"'":'_QT','"':'_DBQ','_':'_UN'}
    return M.get(c,'_'+c if c.isdigit() else '')
tokens=' '.join(t for c in chars if (t:=char_tok(c)))

# ── shared GLSL strings ──────────────────────────────────────────────────────
CHAR_DEFINES="""\
#define _    32,
#define _EX  33,
#define _DBQ 34,
#define _NUM 35,
#define _DOL 36,
#define _PER 37,
#define _AMP 38,
#define _QT  39,
#define _LPR 40,
#define _RPR 41,
#define _MUL 42,
#define _ADD 43,
#define _COM 44,
#define _SUB 45,
#define _DOT 46,
#define _DIV 47,
#define _COL 58,
#define _SEM 59,
#define _LES 60,
#define _EQ  61,
#define _GE  62,
#define _QUE 63,
#define _AT  64,
#define _LBR 91,
#define _ANTI 92,
#define _RBR 93,
#define _HAT 94,
#define _UN  95,
#define _GRV 96,
#define _0 48,
#define _1 49,
#define _2 50,
#define _3 51,
#define _4 52,
#define _5 53,
#define _6 54,
#define _7 55,
#define _8 56,
#define _9 57,
#define _A 65,
#define _B 66,
#define _C 67,
#define _D 68,
#define _E 69,
#define _F 70,
#define _G 71,
#define _H 72,
#define _I 73,
#define _J 74,
#define _K 75,
#define _L 76,
#define _M 77,
#define _N 78,
#define _O 79,
#define _P 80,
#define _Q 81,
#define _R 82,
#define _S 83,
#define _T 84,
#define _U 85,
#define _V 86,
#define _W 87,
#define _X 88,
#define _Y 89,
#define _Z 90,
#define _a  97,
#define _b  98,
#define _c  99,
#define _d 100,
#define _e 101,
#define _f 102,
#define _g 103,
#define _h 104,
#define _i 105,
#define _j 106,
#define _k 107,
#define _l 108,
#define _m 109,
#define _n 110,
#define _o 111,
#define _p 112,
#define _q 113,
#define _r 114,
#define _s 115,
#define _t 116,
#define _u 117,
#define _v 118,
#define _w 119,
#define _x 120,
#define _y 121,
#define _z 122,"""

MACROS_2D=r"""
#define makeStr(name) \
float name(vec2 _FSTU) { \
    if(_FSTU.x<0.||_FSTU.y<0.||_FSTU.y>LINE_H) return 0.0; \
    const int _FSTC[] = int[](

#define _end 0); \
    float _FSTX=0.0; \
    for(int _FSTK=0;_FSTK<_FSTC.length()-1;_FSTK++) { \
        vec4 _FSTM=getGlyphMeta(_FSTC[_FSTK]); \
        if(_FSTU.x<_FSTX+_FSTM.z) { \
            vec4 _FSTR=getGlyphRect(_FSTC[_FSTK]); \
            vec2 _FSTB=vec2(_FSTM.x,LINE_H-_FSTM.y-_FSTM.w); \
            vec2 _FSTL=(_FSTU-vec2(_FSTX,0.)-_FSTB)/vec2(_FSTR.z*ATLAS_W,_FSTM.w); \
            return (all(greaterThanEqual(_FSTL,vec2(0.)))&&all(lessThanEqual(_FSTL,vec2(1.)))) \
                ? _atlasAlpha(_FSTR.xy+_FSTL*_FSTR.zw) : 0.0; \
        } \
        _FSTX+=_FSTM.z; \
    } \
    return 0.0; \
}

#define makeColorStr2D(name) \
vec4 name(vec2 _C2DU) { \
    if(_C2DU.x<0.||_C2DU.y<0.||_C2DU.y>LINE_H) return vec4(0.); \
    const int _C2DC[] = int[](

#define _endC2D 0); \
    float _C2DX=0.0; \
    for(int _C2DK=0;_C2DK<_C2DC.length()-1;_C2DK++) { \
        vec4 _C2DM=getGlyphMeta(_C2DC[_C2DK]); \
        if(_C2DU.x<_C2DX+_C2DM.z) { \
            vec4 _C2DR=getGlyphRect(_C2DC[_C2DK]); \
            vec2 _C2DB=vec2(_C2DM.x,LINE_H-_C2DM.y-_C2DM.w); \
            vec2 _C2DL=(_C2DU-vec2(_C2DX,0.)-_C2DB)/vec2(_C2DR.z*ATLAS_W,_C2DM.w); \
            float _C2DA=(all(greaterThanEqual(_C2DL,vec2(0.)))&&all(lessThanEqual(_C2DL,vec2(1.)))) \
                ? _atlasAlpha(_C2DR.xy+_C2DL*_C2DR.zw) : 0.; \
            return vec4(1.,1.,1.,_C2DA); \
        } \
        _C2DX+=_C2DM.z; \
    } \
    return vec4(0.); \
}
"""

MACROS_3D=r"""
#define makeStr3D(name) \
float name(vec2 p) { \
    const int _3DC[] = int[](

#define _end3D 0); \
    float _3DT=0.; \
    for(int _3DK=0;_3DK<_3DC.length()-1;_3DK++) _3DT+=getGlyphAdv(_3DC[_3DK]); \
    float _3DX=0.,d=1e9; \
    for(int _3DK=0;_3DK<_3DC.length()-1;_3DK++) { \
        d=min(d,glyphSDF(_3DC[_3DK],vec2(p.x+_3DT*.5-_3DX,p.y))); \
        _3DX+=getGlyphAdv(_3DC[_3DK]); \
    } \
    return d; \
}
"""

BEZIER="""\
float dot2(vec2 v){return dot(v,v);}
float LD(vec2 p,vec2 a,vec2 b){
    vec2 pa=p-a,ba=b-a;
    return length(pa-ba*clamp(dot(pa,ba)/dot(ba,ba),0.,1.));
}
int LW(vec2 p,vec2 a,vec2 b){
    if((a.y>p.y)==(b.y>p.y)) return 0;
    float t=(p.y-a.y)/(b.y-a.y);
    if(a.x+t*(b.x-a.x)<p.x) return 0;
    return (b.y>a.y)?1:-1;
}
float QD(vec2 pos,vec2 p0,vec2 p1,vec2 p2){
    vec2 a=p1-p0,b=p0-2.*p1+p2,c=a*2.,d=p0-pos;
    float kk=1./dot(b,b),kx=kk*dot(a,b),
          ky=kk*(2.*dot(a,a)+dot(d,b))/3.,kz=kk*dot(d,a);
    float p=ky-kx*kx,q=kx*(2.*kx*kx-3.*ky)+kz;
    float p3=p*p*p,h=q*q+4.*p3,res;
    if(h>=0.){
        h=sqrt(h); vec2 x=(vec2(h,-h)-q)/2.;
        vec2 uv=sign(x)*pow(abs(x),vec2(1./3.));
        float t=clamp(uv.x+uv.y-kx,0.,1.);
        res=dot2(d+(c+b*t)*t);
    }else{
        float z=sqrt(-p),v=acos(q/(p*z*2.))/3.,m=cos(v),n=sin(v)*1.732050808;
        vec3 t3=clamp(vec3(m+m,-n-m,n-m)*z-kx,0.,1.);
        float dx=dot2(d+(c+b*t3.x)*t3.x),dy=dot2(d+(c+b*t3.y)*t3.y);
        res=min(dx,dy);
    }
    return sqrt(max(res,0.));
}
int QW(vec2 p,vec2 p0,vec2 p1,vec2 p2){
    float A=p0.y-2.*p1.y+p2.y,B=2.*(p1.y-p0.y),C=p0.y-p.y;
    int cnt=0;
    if(abs(A)<1e-6){
        if(abs(B)>1e-6){float t=-C/B;
            if(t>=0.&&t<=1.){float x=mix(mix(p0.x,p1.x,t),mix(p1.x,p2.x,t),t);
                if(x>p.x) cnt+=(p2.y>p0.y)?1:-1;}}
    }else{float disc=B*B-4.*A*C;
        if(disc>=0.){float sq=sqrt(disc);
            for(int s=-1;s<=1;s+=2){float t=(-B+float(s)*sq)/(2.*A);
                if(t>=0.&&t<=1.){float x=mix(mix(p0.x,p1.x,t),mix(p1.x,p2.x,t),t);
                    if(x>p.x){float dy=2.*((1.-t)*(p1.y-p0.y)+t*(p2.y-p1.y));
                        cnt+=(dy>0.)?1:-1;}}}}}
    return cnt;
}"""

_US=[('\u2014','--'),('\u2013','-'),('\u2500','-'),('\u2502','|'),
     ('\xd7','x'),('\u2018',"'"),('\u2019',"'"),('\u201c','"'),('\u201d','"')]
def aclean(s):
    for o,n in _US: s=s.replace(o,n)
    return ''.join(c if ord(c)<128 else '-' for c in s)

font_comment = f"//  Font: {name} ({os.path.basename(args.woff)})  --  chars: \"{aclean(chars)}\""

# ── 2D shader ────────────────────────────────────────────────────────────────
glsl2d=f"""\
// {name}  --  Bezier SDF font  (NEVESD-compatible, no texture)
{font_comment}
// iquilezles.org/articles/distance -- exact quadratic bezier SDF
// Fast compile: const-array loops + switch() tables
// Scale vec2 sc in mainImage -- animate freely with sin(iTime)

{CHAR_DEFINES}
{MACROS_2D}

const float ATLAS_W   = 1.0;
const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

{chr(10).join(all_fn_src)}

int _GC = 0;

{rect_tbl}

{meta_tbl}

float cSDF(vec2 p) {{
{disp}
  return 1e9;
}}
float _atlasAlpha(vec2 pos) {{
    float d=cSDF(pos), fw=max(fwidth(d),0.001);
    return smoothstep(fw,-fw,d);
}}

vec3 tintGradient(vec3 f,vec3 d,vec3 l){{return mix(d,l,dot(f,vec3(.299,.587,.114)));}}
vec3 rgb2hsl(vec3 c){{float mx=max(c.r,max(c.g,c.b)),mn=min(c.r,min(c.g,c.b)),d=mx-mn;
  float h=0.,s=0.,l=(mx+mn)*.5;if(d>.001){{s=d/(1.-abs(2.*l-1.));
  if(mx==c.r)h=mod((c.g-c.b)/d,6.);else if(mx==c.g)h=(c.b-c.r)/d+2.;
  else h=(c.r-c.g)/d+4.;h/=6.;}}return vec3(h,s,l);}}
vec3 hsl2rgb(vec3 h){{float c=(1.-abs(2.*h.z-1.))*h.y,
  x=c*(1.-abs(mod(h.x*6.,2.)-1.)),m=h.z-c*.5;float hi=floor(h.x*6.);
  vec3 r=hi<1.?vec3(c,x,0):hi<2.?vec3(x,c,0):hi<3.?vec3(0,c,x):
         hi<4.?vec3(0,x,c):hi<5.?vec3(x,0,c):vec3(c,0,x);return r+m;}}
vec3 tintHueShift(vec3 f,float s){{vec3 h=rgb2hsl(f);h.x=fract(h.x+s);return hsl2rgb(h);}}

vec2 drawChar(vec2 frag,vec2 cursor,int c,vec2 sc,inout vec3 col,inout float alpha){{
    vec4 uv=getGlyphRect(c); vec4 mt=getGlyphMeta(c);
    vec2 bl=cursor+vec2(mt.x,FONT_BASE-mt.y-mt.w)*sc;
    vec2 sz=vec2(uv.z*ATLAS_W,mt.w)*sc;
    vec2 lc=(frag-bl)/sz;
    if(all(greaterThanEqual(lc,vec2(0.)))&&all(lessThanEqual(lc,vec2(1.)))){{
        float a=_atlasAlpha(uv.xy+lc*uv.zw);
        col=mix(col,vec3(1.),a); alpha=max(alpha,a);
    }}
    return vec2(cursor.x+mt.z*sc.x,cursor.y);
}}
vec2 fontUV(vec2 lab,float cx,float cy,float ch,float adv,vec2 sc){{
    float p=LINE_H/ch;
    return vec2((lab.x-cx)*p/sc.x+adv*.5,(lab.y-cy)*p/sc.y+LINE_H*.5);
}}

// -- Edit text here -------------------------------------------------------
makeStr(line1)       {tokens}  _end
makeColorStr2D(col1) {tokens}  _endC2D

void mainImage(out vec4 fragColor,in vec2 fragCoord){{
    vec2 lab=fragCoord/iResolution.xy-.5;

    // SCALE -- change freely, animate with sin(iTime):
    // vec2 sc = vec2(1.5+.4*sin(iTime), 2.0);   // pulsing width
    // vec2 sc = vec2(1.0, 1.0+.3*sin(iTime*2.)); // pulsing height
    vec2 sc = vec2({sc_x},{sc_y});

    float ch=0.12;
    vec2 fuv=fontUV(lab,0.,0.,ch,{total_adv:.2f},sc);
    vec4 c1=col1(fuv);
    vec3 col=c1.rgb*c1.a;
    // col=tintGradient(col,vec3(.1,.05,0.),vec3(1.,.9,.2)); // gold
    col=tintHueShift(col,iTime*.1);
    fragColor=vec4(col,1.);
}}
"""

outfile=os.path.join(outdir,f"{name}_bezier.glsl")
open(outfile,'w').write(aclean(glsl2d))
total_segs=sum(sum(len(s) for s in get_contours(cmap[c])) for c in ucodes if c in glyph_fns)
bad=[x for x in open(outfile).read() if ord(x)>127]
print(f"  ASCII-clean: {'OK' if not bad else str(len(bad))+' remaining!'}")
print(f"\nWrote: {outfile}")
print(f"  Glyphs:{len(glyph_fns)}  Segments:{total_segs}  Advance:{total_adv:.2f}px")

# ── 3D shader ────────────────────────────────────────────────────────────────
if args.extrude is not None:
    depth=args.extrude; bevel=args.bevel
    bevel_fp=bevel*LINE_H; safe_fp=bevel_fp+0.08
    tw=total_adv/LINE_H; cam_dist=max(tw*0.85+0.5,2.5)

    src3d=[]
    for code in ucodes:
        if code in glyph_fns:
            ctrs=get_contours(cmap[code])
            if ctrs: src3d.append(gen_sdf_fn_3d(glyph_fns[code],ctrs,bevel_fp))

    adv_fn  = adv_tbl(meta_vals)
    disp3d  = glyph_sdf_dispatch(glyph_fns)

    glsl3d=f"""\
// {name} 3D  --  Raymarched extruded bezier SDF
{font_comment}
// iquilezles.org/articles/distance
// Lighting: Phong + Fresnel + cubemap (set iChannel1 to a CubeMap)
// Fast compile: const-array loops + switch() tables
//
// CHANGING TEXT AT RUNTIME:
//   Edit the makeStr3D token list and recompile in Shadertoy.
//   Any combination of the #define _X tokens works.
//   No regeneration needed -- all glyphs are already compiled in.
//
// SCALE:
//   Edit vec2 sc inside sceneSDF.
//   Animate freely: vec2(1.+.3*sin(iTime), 1.)  etc.
//
// MOUSE: click+drag = orbit  |  release = auto pendulum

{CHAR_DEFINES}

{MACROS_3D}

{BEZIER}

// -- Per-glyph SDF (3D variant: safe bbox clamp) --------------------------
{chr(10).join(src3d)}

// -- Scene constants -------------------------------------------------------
const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};
const float EXTRUDE   = {depth:.4f};
const float BEVEL     = {bevel:.4f};

// -- Glyph advance table (used by makeStr3D) -------------------------------
{adv_fn}

// -- Glyph SDF dispatch (used by makeStr3D) --------------------------------
{disp3d}

// -- Define your 3D text here ---------------------------------------------
// Syntax identical to makeStr.  Change tokens to change text.
// Multiple makeStr3D calls can coexist (e.g. two lines of text).
makeStr3D(myText) {tokens}  _end3D

// -- Scene SDF -------------------------------------------------------------
float sceneSDF(vec3 p) {{
    // SCALE -- animate freely, e.g.:
    // vec2 sc = vec2(1.0+0.3*sin(iTime), 1.0);  // pulsing x
    // vec2 sc = vec2(1.0, 1.0+0.2*sin(iTime*2.));  // pulsing y
    // float s = 1.0+0.15*sin(iTime); vec2 sc=vec2(s,s);  // uniform
    vec2 sc = vec2(1.0, 1.0);

    // Map world XY -> font-pixel space, apply scale
    // (centering is handled inside myText via makeStr3D)
    vec2 fp = (p.xy / sc) * LINE_H;

    float d2 = myText(fp + vec2(0., LINE_H*.5));
    // Compensate SDF for non-uniform scale (conservative, safe for marching)
    d2 = d2 / (min(sc.x,sc.y) * LINE_H);

    vec2 w = vec2(d2, abs(p.z)-EXTRUDE);
    return min(max(w.x,w.y),0.)+length(max(w,0.))-BEVEL;
}}

vec3 calcNormal(vec3 p) {{
    vec2 k=vec2(1.,-1.);
    return normalize(k.xyy*sceneSDF(p+k.xyy*5e-4)+k.yyx*sceneSDF(p+k.yyx*5e-4)
                    +k.yxy*sceneSDF(p+k.yxy*5e-4)+k.xxx*sceneSDF(p+k.xxx*5e-4));
}}
float softShadow(vec3 ro,vec3 rd,float mint,float maxt,float k) {{
    float res=1.,t=mint;
    for(int i=0;i<20;i++) {{float h=sceneSDF(ro+rd*t);
        if(h<1e-4) return 0.; res=min(res,k*h/t); t+=clamp(h,.02,.2);
        if(t>maxt) break;}} return clamp(res,0.,1.);
}}
float calcAO(vec3 p,vec3 n) {{
    float occ=0.,sca=1.;
    for(int i=0;i<5;i++) {{float h=.01+.12*float(i)/4.;
        occ+=(h-sceneSDF(p+h*n))*sca; sca*=.95; if(occ>.35) break;}}
    return clamp(1.-3.5*occ,0.,1.);
}}
float march(vec3 ro,vec3 rd) {{
    float t=.1;
    for(int i=0;i<80;i++) {{float d=sceneSDF(ro+rd*t);
        if(d<5e-5*t) return t; t+=d; if(t>20.) break;}} return -1.;
}}

void mainImage(out vec4 fragColor,in vec2 fragCoord) {{
    vec2 uv=(fragCoord-.5*iResolution.xy)/iResolution.y;

    // Camera: mouse drag = orbit, release = pendulum
    float ang,tilt;
    if(iMouse.z>0.) {{
        ang =-(iMouse.x/iResolution.x*2.-1.)*3.14159;
        tilt=mix(.05,2.5,1.-iMouse.y/iResolution.y);
    }} else {{
        ang=iTime*.5; tilt=.55+.12*sin(iTime*.61);
    }}
    float cd={cam_dist:.3f};
    vec3 ro=vec3(sin(ang)*cd,tilt,cos(ang)*cd),ta=vec3(0.,.05,0.);
    vec3 ww=normalize(ta-ro),uu=normalize(cross(ww,vec3(0.,1.,0.))),vv=cross(uu,ww);
    vec3 rd=normalize(uv.x*uu+uv.y*vv+1.5*ww);

    vec3 sky=mix(vec3(.02,.02,.06),vec3(.10,.07,.18),clamp(uv.y+.5,0.,1.));
    vec3 col=sky;

    float t=march(ro,rd);
    if(t>0.) {{
        vec3 p=ro+rd*t,n=calcNormal(p);
        float ao=calcAO(p,n);
        bool isFace=abs(n.z)>.65;
        vec3 matCol=isFace?vec3(1.,.78,.10):mix(vec3(.50,.20,.02),vec3(1.,.78,.10),.12);
        float metal=isFace?.95:.60,rough=isFace?.12:.40;
        float shine=2./max(rough*rough,1e-4)-2.;
        vec3 lk=normalize(vec3(1.2,2.5,1.8)),lc=normalize(-rd);
        float dk=max(dot(n,lk),0.),dc=max(dot(n,lc),0.)*.35;
        float sh=softShadow(p+n*1e-3,lk,.05,8.,18.);
        vec3 F0=mix(vec3(.04),matCol,metal);
        vec3 F=F0+(1.-F0)*pow(1.-max(dot(-rd,n),0.),5.);
        float spec=pow(max(dot(n,normalize(lk-rd)),0.),shine)*sh;
        vec3 spcCol=mix(vec3(1.,.97,.92),matCol,metal);
        vec3 envCol=pow(max(texture(iChannel1,reflect(rd,n)).rgb,0.),vec3(2.2));
        envCol=mix(envCol,envCol*matCol*1.5,metal*.6);
        float hemi=.5+.5*n.y;
        vec3 ambC=mix(vec3(.05,.03,.10),vec3(.13,.10,.20),hemi);
        vec3 kd=(1.-F)*(1.-metal);
        col=matCol*ambC*ao+matCol*kd*(dk*sh+dc)*ao+spcCol*F*spec+F*envCol*ao;
        col=mix(col,sky,clamp(t*.04,0.,1.));
    }}
    {{
        float tg=-(ro.y+.52)/rd.y;
        if(tg>0.&&(t<0.||tg<t)) {{
            vec3 pg=ro+rd*tg; vec2 gp=pg.xz*1.5;
            vec2 gw=abs(fract(gp-.5)-.5)/fwidth(gp);
            float gl=1.-min(min(gw.x,gw.y),1.);
            vec3 gc=mix(vec3(.03,.02,.07),vec3(.16,.12,.26),gl*.55);
            float sh=softShadow(pg+vec3(0.,1e-3,0.),normalize(vec3(1.2,2.5,1.8)),.05,8.,12.);
            col=mix(col,gc*(.25+.75*sh),clamp(1.-tg*.04,0.,1.));
        }}
    }}
    col=col/(col+.75); col=pow(max(col,0.),vec3(.4545));
    fragColor=vec4(col,1.);
}}
"""
    outfile3d=os.path.join(outdir,f"{name}_3d.glsl")
    open(outfile3d,'w').write(aclean(glsl3d))
    bad3=[x for x in open(outfile3d).read() if ord(x)>127]
    print(f"\nWrote (3D): {outfile3d}")
    print(f"  Depth:{depth:.3f}  Bevel:{bevel:.3f}  CamDist:{cam_dist:.2f}")
    print(f"  ASCII-clean: {'OK' if not bad3 else str(len(bad3))+' remaining!'}")

# ── fire shader ──────────────────────────────────────────────────────────────
if args.fire:
    FIRE_NOISE="""\
vec3 hash3(vec3 p) {
    p = vec3(dot(p, vec3(127.1, 311.7,  74.7)),
             dot(p, vec3(269.5, 183.3, 246.1)),
             dot(p, vec3(113.5, 271.9, 124.6)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float noise(vec3 p) {
    vec3 i = floor(p); vec3 f = fract(p);
    vec3 u = f * f * (3.0 - 2.0 * f);
    float n0=dot(hash3(i+vec3(0,0,0)),f-vec3(0,0,0));
    float n1=dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0));
    float n2=dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0));
    float n3=dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0));
    float n4=dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1));
    float n5=dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1));
    float n6=dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1));
    float n7=dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1));
    float ix0=mix(n0,n1,u.x),ix1=mix(n2,n3,u.x);
    float ix2=mix(n4,n5,u.x),ix3=mix(n6,n7,u.x);
    float ret=mix(mix(ix0,ix1,u.y),mix(ix2,ix3,u.y),u.z)*0.5+0.5;
    return ret * 2.0 - 1.0;
}"""

    adv_lines = ["float charAdvance(int c){","  switch(c){"]
    for code,vals in sorted(meta_vals.items()):
        adv_lines.append(f"  case {code}: return {vals[2]:.4f};")
    adv_lines.append("  default: return 8.0;\n  }\n}")
    CHAR_ADVANCE = '\n'.join(adv_lines)

    n_chars = len(chars)
    def char_tok_fire(c):
        if c == ' ': return '_'
        if c.isalpha(): return '_' + c
        M = {'.':'_DOT', ',':'_COM', '-':'_SUB', ':':'_COL', ';':'_SEM',
             '!':'_EX', '?':'_QUE', '(':'_LPR', ')':'_RPR',
             "'": '_QT', '"':'_DBQ', '_':'_UN'}
        return M.get(c, '_' + c if c.isdigit() else '')
    token_list = ' '.join(t for c in chars if (t := char_tok_fire(c)))
    GET_TEXT_DIST = f"""\
float getTextDist(vec2 fuv) {{
    const int ch[{n_chars+1}] = int[]({token_list}  0);
    float x = 0., md = 1e9;
    for (int k = 0; k < {n_chars}; k++) {{
        int c = ch[k];
        getGlyphRect(c);
        if (c != 32) {{
            vec2 pg = vec2(fuv.x - x, fuv.y);
            md = min(md, cSDF(pg));
        }}
        x += charAdvance(c);
    }}
    return md;
}}"""

    FIRE_COLOR = f"""\
const float _Power     = {args.fire_power};
const float _MaxLength = {args.fire_maxlen};
const float _Dumping   = {args.fire_dumping};

vec3 runeFireColor(vec2 p, float dist) {{
    vec3 coord = vec3(p * 3.5 + 2.5, iTime * 0.4);
    float n  = abs(noise(coord));
    n += 0.50  * abs(noise(coord * 2.0));
    n += 0.25  * abs(noise(coord * 4.0));
    n += 0.125 * abs(noise(coord * 8.0));
    n *= (250.001 - _Power);
    float k = clamp(dist, 0.0, _MaxLength) / _MaxLength;
    n *= dist / pow(1.001 - k, _Dumping);
    return pow(vec3(1.0, 0.25, 0.08) / n, vec3(1.9));
}}"""

    slide_off   = args.fire_slide
    slide_time  = args.fire_slide_time
    hold_time   = args.fire_hold_time
    f_ch        = args.fire_ch
    f_sc_x      = fire_sc_x
    f_sc_y      = fire_sc_y

    FIRE_MAIN = f"""\
void mainImage(out vec4 fragColor, in vec2 fragCoord) {{
    vec2 r   = iResolution.xy;
    vec2 lab = fragCoord / r - .5;
    vec2 p   = (fragCoord * 2.0 - r) / r.y;

    vec2 sc  = vec2({f_sc_x},{f_sc_y});
    float ch = {f_ch};

    float slideTime = {slide_time};
    float holdTime  = {hold_time};
    float period    = slideTime * 2.0 + holdTime;
    float t     = mod(iTime, period);
    float s_in  = smoothstep(0.0,                  slideTime, t);
    float s_out = smoothstep(slideTime + holdTime,  period,    t);
    float cx = mix({slide_off}, 0.0, s_in) + mix(0.0, -{slide_off}, s_out);

    vec2 fuv = fontUV(lab, cx, 0., ch, {total_adv:.2f}, sc);

    float signedDist = getTextDist(fuv) * ch / LINE_H;
    float dist = min(abs(signedDist), 1.0);

    vec3 col = runeFireColor(p, dist);
    fragColor = vec4(col, 1.0);
}}"""

    fire_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            fire_sdf_src.append(gen_sdf_fn_fire(fn, contours))

    fire_disp = '\n'.join(
        f"  if(_GC=={code}) return {fn}(p);"
        for code,fn in sorted(glyph_fns.items()))

    glsl_fire = f"""\
// {name} -- Rune-style fire text
{font_comment}
// Fire technique: Kamil Kolaczynski (revers) 2015 -- adapted for Bezier SDF font
// No iChannel0, no buffer -- fully standalone, paste into any Shadertoy tab.
// Generated by font2bezier.py --fire

{CHAR_DEFINES}

{FIRE_NOISE}

const float ATLAS_W = 1.0;
const float LINE_H  = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

{chr(10).join(fire_sdf_src)}

int _GC = 0;

{rect_tbl}

float cSDF(vec2 p) {{
{fire_disp}
  return 1e9;
}}

vec2 fontUV(vec2 lab, float cx, float cy, float ch, float adv, vec2 sc) {{
    float p = LINE_H / ch;
    return vec2((lab.x-cx)*p/sc.x + adv*.5, (lab.y-cy)*p/sc.y + LINE_H*.5);
}}

{CHAR_ADVANCE}

{GET_TEXT_DIST}

{FIRE_COLOR}

{FIRE_MAIN}
"""

    outfile_fire = os.path.join(outdir, f"{name}_fire.glsl")
    open(outfile_fire, 'w').write(aclean(glsl_fire))
    bad_fire = [x for x in open(outfile_fire).read() if ord(x) > 127]
    print(f"\nWrote (fire): {outfile_fire}")
    print(f"  Chars:{len(chars)}  Advance:{total_adv:.2f}px")
    print(f"  _Power:{args.fire_power}  _MaxLength:{args.fire_maxlen}  _Dumping:{args.fire_dumping}")
    print(f"  ch:{f_ch}  sc:({f_sc_x},{f_sc_y})  slide:{slide_off}  slideTime:{slide_time}s  holdTime:{hold_time}s")
    print(f"  ASCII-clean: {'OK' if not bad_fire else str(len(bad_fire))+' remaining!'}")

# ── demo shader (font + opCutDispersal) ──────────────────────────────────────
if args.demo:
    demo_d   = args.demo_depth
    demo_bev = args.bevel           # reuse global --bevel
    demo_iters = args.demo_iters
    demo_spd   = args.demo_speed
    kx, ky, kz = demo_kdiv_x, demo_kdiv_y, demo_kdiv_z

    tw = total_adv / LINE_H         # world-space text width (height = 1.0)

    # opCutDispersal l0 half-extents -- must enclose the scene + dispersal margin
    l0_x = tw * 0.5 + 0.5
    l0_y = 0.5      + 0.35
    l0_z = demo_d   + 0.35

    # bounding box for AABB ray test (with tOpen expansion)
    bb_x = l0_x
    bb_y = l0_y
    bb_z = l0_z

    cam_demo = max(tw * 0.85 + 0.5, 2.8)

    # Per-glyph 3D SDFs (safe bbox clamp variant)
    bevel_fp = demo_bev * LINE_H
    src_demo = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        ctrs = get_contours(gname)
        if ctrs:
            src_demo.append(gen_sdf_fn_3d(glyph_fns[code], ctrs, bevel_fp))

    adv_fn_demo = adv_tbl(meta_vals)
    disp3d_demo = glyph_sdf_dispatch(glyph_fns)

    glsl_demo = f"""\
// {name} DEMO  --  Bezier SDF Font + Cut Dispersal
{font_comment}
// Font  : fully analytical bezier SDF -- no iChannel0 texture required
// Effect: opCutDispersal (Sebastien Durand 2022, CC BY-NC-SA 3.0)
//         https://www.shadertoy.com/view/wsSGDD
// Generated by font2bezier.py --demo
//
// No iChannel needed.  Single-tab Shadertoy paste.
// MOUSE: click+drag left/right = orbit  |  idle = auto rotation
//
// Tune --demo-depth  --demo-iters  --demo-speed  --demo-kdiv to taste.
// Edit the makeStr3D token list to change text, then regenerate.

{CHAR_DEFINES}

{MACROS_3D}

// -- Bezier SDF primitives (iq, CC BY-NC-SA) ────────────────────────────────
{BEZIER}

// -- Per-glyph SDFs (3D safe-bbox variant) ─────────────────────────────────
{chr(10).join(src_demo)}

// -- Scene constants ────────────────────────────────────────────────────────
const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};
const float EXTRUDE   = {demo_d:.4f};
const float BEVEL     = {demo_bev:.4f};

// -- Glyph tables ───────────────────────────────────────────────────────────
{adv_fn_demo}

{disp3d_demo}

// -- Text (edit tokens to change text, then regenerate) ─────────────────────
makeStr3D(myText) {tokens}  _end3D

// -- Extruded font SDF ──────────────────────────────────────────────────────
float fontSDF(vec3 p) {{
    vec2 fp = p.xy * LINE_H;
    float d2 = myText(fp + vec2(0., LINE_H * .5));
    d2 /= LINE_H;
    vec2 w = vec2(d2, abs(p.z) - EXTRUDE);
    return min(max(w.x, w.y), 0.) + length(max(w, 0.)) - BEVEL;
}}

// -- Cut Dispersal operator ─────────────────────────────────────────────────
// Adapted from Sebastien Durand https://www.shadertoy.com/view/wsSGDD
// opCutDispersal modifies uv in-place (dispersed glyph-space coords).
// Combined with fontSDF via max() to produce the cracked/dispersed look.
#define CD_ITERS {float(demo_iters)}

mat2 _rot(float a) {{ return mat2(cos(a),sin(a),-sin(a),cos(a)); }}

vec3 _hash33(vec3 p) {{
    p = vec3(dot(p,vec3(127.1,311.7, 74.7)),
             dot(p,vec3(269.5,183.3,246.1)),
             dot(p,vec3(113.5,271.9,124.6)));
    return fract(sin(p)*43758.5453123);
}}

float _sdBox(vec3 p, vec3 b) {{
    vec3 q = abs(p) - b;
    return length(max(q,0.)) + min(max(q.x,max(q.y,q.z)),0.);
}}

float opCutDispersal(inout vec3 uv, vec3 kdiv) {{
    kdiv *= .3 + .7*smoothstep(-2.,2., uv.x + 10.*cos({demo_spd:.3f}*iTime));
    uv.xz *= _rot(.2);
    uv.xy *= _rot(.3);
    vec3 l0   = 2.*1.9*vec3({l0_x:.4f},{l0_y:.4f},{l0_z:.4f});
    vec3 dMin = -l0*.5 - kdiv*pow(2.,CD_ITERS-1.);
    vec3 dMax =  l0*.5 + kdiv*pow(2.,CD_ITERS-1.);
    float i=0.;
    vec3 diff2 = vec3(1.), posTxt = uv;
    for (; i<CD_ITERS; i++) {{
        vec3 div0  = vec3(.1)+.8*_hash33(diff2),
             dd    = kdiv*pow(2.,CD_ITERS-1.-i),
             a0    = div0*l0,
             a2    = a0+dd,
             l2    = l0+2.*dd,
             div2  = a2/l2;
        vec3 divide = mix(dMin, dMax, div2);
        l0    = mix(l0-a0,  a0,     step(uv,divide));
        dMax  = mix(dMax,   divide, step(uv,divide));
        dMin  = mix(divide, dMin,   step(uv,divide));
        diff2 = step(uv,divide) - 10.*_hash33(diff2);
        posTxt -= dd*(.5 - step(uv,divide));
    }}
    vec3 center = (dMin+dMax)*.5;
    vec3 dd0    = .5*kdiv*pow(2.,CD_ITERS-(i-1.));
    float d     = _sdBox(uv-center, .5*(dMax-dMin)-.5*dd0);
    uv = posTxt;
    uv.xy *= _rot(-.3);
    uv.xz *= _rot(-.2);
    return d;
}}

float tOpen;
const vec3 KDIV = vec3({kx:.4f},{ky:.4f},{kz:.4f});

float map(vec3 p) {{
    float dcut = opCutDispersal(p, KDIV*tOpen);
    float dscn = fontSDF(p);
    return max(dscn, dcut);
}}

vec2 mapMat(vec3 p) {{
    float dcut = opCutDispersal(p, KDIV*tOpen);
    float dscn = fontSDF(p);
    return vec2(max(dscn,dcut), dscn>=dcut ? 1. : 2.);
}}

vec3 calcNormal(vec3 p, vec3 rd, inout float edge) {{
    float h  = max(4.5/mix(450.,min(850.,iResolution.y),.35), 5e-4);
    float d0 = map(p);
    vec3  n  = vec3(0.);
    float lap = 0.;
    for (int i=min(iFrame,0); i<4; i++) {{
        vec3  ev = .57735*(2.*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.);
        float s  = map(p + h*ev);
        n   += ev*s;
        lap += s;
    }}
    edge = smoothstep(0.,1.,sqrt(abs(lap - 4.*d0)/h));
    return normalize(n - max(0.,dot(n,rd))*rd);
}}

bool iBox(vec3 ro, vec3 rd, vec3 sz, inout float tN, inout float tF) {{
    vec3 m=sign(rd)/max(abs(rd),1e-8), n=m*ro, k=abs(m)*sz,
         t1=-n-k, t2=-n+k;
    tN=max(max(t1.x,t1.y),t1.z);
    tF=min(min(t2.x,t2.y),t2.z);
    return !(tN>tF || tF<=0.);
}}

vec3 shade(vec3 rd, vec3 n, float mat, vec3 ldir, vec3 bg, float dist) {{
    float amb = clamp(.5+.5*n.y,0.,1.),
          dif = clamp(dot(n,ldir),0.,1.),
          pp  = clamp(dot(reflect(-ldir,n),-rd),0.,1.),
          fre = (.7+.3*dif)*pow(clamp(1.+dot(n,rd),0.,1.),2.);
    vec3 cobj  = mat<1.5 ? vec3(.65,.70,.74) : 1.5*vec3(.88,.44,.05);
    float spec = mat<1.5 ? 99. : 16.;
    vec3 brdf  = .5*amb + dif*vec3(1.,.9,.7),
         sp    = 3.*pow(pp,spec)*vec3(1.,.7,.3),
         col   = cobj*(brdf+sp) + fre*(.5*cobj+.5);
    return mix(col, bg, smoothstep(5.,20.,dist));
}}

mat3 setCamera(vec3 ro, vec3 ta, float r) {{
    vec3 w=normalize(ta-ro), p=vec3(sin(r),cos(r),0.),
         u=normalize(cross(w,p)), v=cross(u,w);
    return mat3(u,v,w);
}}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {{
    vec2 r=iResolution.xy, m=iMouse.xy/r, q=fragCoord/r;
    tOpen = .4*smoothstep(.6,0.,cos({demo_spd:.3f}*iTime));
    float a = iMouse.z>0.
              ? 3.14159*(2.*m.x-1.)
              : 1.+mix(.3,3.*cos(.4*3.*iTime),.5+.5*cos(.2*iTime));
    float camY = iMouse.z>0. ? mix(.1,2.5,m.y) : .4*cos(.4*iTime)+.8;
    vec3 ta=vec3(0.),
         ro=ta+{cam_demo:.2f}*vec3(cos(a), camY, sin(a));
    mat3 ca=setCamera(ro,ta,.1*cos(.123*iTime));
    vec3 rd=ca*normalize(vec3((2.*fragCoord-r)/r.y,2.5));
    vec3 bg=.09*vec3(_hash33(q.xyx).x+1.);
    vec3  c=bg;
    vec3 bsz=vec3({bb_x:.3f},{bb_y:.3f},{bb_z:.3f})*(1.+vec3(1.,2.,3.)*tOpen)+.05;
    float tN=0.,tF=14.,t=0.,h=.1;
    if (iBox(ro,rd,bsz,tN,tF)) {{
        t=tN;
        for (int i=min(iFrame,0); i<140; i++) {{
            if (h<1e-3||t>tF) break;
            t += h=map(ro+rd*t);
        }}
        if (t<tF) {{
            vec3 pos=ro+t*rd;
            float edge=0.;
            vec2  mat=mapMat(pos);
            vec3  n=calcNormal(pos,rd,edge);
            n=normalize(n-max(0.,dot(n,rd))*rd);
            vec3 lp=ro+3.*vec3(.25,2.,-.1);
            c=shade(rd,n,mat.y,normalize(lp-pos),bg,t);
            c*=1.-edge*.8;
        }}
    }}
    c=pow(max(c,0.),vec3(.75));
    c*=pow(16.*q.x*q.y*(1.-q.x)*(1.-q.y),.7);
    fragColor=vec4(c,1.);
}}
"""

    outfile_demo=os.path.join(outdir,f"{name}_demo.glsl")
    open(outfile_demo,'w').write(aclean(glsl_demo))
    bad_demo=[x for x in open(outfile_demo).read() if ord(x)>127]
    print(f"\nWrote (demo): {outfile_demo}")
    print(f"  Depth:{demo_d:.3f}  Bevel:{demo_bev:.3f}  Iters:{demo_iters}  Speed:{demo_spd}")
    print(f"  KDIV:({kx:.3f},{ky:.3f},{kz:.3f})  l0:({l0_x:.3f},{l0_y:.3f},{l0_z:.3f})")
    print(f"  CamDist:{cam_demo:.2f}  TextWidth:{tw:.2f}")
    print(f"  ASCII-clean: {'OK' if not bad_demo else str(len(bad_demo))+' remaining!'}")

# ── spell shader (Fontskin-style sequential reveal) ──────────────────────────
if args.spell:
    spell_ch    = args.spell_ch
    spell_draw  = args.spell_draw
    spell_pause = args.spell_pause
    spell_glow  = args.spell_glow
    spell_hue   = args.spell_hue_speed

    # Character code list — unknown chars fall back to space (code 32)
    spell_codes = [ord(c) if ord(c) in cmap else 32 for c in chars]
    spell_n     = len(spell_codes)
    spell_codes_str = ', '.join(str(c) for c in spell_codes)

    # Vertical centre of the text block in fuv space.
    # bl.y = FONT_BASE - mt.y - mt.w  (bottom of char)
    # top_y = FONT_BASE - mt.y        (top of char)
    ys = [(FONT_BASE - meta_vals[ord(c)][1] - meta_vals[ord(c)][3],
           FONT_BASE - meta_vals[ord(c)][1])
          for c in chars if ord(c) in meta_vals and meta_vals[ord(c)][3] > 0]
    if ys:
        spell_ycenter = (min(b for b,_ in ys) + max(t for _,t in ys)) / 2.0
    else:
        spell_ycenter = 0.0

    # Per-glyph SDFs without per-function bbox early-exit guard.
    # The [0,1] lc check in mainImage handles culling; removing the guard
    # prevents the rectangular bounding-box outline artifact.
    spell_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            spell_sdf_src.append(gen_sdf_fn_fire(fn, contours))

    spell_disp = '\n'.join(
        f"  if(_GC=={code}) return {fn}(p);"
        for code, fn in sorted(glyph_fns.items()))

    glsl_spell = f"""\
// {name} -- Spell reveal animation
{font_comment}
// Sequential character reveal: Fontskin-style outline-progress sweep
// Bezier SDF font: iquilezles.org/articles/distance
// Generated by font2bezier.py --spell
//
// No iChannel needed.  Single-tab Shadertoy paste.
//
// Key parameters (all baked at generation time, re-run to change):
//   --spell-ch       {spell_ch}   (text height as fraction of screen height)
//   --spell-draw     {spell_draw}   (seconds to reveal all characters)
//   --spell-pause    {spell_pause}   (hold time before restart)
//   --spell-color    {spell_r:.2f},{spell_g:.2f},{spell_b:.2f}   (base RGB)
//   --spell-hue-speed {spell_hue}  (hue drift per second)
//   --spell-glow     {spell_glow}   (outer glow radius in font units)

const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

// Per-glyph SDFs — no per-function bbox early-exit guard.
// Culling is handled per-pixel by the lc in [0,1] check in mainImage.
{chr(10).join(spell_sdf_src)}

int _GC = 0;

// getGlyphRect sets _GC as a side-effect so cSDF dispatches correctly.
{rect_tbl}

{meta_tbl}

float cSDF(vec2 p){{
{spell_disp}
  return 1e9;
}}

vec3 rgb2hsl(vec3 c){{
    float mx=max(c.r,max(c.g,c.b)),mn=min(c.r,min(c.g,c.b)),d=mx-mn;
    float h=0.,s=0.,l=(mx+mn)*.5;
    if(d>.001){{s=d/(1.-abs(2.*l-1.));
        if(mx==c.r)h=mod((c.g-c.b)/d,6.);
        else if(mx==c.g)h=(c.b-c.r)/d+2.;
        else h=(c.r-c.g)/d+4.;h/=6.;}}
    return vec3(h,s,l);
}}
vec3 hsl2rgb(vec3 h){{
    float c=(1.-abs(2.*h.z-1.))*h.y,x=c*(1.-abs(mod(h.x*6.,2.)-1.)),m=h.z-c*.5;
    float hi=floor(h.x*6.);
    vec3 r=hi<1.?vec3(c,x,0.):hi<2.?vec3(x,c,0.):hi<3.?vec3(0.,c,x):
           hi<4.?vec3(0.,x,c):hi<5.?vec3(x,0.,c):vec3(c,0.,x);
    return r+m;
}}
vec3 tintHueShift(vec3 f,float s){{vec3 h=rgb2hsl(f);h.x=fract(h.x+s);return hsl2rgb(h);}}

// Aspect-corrected lab coords -> font pixel space.
// Vertical offset {spell_ycenter:.2f} centres the text block optically on screen.
vec2 fontUV(vec2 lab, float ch, float adv){{
    float p = LINE_H / ch;
    return vec2(lab.x*p + adv*.5, lab.y*p + {spell_ycenter:.4f});
}}

void mainImage(out vec4 fragColor, in vec2 fragCoord){{
    // Isotropic lab coordinates — corrects aspect ratio so glyphs are not distorted.
    vec2 lab = fragCoord / iResolution.xy - .5;
    lab.x   *= iResolution.x / iResolution.y;

    vec2 fuv = fontUV(lab, {spell_ch:.4f}, {total_adv:.4f});

    // "{aclean(chars)}" -- {spell_n} glyphs
    int codes[{spell_n}] = int[]({spell_codes_str});

    // drawDur  : window in which all chars are cued and revealed.
    // pauseDur : hold time after full reveal before restart.
    // dt       : delay between successive character cues.
    float drawDur  = {spell_draw:.2f};
    float pauseDur = {spell_pause:.2f};
    float period   = drawDur + pauseDur;
    float t        = mod(iTime, period);
    float dt       = drawDur / {float(spell_n):.1f};

    vec3  col = vec3(0.);
    float al  = 0.;
    float cx  = 0.;   // horizontal cursor in font units

    for (int i = 0; i < {spell_n}; i++){{
        int  c  = codes[i];
        vec4 gr = getGlyphRect(c);   // sets _GC for the cSDF dispatch
        vec4 mt = getGlyphMeta(c);
        float el = t - float(i)*dt;  // seconds elapsed since this char's cue

        if (c != 32 && el > 0.){{
            // Map fuv into normalised glyph-box coords [0,1]^2.
            vec2 bl = vec2(cx + mt.x, FONT_BASE - mt.y - mt.w);
            vec2 sz = vec2(gr.z, mt.w);
            vec2 lc = (fuv - bl) / sz;

            if (all(greaterThanEqual(lc, vec2(0.))) &&
                all(lessThanEqual  (lc, vec2(1.)))){{

                vec2  gp = gr.xy + lc * gr.zw;   // glyph-space coordinate
                float d  = cSDF(gp);
                float fw = max(fwidth(d), .001);

                // Outline-progress approximated by polar angle from glyph
                // bounding-box centre, mapped to [0,1].
                // Fontskin reveal condition: pixel shown when op < 2*elapsed.
                vec2  ctr  = gr.xy + gr.zw * .5;
                float op   = atan(gp.y-ctr.y, gp.x-ctr.x) / (2.*acos(-1.)) + .5;
                float prog = clamp(el, 0., .5) * 2.;   // sweeps 0->1 in 0.5 s
                float revealed = step(op, prog);

                // Flash at sweep frontier: 1.8-unit band around the SDF zero-
                // crossing, fades after reveal completes to avoid re-firing
                // at the angle-wrap seam when prog = 1.
                float flashFade = smoothstep(.55, .42, el);
                float flash = smoothstep(.06, 0., abs(op - prog))
                            * smoothstep(1.8,  0., abs(d))
                            * flashFade;

                // Outer glow, {spell_glow:.1f} font-unit radius, lags 0.15 s behind
                // the frontier (mirrors Fontskin's external-recess effect).
                // bboxFade fades the glow to zero within one glow-radius of each
                // bbox edge, preventing the hard rectangular cutoff artifact that
                // appears where glowA drops abruptly from nonzero to unevaluated.
                float gProg    = clamp(el - .15, 0., .5);
                float glowInLc = {spell_glow:.1f} / max(sz.x, sz.y);
                vec2  edgeDist = min(lc, 1. - lc);
                float bboxFade = smoothstep(0., glowInLc, min(edgeDist.x, edgeDist.y));
                float glowA    = smoothstep({spell_glow:.1f}, 0., d) * step(op, gProg) * .28 * bboxFade;

                float fillA = smoothstep(fw, -fw, d) * revealed;

                // Base color blends to white at the flash frontier.
                vec3 base = vec3({spell_r:.4f}, {spell_g:.4f}, {spell_b:.4f});
                vec3 cc   = mix(base, vec3(1.), flash);

                float tot   = clamp(fillA + flash + glowA, 0., 1.);
                float blend = tot * (1. - al);
                col += cc * blend;
                al   = clamp(al + blend, 0., 1.);
            }}
        }}
        cx += mt.z;
    }}

    // Slow hue drift -- set --spell-hue-speed 0 to disable.
    col = tintHueShift(col, iTime * {spell_hue:.4f});

    fragColor = vec4(col, 1.);
}}
"""

    outfile_spell = os.path.join(outdir, f"{name}_spell.glsl")
    open(outfile_spell, 'w').write(aclean(glsl_spell))
    bad_spell = [x for x in open(outfile_spell).read() if ord(x) > 127]
    print(f"\nWrote (spell): {outfile_spell}")
    print(f"  Chars:{spell_n}  Advance:{total_adv:.2f}px  yCentre:{spell_ycenter:.2f}")
    print(f"  ch:{spell_ch}  drawDur:{spell_draw}s  pauseDur:{spell_pause}s")
    print(f"  color:({spell_r:.2f},{spell_g:.2f},{spell_b:.2f})  "
          f"hueSpeed:{spell_hue}  glowRadius:{spell_glow}")
    print(f"  ASCII-clean: {'OK' if not bad_spell else str(len(bad_spell))+' remaining!'}")

# ── matrix shader (DisAInformation energy ripple + sweep) ────────────────────
if args.matrix:
    mx_ch_base  = args.matrix_ch_base
    mx_ch_amp   = args.matrix_ch_amp
    mx_ch_speed = args.matrix_ch_speed
    mx_glow     = args.matrix_glow
    mx_tbuf     = args.matrix_tbuf
    mx_tgamma   = args.matrix_tgamma

    # Same character prep as --spell
    mx_codes = [ord(c) if ord(c) in cmap else 32 for c in chars]
    mx_n     = len(mx_codes)
    mx_codes_str = ', '.join(str(c) for c in mx_codes)

    ys = [(FONT_BASE - meta_vals[ord(c)][1] - meta_vals[ord(c)][3],
           FONT_BASE - meta_vals[ord(c)][1])
          for c in chars if ord(c) in meta_vals and meta_vals[ord(c)][3] > 0]
    if ys:
        mx_ycenter = (min(b for b,_ in ys) + max(t for _,t in ys)) / 2.0
    else:
        mx_ycenter = 0.0

    mx_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            mx_sdf_src.append(gen_sdf_fn_fire(fn, contours))

    mx_disp = '\n'.join(
        f"  if(_GC=={code}) return {fn}(p);"
        for code, fn in sorted(glyph_fns.items()))

    glsl_matrix = f"""\
// {name} -- Matrix / DisAInformation energy effect
{font_comment}
// Effect ported from the Fontskin "DisAInformation" widget shader (doc5/doc6):
//   oscillating aura ripple  -- auraEdgeDist x sin/cos turbulence
//   inner outline fill       -- outline(sdfFont, primaryColor, {mx_tbuf})
//   diagonal sweep highlight -- time-based sideAngle x x-gradient
// Text size pulses with abs(sin(iTime * {mx_ch_speed})).
//
// No iChannel needed.  Single-tab Shadertoy paste.
//
// Key parameters (re-run with different flags to change):
//   --matrix-ch-base   {mx_ch_base}   base text height (fraction of screen height)
//   --matrix-ch-amp    {mx_ch_amp}   height animation amplitude
//   --matrix-ch-speed  {mx_ch_speed}  height animation speed
//   --matrix-color     {matrix_r:.3f},{matrix_g:.3f},{matrix_b:.3f}  primary RGB
//   --matrix-glow      {mx_glow}    aura radius in font units
//   --matrix-tbuf      {mx_tbuf}    outline SDF threshold

const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

// Per-glyph SDFs (no per-function bbox guard — culled per-pixel in mainImage)
{chr(10).join(mx_sdf_src)}

int _GC = 0;

// getGlyphRect sets _GC as a side-effect for cSDF dispatch.
{rect_tbl}

{meta_tbl}

float cSDF(vec2 p){{
{mx_disp}
  return 1e9;
}}

// Aspect-corrected lab -> font pixel space.
// Vertical offset {mx_ycenter:.2f} centres the text block optically on screen.
vec2 fontUV(vec2 lab, float ch, float adv){{
    float p = LINE_H / ch;
    return vec2(lab.x*p + adv*.5, lab.y*p + {mx_ycenter:.4f});
}}

void mainImage(out vec4 fragColor, in vec2 fragCoord){{
    vec2 lab = fragCoord / iResolution.xy - .5;
    lab.x   *= iResolution.x / iResolution.y;

    // Pulsing text size — height oscillates between ch_base and ch_base+ch_amp.
    float ch = {mx_ch_base:.4f} + {mx_ch_amp:.4f} * abs(sin(iTime * {mx_ch_speed:.4f}));
    vec2 fuv = fontUV(lab, ch, {total_adv:.4f});

    // "{aclean(chars)}" -- {mx_n} glyphs
    int codes[{mx_n}] = int[]({mx_codes_str});

    // Effect constants (matching doc5/doc6 widget configuration)
    const vec4  U_PRIMARY = vec4({matrix_r:.4f}, {matrix_g:.4f}, {matrix_b:.4f}, 1.0);
    const float U_TBUF    = {mx_tbuf:.2f};
    const float U_TGAMMA  = {mx_tgamma:.2f};
    const float AURA_R    = {mx_glow:.1f};

    vec4  Cm = vec4(0.);   // output accumulator (mirrors doc5's Cm)
    float cx = 0.;

    for (int i = 0; i < {mx_n}; i++){{
        int  c  = codes[i];
        vec4 gr = getGlyphRect(c);   // sets _GC for cSDF dispatch
        vec4 mt = getGlyphMeta(c);

        if (c != 32){{
            vec2 bl = vec2(cx + mt.x, FONT_BASE - mt.y - mt.w);
            vec2 sz = vec2(gr.z, mt.w);
            vec2 lc = (fuv - bl) / sz;

            // Expand bounds to include the outer aura region.
            float auraInLc = AURA_R / max(sz.x, sz.y);
            if (all(greaterThanEqual(lc, vec2(-auraInLc))) &&
                all(lessThanEqual  (lc, vec2(1. + auraInLc)))){{

                vec2  gp = gr.xy + lc * gr.zw;
                float d  = cSDF(gp);
                float fw = max(fwidth(d), .001);

                // Fontskin SDF encoding: 0.5 at edge, soft 6*fw transition so the
                // outline threshold ({mx_tbuf}) falls ~2 fw inside the stroke.
                float sdfFont      = smoothstep(fw*6., -fw*6., d);
                float auraEdgeDist = smoothstep(AURA_R, 0., d);

                // sideAngle: time-based global sweep (doc6 style).
                // abs(mod(iTime,1.)) gives a sawtooth 0->1->0 every second.
                float sideAngle = abs(mod(iTime, 1.));

                // Bbox edge fade -- smoothly zero out contributions in the
                // expanded aura region so there is no hard rectangular border.
                float outsideDist = max(max(-lc.x, lc.x-1.), max(-lc.y, lc.y-1.));
                float bfade       = smoothstep(auraInLc, 0., max(0., outsideDist));

                // ── Doc5/doc6 mainImage (translated) ─────────────────────────

                // Co: oscillating aura ripple + base SDF brightness.
                float Co_val = auraEdgeDist
                    * sin(iTime*10. + fragCoord.x/9.)
                    * cos(iTime*10. + fragCoord.y - mod(iTime/52.,10.)/30.)
                    + sdfFont;
                Cm += vec4(Co_val) * .3 * bfade;

                // Cp: inner outline at the SDF buffer threshold.
                float outlineO = smoothstep(U_TBUF - U_TGAMMA,
                                            U_TBUF + U_TGAMMA, sdfFont);
                vec4 Cp = vec4(U_PRIMARY.rgb, outlineO * U_PRIMARY.a);

                // Half outline + full SDF brightness (doc5: Cm += Cp/2. + sdfFont).
                Cm += (Cp * .5 + vec4(sdfFont)) * bfade;

                // Diagonal sweep highlight (doc5/doc6: Cq / Cr / Cp.rgba -=).
                float Cq = fragCoord.x / iResolution.x * 4.;
                float Cr  = 1. - mod(-sideAngle + Cq, 1.);
                Cp.rgba -= vec4(mod(Cr, 1.));
                Cm += Cp * bfade;
            }}
        }}
        cx += mt.z;
    }}

    fragColor = vec4(clamp(Cm.rgb, 0., 1.), 1.);
}}
"""

    outfile_matrix = os.path.join(outdir, f"{name}_matrix.glsl")
    open(outfile_matrix, 'w').write(aclean(glsl_matrix))
    bad_matrix = [x for x in open(outfile_matrix).read() if ord(x) > 127]
    print(f"\nWrote (matrix): {outfile_matrix}")
    print(f"  Chars:{mx_n}  Advance:{total_adv:.2f}px  yCentre:{mx_ycenter:.2f}")
    print(f"  ch_base:{mx_ch_base}  ch_amp:{mx_ch_amp}  ch_speed:{mx_ch_speed}")
    print(f"  color:({matrix_r:.3f},{matrix_g:.3f},{matrix_b:.3f})  "
          f"glow:{mx_glow}  tbuf:{mx_tbuf}  tgamma:{mx_tgamma}")
    print(f"  ASCII-clean: {'OK' if not bad_matrix else str(len(bad_matrix))+' remaining!'}")

# ── sweep shader (horizontal sweep bands over text aura) ──────────────────────
if args.sweep:
    sw_ch      = args.sweep_ch
    sw_aura    = args.sweep_aura
    sw_speed   = args.sweep_speed
    sw_wave_w  = args.sweep_wave_width
    sw_angle   = args.sweep_angle
    sw_cr_pow  = args.sweep_cr_power
    sw_pause   = max(0.0, min(0.99, args.sweep_pause))
    sw_hl      = args.sweep_highlight
    sw_sup_sc  = args.sweep_sup_scale
    sw_sup_el  = args.sweep_sup_elev
    sw_sup_k   = args.sweep_sup_kern

    # Superscript special-symbol codes (® ™ © ℗) present in this text
    _SUP = {0xAE, 0x2122, 0xA9, 0x2117}
    sw_sup_in  = sorted(_SUP.intersection(ord(c) for c in chars if ord(c) in cmap))
    sw_isSup   = '||'.join(f'c=={code}' for code in sw_sup_in) if sw_sup_in else 'false'
    # Adjusted total advance: superscript chars take sw_sup_sc of normal width
    sw_adv_adj = sum(
        meta_vals.get(ord(c),(0,0,0,0))[2] * (sw_sup_sc if ord(c) in _SUP else 1.0)
        for c in chars if ord(c) in cmap)

    sw_codes = [ord(c) if ord(c) in cmap else 32 for c in chars]
    sw_n     = len(sw_codes)
    sw_codes_str = ', '.join(str(c) for c in sw_codes)

    ys = [(FONT_BASE - meta_vals[ord(c)][1] - meta_vals[ord(c)][3],
           FONT_BASE - meta_vals[ord(c)][1])
          for c in chars if ord(c) in meta_vals and meta_vals[ord(c)][3] > 0]
    sw_ycenter = (min(b for b,_ in ys) + max(t for _,t in ys)) / 2.0 if ys else 0.0

    sw_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            sw_sdf_src.append(gen_sdf_fn_fire(fn, contours))

    sw_disp = '\n'.join(
        f"  if(_GC=={code}) return {fn}(p);"
        for code, fn in sorted(glyph_fns.items()))

    glsl_sweep = f"""\
// {name} -- Sweep effect (RGSS antialiased)
{font_comment}
// Single-tab Shadertoy paste -- no Buffer A, no iChannel needed.
//
// Key parameters (re-run to change):
//   --sweep-ch           {sw_ch}   text height fraction
//   --sweep-aura         {sw_aura}   aura radius in font units
//   --sweep-speed        {sw_speed}   sweep wave speed
//   --sweep-wave-width   {sw_wave_w}   spatial period as screen fraction
//   --sweep-angle        {sw_angle}   band angle in degrees (0=horizontal, 90=vertical)
//   --sweep-cr-power     {sw_cr_pow}   wave exponent (lower=wider bright bands)
//   --sweep-base-color   {sweep_br:.3f},{sweep_bg:.3f},{sweep_bb:.3f}
//   --sweep-primary-color {sweep_pr:.3f},{sweep_pg:.3f},{sweep_pb:.3f}
//   --sweep-secondary-color {sweep_sr:.3f},{sweep_sg:.3f},{sweep_sb:.3f}

#define PI 3.1415926

// ── effect constants ──────────────────────────────────────────────────────────
const vec4  BASE_COLOR   = vec4({sweep_br:.4f},{sweep_bg:.4f},{sweep_bb:.4f},1.);
const vec4  PRIM_COLOR   = vec4({sweep_pr:.4f},{sweep_pg:.4f},{sweep_pb:.4f},1.);
const vec3  SEC_COLOR    = vec3({sweep_sr:.4f},{sweep_sg:.4f},{sweep_sb:.4f});
const float AURA_R       = {sw_aura:.1f};
const float SWEEP_SPEED  = {sw_speed:.4f};
const float SWEEP_WIDTH  = {sw_wave_w:.4f};
const float SWEEP_ANGLE  = {sw_angle:.4f};
// SWEEP_PAUSE 0=continuous wave  0.5=half-cycle rest  0.8=long gap between pulses
const float SWEEP_PAUSE  = {sw_pause:.4f};
// HIGHLIGHT: scales sweep bands before tone-map (>1 = more pronounced)
const float HIGHLIGHT    = {sw_hl:.4f};
const float CH           = {sw_ch:.4f};
const float ADV          = {sw_adv_adj:.4f};  // adjusted for superscript advance
// vec2 SC controls text stretch — passed from --scale X,Y
// e.g. vec2(0.5,1.0) doubles width, vec2(1.0,0.5) doubles height
const vec2  SC           = vec2({sc_x:.4f},{sc_y:.4f});
// Superscript: special symbols (® ™ etc.) rendered at SUP_SCALE, elevated SUP_ELEV
const float SUP_SCALE    = {sw_sup_sc:.4f};
const float SUP_ELEV     = {sw_sup_el:.4f};
// SUP_KERN: pull superscript towards preceding char (fraction of glyph width)
const float SUP_KERN     = {sw_sup_k:.4f};

const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

// Per-glyph SDFs (no per-function bbox guard)
{chr(10).join(sw_sdf_src)}

int _GC = 0;
{rect_tbl}
{meta_tbl}

float cSDF(vec2 p){{
{sw_disp}
  return 1e9;
}}

// Aspect-corrected lab -> font pixel space
vec2 fontUV(vec2 lab, float ch, float adv){{
    float p = LINE_H / ch;
    return vec2(lab.x*p/SC.x + adv*.5, lab.y*p/SC.y + {sw_ycenter:.4f});
}}

// ── core render (called 4x by RGSS) ──────────────────────────────────────────
vec4 render(vec2 fc){{
    vec2 lab = fc / iResolution.xy - .5;
    lab.x   *= iResolution.x / iResolution.y;
    vec2 fuv = fontUV(lab, CH, ADV);

    // "{aclean(chars)}" -- {sw_n} glyphs
    int codes[{sw_n}] = int[]({sw_codes_str});

    vec4  Cm  = vec4(0.);
    float al  = 0.;
    float cx2 = 0.;

    for (int i = 0; i < {sw_n}; i++){{
        int  c  = codes[i];
        vec4 gr = getGlyphRect(c);
        vec4 mt = getGlyphMeta(c);
        // Special symbols rendered smaller and elevated (superscript)
        bool isSup = ({sw_isSup});
        float kernPx = isSup ? gr.z * SUP_KERN : 0.;   // px to pull towards prev char

        if (c != 32){{
            vec2 bl = vec2(cx2 + mt.x - kernPx, FONT_BASE - mt.y - mt.w);
            vec2 sz = vec2(gr.z, mt.w);
            vec2 lc = (fuv - bl) / sz;

            float auraInLc = AURA_R / max(sz.x, sz.y);
            if (all(greaterThanEqual(lc, vec2(-auraInLc))) &&
                all(lessThanEqual  (lc, vec2(1. + auraInLc)))){{

                vec2  gp = gr.xy + lc * gr.zw;
                // Superscript: scale around elevated centre
                if (isSup) {{
                    vec2 cen = gr.xy + gr.zw*0.5 + vec2(0., sz.y*SUP_ELEV);
                    gp = cen + (gp - cen) / SUP_SCALE;
                }}
                float d  = cSDF(gp);

                // Euclidean gradient -- more accurate than fwidth at curves
                float fw = max(length(vec2(dFdx(d), dFdy(d))), 0.5);

                float textEdgeDist = smoothstep( fw*2., -fw*2., d);
                float auraEdgeDist = smoothstep(AURA_R,     0., d);
                float fillMask     = smoothstep( fw*2., -fw*2., d);

                // Bbox fade -- no hard rectangular cutoff at aura edge
                float outsideDist = max(max(-lc.x, lc.x-1.), max(-lc.y, lc.y-1.));
                float bboxFade    = smoothstep(auraInLc, 0., max(0., outsideDist));

                // ── sweep effect ─────────────────────────────────────────────
                float Co = textEdgeDist - 0.42;

                float Cp = Co / max(auraEdgeDist, 0.001);
                Cp = smoothstep(0., 1., 1. - clamp(abs(Cp), 0., 1.));

                vec4 frag  = mix(BASE_COLOR, PRIM_COLOR, Cp);
                frag.rgb  += pow(Cp, 14.) * 3.;
                frag.rgb  += SEC_COLOR * smoothstep(0.5, 0.7, Co);

                // Tilted sweep wave with optional pause between passes
                float rad        = SWEEP_ANGLE / 180.0;
                float sweepCoord = dot(fc / iResolution.xy,
                                       vec2(cos(rad), sin(rad)));
                float rawCr = abs(cos(iTime * SWEEP_SPEED
                                 - sweepCoord / SWEEP_WIDTH));
                // Pause: stretch rawCr toward 1 so the band fires only briefly
                // SWEEP_PAUSE=0 → original, 0.7 → band takes ~30% of cycle
                float Cr = min(rawCr / max(1.0 - SWEEP_PAUSE, 0.01), 1.0);
                float Cs = max(auraEdgeDist * (0.3 + 0.7 * pow(Cr, {sw_cr_pow:.4f})), 0.);

                frag     /= Cs;
                frag.rgb *= HIGHLIGHT;               // pronounce the sweep bands
                frag.a   *= auraEdgeDist;
                frag     *= auraEdgeDist - 0.1;
                frag     *= fillMask;
                frag      = clamp(frag, 0., 2.);

                float blend = frag.a * (1. - al) * bboxFade;
                Cm.rgb += frag.rgb * blend;
                al      = clamp(al + blend, 0., 1.);
            }}
        }}
        cx2 += isSup ? mt.z * SUP_SCALE : mt.z;
    }}
    return vec4(Cm.rgb, 1.);
}}

// ── main: 4-tap Rotated Grid Super-Sampling ──────────────────────────────────
void mainImage(out vec4 fragColor, in vec2 fragCoord){{
    fragColor = (
        render(fragCoord + vec2( 0.125,  0.375)) +
        render(fragCoord + vec2( 0.375, -0.125)) +
        render(fragCoord + vec2(-0.125, -0.375)) +
        render(fragCoord + vec2(-0.375,  0.125))
    ) * 0.25;
}}
"""

    outfile_sweep = os.path.join(outdir, f"{name}_sweep.glsl")
    open(outfile_sweep, 'w').write(aclean(glsl_sweep))
    bad_sw = [x for x in open(outfile_sweep).read() if ord(x) > 127]
    print(f"\nWrote (sweep): {outfile_sweep}")
    print(f"  Chars:{sw_n}  Advance:{total_adv:.2f}px  yCentre:{sw_ycenter:.2f}")
    print(f"  ch:{sw_ch}  aura:{sw_aura}  speed:{sw_speed}  "
          f"wave_width:{sw_wave_w}  angle:{sw_angle}deg  cr_power:{sw_cr_pow}  pause:{sw_pause}")
    print(f"  base:({sweep_br:.3f},{sweep_bg:.3f},{sweep_bb:.3f})  "
          f"primary:({sweep_pr:.3f},{sweep_pg:.3f},{sweep_pb:.3f})  "
          f"secondary:({sweep_sr:.3f},{sweep_sg:.3f},{sweep_sb:.3f})")
    print(f"  ASCII-clean: {'OK' if not bad_sw else str(len(bad_sw))+' remaining!'}")

# ── sweep-3d shader (raymarched extrusion + sweep surface color) ──────────────
if args.sweep_3d:
    s3_depth  = args.sweep_3d_depth
    s3_bevel  = args.sweep_3d_bevel
    s3_ty     = args.sweep_3d_ty
    s3_dist   = args.sweep_3d_dist
    # reuse all sweep visual params
    s3_aura   = args.sweep_aura
    s3_speed  = args.sweep_speed
    s3_wave_w = args.sweep_wave_width
    s3_angle  = args.sweep_angle
    s3_cr_pow = args.sweep_cr_power
    s3_hl     = args.sweep_highlight
    s3_sup_sc = args.sweep_sup_scale
    s3_sup_el = args.sweep_sup_elev
    s3_sup_k  = args.sweep_sup_kern
    _SUP3     = {0xAE, 0x2122, 0xA9, 0x2117}

    s3_codes     = [ord(c) if ord(c) in cmap else 32 for c in chars]
    s3_n         = len(s3_codes)
    s3_codes_str = ', '.join(str(c) for c in s3_codes)

    # Single set of SDF functions (no bbox guard) — clean gradients, no banding.
    # X-range skip in fontDist handles culling instead.
    s3_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if (gname not in gs and gname not in _synth_data) or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            s3_sdf_src.append(gen_sdf_fn_fire(f"s3_{fn}", contours))

    # fontDist lines with per-glyph X-range skip + superscript kern baked in.
    s3_font_lines = []
    s3_margin  = s3_aura + 5.0

    # Step 1: compute true 3D total advance (scaled sup + kern) for centering
    total_adv_3d = 0.0
    for c in chars:
        code = ord(c)
        if code not in cmap or code == 32:
            if code in meta_vals: total_adv_3d += meta_vals[code][2]
            continue
        if code not in meta_vals: continue
        if code in _SUP3 and code in rect_vals:
            kern_px = rect_vals[code][2] * s3_sup_k
            total_adv_3d += meta_vals[code][2] * s3_sup_sc - kern_px
        else:
            total_adv_3d += meta_vals[code][2]
    half_adv_3d = total_adv_3d * 0.5

    # Step 2: build fontDist lines using kerned positions
    cx_acc = 0.0
    glyph_idx = 0   # counter for early-out on first 2 glyphs
    for c in chars:
        code = ord(c)
        if code not in cmap or code == 32:
            if code in meta_vals: cx_acc += meta_vals[code][2]
            continue
        fn = glyph_fns.get(code, f"sdf{code}")

        if code in _SUP3 and code in rect_vals:
            kern_px = rect_vals[code][2] * s3_sup_k
            cx_acc -= kern_px          # pull sup glyph toward previous char

        offset_x = half_adv_3d - cx_acc

        if code in rect_vals:
            gx0   = rect_vals[code][0]
            gw    = rect_vals[code][2]
            gy0   = rect_vals[code][1]
            gh    = rect_vals[code][3]
            fp_lo = gx0 - offset_x - s3_margin
            fp_hi = gx0 + gw - offset_x + s3_margin
            if code in _SUP3:
                cen_x = gx0 + gw * 0.5
                cen_y = gy0 + gh * 0.5 + gh * s3_sup_el
                s3_font_lines.append(
                    f"  if(x>{fp_lo:.1f}&&x<{fp_hi:.1f}){{"
                    f" vec2 _c=vec2({cen_x:.4f},{cen_y:.4f});"
                    f" d=min(d,s3_{fn}(_c+(fp+vec2({offset_x:.4f},0.)-_c)/SUP_SCALE)); }}")
            else:
                early = ' if(d<0.) return d;' if glyph_idx < 2 else ''
                s3_font_lines.append(
                    f"  if(x>{fp_lo:.1f}&&x<{fp_hi:.1f})"
                    f"{{ d=min(d,s3_{fn}(fp+vec2({offset_x:.4f},0.)));{early} }}")
                glyph_idx += 1
        else:
            s3_font_lines.append(
                f"  d=min(d,s3_{fn}(fp+vec2({offset_x:.4f},0.)));")

        if code in meta_vals:
            if code in _SUP3:
                cx_acc += meta_vals[code][2] * s3_sup_sc  # scaled advance (kern already deducted)
            else:
                cx_acc += meta_vals[code][2]

    s3_font_body = '\n'.join(s3_font_lines)

    # Compute actual glyph Y extent from rect_vals for proper bbox + centering.
    ys_3d = []
    for code in ucodes_sdf:
        if code in rect_vals:
            y0 = rect_vals[code][1]
            h  = rect_vals[code][3]
            ys_3d.append(y0)
            ys_3d.append(y0 + h)
    if ys_3d:
        s3_y_min    = min(ys_3d)
        s3_y_max    = max(ys_3d)
        s3_y_center = (s3_y_min + s3_y_max) * 0.5
        s3_bbox_y   = (s3_y_max - s3_y_min) * 0.5 / LINE_H + 0.12
    else:
        s3_y_center = LINE_H * 0.5
        s3_bbox_y   = 0.60

    # Outer scene bounding box (world units)
    s3_bbox_x = total_adv / LINE_H * 0.5 + 0.15

    glsl_sweep3d = f"""\
// ============================================================
//  FontyMon v2.0  --  Raymarched extruded bezier SDF text
//
{font_comment}
//
//  Letters Sweep 3D (--sweep-3d option)
//
//  Shadertoy setup:
//    Buffer A tab  -> paste {name}_sweep3d_bufA.glsl
//    Image tab     -> paste this file
//    Image tab iChannel0 -> click slot, select "Buffer A"
//
//  The procedural texture in Buffer A is sampled via
//  texture(iChannel0, ...) in sweepColor to add animated
//  volumetric color on the text surface interior.
//
//  List of all fonts available:  https://tinyurl.com/yn75rfhj
//
//  Contact me: subband@gmail.com or subband@protonmail.com
//      github: https://github.com/mewza
// ============================================================

#define PI 3.1415926

// -- effect constants ----------------------------------------------------------
const vec3  BASE_COLOR  = vec3({sweep_br:.4f},{sweep_bg:.4f},{sweep_bb:.4f});
const vec3  PRIM_COLOR  = vec3({sweep_pr:.4f},{sweep_pg:.4f},{sweep_pb:.4f});
const vec3  SEC_COLOR   = vec3({sweep_sr:.4f},{sweep_sg:.4f},{sweep_sb:.4f});
const float AURA_R      = {s3_aura:.4f};
const float SWEEP_SPEED = {s3_speed:.4f};
const float SWEEP_WIDTH = {s3_wave_w:.4f};
const float SWEEP_ANGLE = {s3_angle:.4f};
const float CR_POW      = {s3_cr_pow:.4f};
// HIGHLIGHT: scales sweep bands before tone-map (>1 = more pronounced)
const float HIGHLIGHT   = {s3_hl:.4f};
// SUP_SCALE: special symbols (- - -) rendered at this fraction of normal size
const float SUP_SCALE   = {s3_sup_sc:.4f};
// DEPTH: extrusion thickness in world units (--sweep-3d-depth)
const float DEPTH       = {s3_depth:.4f};
const float BEVEL       = {s3_bevel:.4f};
const float LINE_H      = {LINE_H:.4f};
const float TOTAL_ADV   = {total_adv:.4f};
// Y_CENTER: shifts glyphs so they sit centred on world y=0
const float Y_CENTER    = {s3_y_center:.4f};
// TY: additional world-space vertical shift (--sweep-3d-ty, negative = down)
const float TY          = {s3_ty:.4f};
// DISTANCE: camera distance -- increase to zoom out (--sweep-3d-dist)
const float DISTANCE    = {s3_dist:.4f};
const vec3  BBOX        = vec3({s3_bbox_x:.4f},{s3_bbox_y:.4f},DEPTH+BEVEL+0.05);

{BEZIER}

// -- SDFs (no bbox guard -- clean gradients, X-range skip handles culling) ------
{chr(10).join(s3_sdf_src)}

// -- fontDist: per-glyph X-range skip -----------------------------------------
// fp = toFP(pos.xy)  -- font pixel space, horizontally and vertically centred
float fontDist(vec2 fp){{
  float d=1e9, x=fp.x;
{s3_font_body}
  return d;
}}

// World XY - font pixel space (centred + optional vertical shift)
vec2 toFP(vec2 pxy){{ return (pxy - vec2(0., TY)) * LINE_H + vec2(0., Y_CENTER); }}

// -- scene SDF ----------------------------------------------------------------
float sceneSDF(vec3 p){{
  vec3 q=abs(p)-BBOX;
  if(any(greaterThan(q,vec3(0.02)))) return length(max(q,0.))+0.01;
  float d2=fontDist(toFP(p.xy))/LINE_H;
  vec2  w=vec2(d2,abs(p.z)-DEPTH);
  return min(max(w.x,w.y),0.)+length(max(w,0.))-BEVEL;
}}

// -- normal: central differences XY + analytical Z ----------------------------
vec3 calcNormal(vec3 p, float fd)
{{
    float e2 = 3e-4 * LINE_H;
    vec2  fp = toFP(p.xy);

    // Central differences: 4 fontDist calls total (was 6x sceneSDF)
    float nx = fontDist(fp + vec2(e2, 0.)) - fontDist(fp - vec2(e2, 0.));
    float ny = fontDist(fp + vec2(0., e2)) - fontDist(fp - vec2(0., e2));

    // Analytical Z from extrusion geometry
    float d2s = fd / LINE_H;
    float dz  = abs(p.z) - DEPTH;
    vec2  w   = max(vec2(d2s, dz), 0.0);
    float wL  = length(w);
    float nz  = sign(p.z) * (wL > 1e-5 ? w.y / wL : float(dz > d2s));

    vec3 n = vec3(nx, ny, nz * LINE_H);
    return normalize(n);
}}

// -- raymarcher: 28 steps + over-relaxation -----------------------------------
float march(vec3 ro, vec3 rd){{
  vec3 q=abs(ro)-BBOX; float skip=length(max(q,0.));
  float t=max(0.,skip-0.02);
  float prev=1e9;
  for(int i=0;i<28;i++){{
    float h=sceneSDF(ro+rd*t);
    if(h<0.0001) return t;
    if(t>10.)    return -1.;
    // Over-relax, but pull back if we overshot
    float step_t=(h+prev>1.4*h)?h*1.4:h;
    prev=h;
    t+=step_t;
  }}
  return -1.;
}}

// -- surface color with Gouraud shading + sweep -------------------------------
vec3 sweepColor(vec3 pos, vec3 nor, float fd, vec3 rd){{
  const float fw = 2.5;
  float textEdge = smoothstep( fw,-fw, fd);
  float auraEdge = smoothstep(AURA_R,0.,fd);

  float Co = textEdge-0.42;
  float Cp = Co/max(auraEdge,0.001);
  Cp = smoothstep(0.,1.,1.-clamp(abs(Cp),0.,1.));

  // Inner hue: dark indigo tint so interior reads differently from purple edge
  vec3 innerCol = PRIM_COLOR + vec3(0.02, 0.0, 0.18);
  vec3 baseCol = mix(BASE_COLOR, innerCol, Cp);
   
  // === BASIC GOURAUD SHADING ===
  vec3 lightDir = normalize(vec3(sin(iTime*0.2)*0.6 + 0.4, 
                               0.9, 
                               cos(iTime*0.2)*0.5));
  float diffuse = max(dot(nor, lightDir), 0.0);
  
  // Optional second fill light (soft from opposite side)
  vec3 fillDir = normalize(vec3(-0.4, 0.3, -0.6));
  float fill = max(dot(nor, fillDir), 0.0) * 0.35;
  
  float ambient = 0.25;  // base ambient level
  
  float lighting = ambient + diffuse * 0.85 + fill;
  lighting = clamp(lighting, 0.0, 1.2);  // slight overbright allowed for highlights

  vec3 litCol = baseCol * lighting;
  float specular = pow(max(dot(reflect(-lightDir, nor), -rd), 0.0), 16.0);
  litCol += vec3(1.0) * specular * 0.6;

  // === Original sweep / aura effects (applied on top of lit color) ===
  float rad        = SWEEP_ANGLE/180.0;
  float sweepCoord = dot(pos.xy,vec2(cos(rad),sin(rad)))*LINE_H/TOTAL_ADV;
  float Cr = abs(cos(iTime*SWEEP_SPEED - sweepCoord/SWEEP_WIDTH));
  float Cs = max(auraEdge*(0.02+0.98*pow(Cr,CR_POW)),0.);

  litCol +=  smoothstep(1.,.0, fd) * texture(iChannel0, mod(pos.xy+0.3,vec2(1))).rgb;
  litCol *=  4. * litCol;
  
  litCol /= max(Cs,0.0002);
  litCol *= HIGHLIGHT;

  litCol *= max(auraEdge-0.1,0.);
  litCol += BASE_COLOR*pow(Cp,14.)*3.;
  litCol += SEC_COLOR*smoothstep(0.5,0.7,Co)*auraEdge;

  // White injection weighted by aura
  float outMask = smoothstep(-2.5, 6.0, fd);
  float intens  = length(litCol);
  litCol += intens * 0.85 * outMask;
  
  litCol  = 1.0 - exp(-litCol * 0.9);
  
  // Final view-dependent tweak (keeps some of your original feel)
  litCol *= 0.6 + 0.4*abs(nor.z);

  return litCol;
}}

// -- main: fd computed once, shared by calcNormal + sweepColor -----------------
void mainImage(out vec4 fragColor, in vec2 fragCoord){{
  vec2 uv = (fragCoord-iResolution.xy*.5)/iResolution.y;

  float camAngle = (iMouse.z>0.)
    ? (iMouse.x/iResolution.x-0.5)*PI*2.
    : sin(iTime*0.3)*0.6;
  float camElev = (iMouse.z>0.)
    ? (iMouse.y/iResolution.y-0.5)*PI*0.8
    : -0.18;

  vec3 ro = vec3(sin(camAngle)*cos(camElev),
                 sin(camElev),
                 cos(camAngle)*cos(camElev))*DISTANCE;
  vec3 ww = normalize(-ro);
  vec3 uu = normalize(cross(ww,vec3(0.,1.,0.)));
  vec3 vv = cross(uu,ww);
  vec3 rd = normalize(uv.x*uu+uv.y*vv+1.5*ww);

  vec3 col = vec3(0.);
  float t  = march(ro,rd);
  if(t>0.){{
    vec3  pos = ro+rd*t;
    float fd  = fontDist(toFP(pos.xy));    // computed ONCE
    vec3  nor = calcNormal(pos, fd);
    col       = sweepColor(pos, nor, fd, rd);
  }}

  fragColor = vec4(col,1.);
}}
"""

    outfile_s3d = os.path.join(outdir, f"{name}_sweep3d.glsl")
    open(outfile_s3d, 'w').write(aclean(glsl_sweep3d))
    bad_s3 = [x for x in open(outfile_s3d).read() if ord(x) > 127]

    # ── Buffer A shader (procedural texture sampled by iChannel0) ─────────
    glsl_bufA = f"""\
// ============================================================
//  FontyMon v2.0  --  Buffer A  (procedural texture for sweep-3d)
//
{font_comment}
//
//  Shadertoy setup:
//    Buffer A tab  -> paste this code
//    Image tab     -> paste {name}_sweep3d.glsl
//    Image tab iChannel0 -> set to "Buffer A"
//
//  Two layered volumetric effects mixed 30/70:
//    getMainImage  : swirling cos-lattice accumulator (80 iters)
//    getMainImage2 : folded-space rings (20 outer x 8 inner iters)
//  Both use tanh compression so later iterations contribute
//  diminishing visible difference.
// ============================================================

vec4 getMainImage(vec2 fragCoord) {{
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    vec4 o = vec4(0.0);
    float t = 4.0 * iTime;
    float t02 = t * 0.2;
    float t05 = t * 0.5;
    vec3 rd = normalize(vec3(uv, 0.95));
    float z = 0.0;
    for (int i = 0; i < 80; i++) {{
        vec3 p = z * rd;
        p.z += t;
        // Swirl
        float swirl = 0.1 * sin(length(p.xy) - t05);
        float cs = cos(swirl), ss = sin(swirl);
        p.xy = mat2(cs,-ss,ss,cs) * p.xy;
        // Rotation (only .x component of angle matters: 0.0)
        float a = z * 0.3 + t02;
        float ca = cos(a), sa = sin(a);
        p.xy = mat2(ca,-sa,sa,ca) * p.xy;
        // SDF + accumulate
        vec3 q = cos(p.yzx + p.z - t02);
        float d = length(cos(p + q).xy) * 0.2;
        z += d;
        o += (sin(p.x + t + vec4(0.0, 2.0, 3.0, 0.0)) + 0.8) / d;
    }}
    return vec4((3.0 * tanh(o / 6000.0)).rgb, 1.0);
}}

vec4 getMainImage2(vec2 fragCoord) {{
    float d = 0.0;
    float t = iTime;
    vec4 color = vec4(0.0);
    vec3 rd = normalize(vec3(2.0 * fragCoord - iResolution.xy, -iResolution.y));
    for (int i = 0; i < 20; i++) {{
        vec3 p = d * rd;
        p.z -= t;
        float s = 0.1;
        for (int j = 0; j < 8; j++) {{
            p -= dot(cos(t + p * (s * 16.0)), vec3(0.01)) / s;
            p += sin(p.yzx * 3.0) * 0.3;
            s *= 0.9;
        }}
        s = 0.02 + abs(3.0 - length(p.yx)) * 0.3;
        d += s;
        color += (0.1 + cos(d + vec4(4.0, 2.0, 1.0, 0.0))) / s;
    }}
    return tanh(color / 500.0);
}}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {{
    fragColor = mix(
        getMainImage(fragCoord),
        getMainImage2(fragCoord),
        0.7
    );
}}
"""

    outfile_bufA = os.path.join(outdir, f"{name}_sweep3d_bufA.glsl")
    open(outfile_bufA, 'w').write(aclean(glsl_bufA))
    bad_bufA = [x for x in open(outfile_bufA).read() if ord(x) > 127]

    print(f"\nWrote (sweep-3d Image): {outfile_s3d}")
    print(f"Wrote (sweep-3d Buffer A): {outfile_bufA}")
    print(f"  Shadertoy setup:")
    print(f"    1. Buffer A tab  -> paste {name}_sweep3d_bufA.glsl")
    print(f"    2. Image tab     -> paste {name}_sweep3d.glsl")
    print(f"    3. Image tab iChannel0 -> click slot, select 'Buffer A'")
    print(f"  Chars:{s3_n}  depth:{s3_depth}  bevel:{s3_bevel}  aura:{s3_aura}")
    print(f"  speed:{s3_speed}  wave_width:{s3_wave_w}  angle:{s3_angle}  "
          f"cr_power:{s3_cr_pow}")
    print(f"  ASCII-clean Image: {'OK' if not bad_s3 else str(len(bad_s3))+' remaining!'}")
    print(f"  ASCII-clean BufA:  {'OK' if not bad_bufA else str(len(bad_bufA))+' remaining!'}")

# ── voodoo shader ─────────────────────────────────────────────────────────────
if args.voodoo:
    vd_ch    = args.voodoo_ch
    vd_speed = args.voodoo_speed
    vd_iters = max(1, min(16, args.voodoo_iters))

    vd_codes = [ord(c) if ord(c) in cmap else 32 for c in chars]
    vd_n     = len(vd_codes)
    vd_codes_str = ', '.join(str(c) for c in vd_codes)

    ys = [(FONT_BASE - meta_vals[ord(c)][1] - meta_vals[ord(c)][3],
           FONT_BASE - meta_vals[ord(c)][1])
          for c in chars if ord(c) in meta_vals and meta_vals[ord(c)][3] > 0]
    vd_ycenter = (min(b for b,_ in ys) + max(t for _,t in ys)) / 2.0 if ys else 0.0

    vd_sdf_src = []
    for code in ucodes_sdf:
        gname = cmap[code]
        if gname not in gs or code == 32: continue
        contours = get_contours(gname)
        if contours:
            fn = glyph_fns.get(code, f"sdf{code}")
            vd_sdf_src.append(gen_sdf_fn_fire(fn, contours))

    vd_disp = '\n'.join(
        f"  if(_GC=={code}) return {fn}(p);"
        for code, fn in sorted(glyph_fns.items()))

    glsl_voodoo = f"""\
// {name} -- VooDoo fractal effect
{font_comment}
// ─────────────────────────────────────────────────────────────────────────────
// Effect ported from Fontskin "VooDoo" preset (doc5).
// Single-tab Shadertoy paste -- no Buffer A, no iChannel needed.
//
// Algorithm (translated from doc5 shader):
//   1. outlineProgress = polar angle from glyph bbox centre [0,1]
//      (approximates Fontskin's arc-length parameterisation)
//   2. edgeDist = 0.743 - sdfFont  (positive outside, negative deep inside)
//   3. op = outlineProgress * edgeDist  (modulates by edge proximity)
//   4. uv = (op, sdfFont*0.4 - 0.9)   (fractal domain: angle x depth)
//   5. Fractal fold loop ({vd_iters}x): fract(uv*1.5)-0.5 + cosine palette spike
//   6. alpha = min(sdfFont, luma)       (clips result to text silhouette)
//
// Color palette: Cm(t) = 0.5 + 0.5*cos(2pi*(t + Cr))
//   Cr = ({voodoo_cr:.3f}, {voodoo_cg:.3f}, {voodoo_cb:.3f})
//   (0,0,0) = white/gray   |   (0, 0.333, 0.667) = rainbow
//
// Key parameters (re-run to change):
//   --voodoo-ch      {vd_ch}    text height fraction
//   --voodoo-color   {voodoo_cr:.3f},{voodoo_cg:.3f},{voodoo_cb:.3f}  palette phase
//   --voodoo-speed   {vd_speed}   animation speed
//   --voodoo-iters   {vd_iters}     fractal iterations

const float LINE_H    = {LINE_H:.4f};
const float FONT_BASE = {FONT_BASE:.4f};

{BEZIER}

// Per-glyph SDFs (no per-function bbox guard)
{chr(10).join(vd_sdf_src)}

int _GC = 0;
{rect_tbl}
{meta_tbl}

float cSDF(vec2 p){{
{vd_disp}
  return 1e9;
}}

// Aspect-corrected lab -> font pixel space
vec2 fontUV(vec2 lab, float ch, float adv){{
    float p = LINE_H / ch;
    return vec2(lab.x*p + adv*.5, lab.y*p + {vd_ycenter:.4f});
}}

// Cosine colour palette (IQ-style) — Cr is the phase offset per channel.
// Cr = ({voodoo_cr:.3f}, {voodoo_cg:.3f}, {voodoo_cb:.3f})
vec3 _palette(float t){{
    const vec3 Cr = vec3({voodoo_cr:.4f}, {voodoo_cg:.4f}, {voodoo_cb:.4f});
    return vec3(0.5) + vec3(0.5) * cos(6.28318 * (vec3(1.) * t + Cr));
}}

void mainImage(out vec4 fragColor, in vec2 fragCoord){{
    vec2 lab = fragCoord / iResolution.xy - .5;
    lab.x   *= iResolution.x / iResolution.y;
    vec2 fuv = fontUV(lab, {vd_ch:.4f}, {total_adv:.4f});

    // "{aclean(chars)}" -- {vd_n} glyphs
    int codes[{vd_n}] = int[]({vd_codes_str});

    vec3  col = vec3(0.);
    float al  = 0.;
    float cx2 = 0.;

    for (int i = 0; i < {vd_n}; i++){{
        int  c  = codes[i];
        vec4 gr = getGlyphRect(c);
        vec4 mt = getGlyphMeta(c);

        if (c != 32){{
            vec2 bl = vec2(cx2 + mt.x, FONT_BASE - mt.y - mt.w);
            vec2 sz = vec2(gr.z, mt.w);
            vec2 lc = (fuv - bl) / sz;

            if (all(greaterThanEqual(lc, vec2(0.))) &&
                all(lessThanEqual  (lc, vec2(1.)))){{

                vec2  gp = gr.xy + lc * gr.zw;
                float d  = cSDF(gp);
                float fw = max(fwidth(d), .001);

                // Fontskin-style SDF encoding: 0.5 at edge, soft 6*fw transition
                float sdfFont  = smoothstep(fw*6., -fw*6., d);

                // edgeDist: mirrors Fontskin's -(sdfFont - textbuffer - textgamma - 0.035)
                // positive outside/at-edge, goes negative deep inside the stroke
                float edgeDist = 0.743 - sdfFont;

                // outlineProgress: polar angle from glyph bbox centre -> [0,1]
                // Approximates Fontskin's arc-length parameterisation.
                vec2  ctr = gr.xy + gr.zw * .5;
                float op  = atan(gp.y - ctr.y, gp.x - ctr.x) / (2. * acos(-1.)) + .5;

                // Doc5 line: outlineProgress *= edgeDist
                op *= edgeDist;

                // Fractal domain: x = outline position * depth, y = SDF depth
                vec2 uv = vec2(op, sdfFont * 0.4 - 0.9);
                vec2 Cu = uv;

                // Fractal fold loop (doc5: 4 iterations)
                vec3 Cv = vec3(0.);
                for (float Cw = 0.; Cw < {float(vd_iters):.1f}; Cw++){{
                    uv = fract(uv * 1.5) - 0.5;
                    float r = length(uv) * exp(-length(Cu));
                    vec3  Cx = _palette(length(Cu) + Cw * .4 + iTime * {vd_speed:.4f});
                    r = sin(r * 8. + iTime + fragCoord.x / 100.) / 8.;
                    r = abs(r);
                    // Smooth spike: larger guard (0.008) tames the worst noise;
                    // clamp per-iteration contribution to cap total brightness.
                    r = pow(0.01 / max(r, 0.008), 1.2);
                    Cv += Cx * min(r, 4.0);
                }}

                // Smooth bbox fade: ramps to zero within 4% of each bbox edge,
                // preventing the hard rectangular cutoff artifact.
                float bboxFade = smoothstep(0., 0.04,
                    min(min(lc.x, 1. - lc.x), min(lc.y, 1. - lc.y)));

                // Alpha: luma brightness clamped to SDF extent then bbox-faded
                float alpha = min(sdfFont, min(1., Cv.r + Cv.g + Cv.b));
                float blend = alpha * (1. - al) * bboxFade;
                col += Cv * blend;
                al   = clamp(al + blend, 0., 1.);
            }}
        }}
        cx2 += mt.z;
    }}

    fragColor = vec4(col, 1.);
}}
"""

    outfile_voodoo = os.path.join(outdir, f"{name}_voodoo.glsl")
    open(outfile_voodoo, 'w').write(aclean(glsl_voodoo))
    bad_vd = [x for x in open(outfile_voodoo).read() if ord(x) > 127]
    print(f"\nWrote (voodoo): {outfile_voodoo}")
    print(f"  Chars:{vd_n}  Advance:{total_adv:.2f}px  yCentre:{vd_ycenter:.2f}")
    print(f"  ch:{vd_ch}  speed:{vd_speed}  iters:{vd_iters}")
    print(f"  palette Cr:({voodoo_cr:.3f},{voodoo_cg:.3f},{voodoo_cb:.3f})")
    print(f"  ASCII-clean: {'OK' if not bad_vd else str(len(bad_vd))+' remaining!'}")
