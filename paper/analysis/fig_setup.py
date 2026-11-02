"""Figure: (a) the simulated workspace; (b) information flow. The executor sees only the perturbed reports and its own
primitive feedback; the independent evaluator reads the simulator directly and is used only for scoring."""
from common import setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
import matplotlib.image as mpimg
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
fig = plt.figure(figsize=(WIDTH, 52*MM))
a1 = fig.add_axes([0.0, 0.0, 0.40, 0.88]); a2 = fig.add_axes([0.42, 0.0, 0.58, 0.88])
hi = OUT/'figures/scene_main_2048.png'   # 2048 px render from HiResCapture.cs; falls back to the 512 px capture
img = mpimg.imread(str(hi if hi.exists() else OUT/'figures/scene_main_rgb.jpg')); H = img.shape[0]
a1.imshow(img[round(40*H/512):round(470*H/512), :, :3], interpolation='none'); a1.set_axis_off()   # 'none': embed at native resolution
fig.text(0.0, 0.95, '(a) Simulated workspace', fontsize=8); fig.text(0.42, 0.95, '(b) Information flow', fontsize=8)
for txt, xy, xt in [('red cube', (108, 342), (40, 410)), ('bowl', (398, 340), (430, 410)), ('plate', (455, 300), (440, 235)),
                    ('green ball', (45, 320), (5, 240)), ('cylinder', (57, 288), (95, 205))]:
    k = H/512; a1.annotate(txt, (xy[0]*k, xy[1]*k), xytext=(xt[0]*k, xt[1]*k), fontsize=6.5, color='white', arrowprops=dict(arrowstyle='-', color='white', lw=0.6),
                bbox=dict(boxstyle='round,pad=0.15', fc='black', ec='none', alpha=0.55))
a2.set_xlim(0, 100); a2.set_ylim(0, 50); a2.set_axis_off()
def box(x, y, w, h, text, fc='white', ec='0.3', lw=0.7, ls='-'):
    a2.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.3,rounding_size=1.0', fc=fc, ec=ec, lw=lw, ls=ls))
    a2.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=6.8)
def arrow(p, q, text=None, ls='-', col='0.25', at=None, ha='center'):
    a2.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=6, lw=0.7, color=col, ls=ls, shrinkA=0, shrinkB=0))
    if text: a2.text(*at, text, fontsize=6, ha=ha, va='center', color='0.3')
box(0, 18, 17, 14, 'Simulator\n(object poses)', fc='0.95')
box(25, 37, 23, 10, 'Goal check\n(per goal: c / i / u)')
box(57, 37, 26, 10, 'Error injection\n(rate $r$, persistence $s$)', fc='#FFF4E0', ec='#E69F00')
box(57, 18, 26, 10, 'Completion rule\n(record $V_t$)', fc='#E6F4EF', ec='#009E73', lw=1.0)
box(25, 18, 23, 10, 'Executor\n(first goal not in $V_t$)')
box(25, 1, 26, 8, 'Independent evaluator', fc='0.95', ls='--')
arrow((10, 32.6), (24.6, 42))
arrow((48.6, 42), (56.6, 42))
arrow((70, 36.6), (70, 28.6), 'reports $z_g$', at=(71.5, 32.5), ha='left')
arrow((56.6, 23), (48.6, 23), '$V_t$', at=(52.6, 25))
arrow((24.6, 23), (17.6, 23), 'pick,\nplace', at=(21, 27.3))
arrow((10, 17.6), (24.6, 5), ls='--', col='0.5')
a2.text(54, 5, 'used for scoring only;\nnever seen by the executor', fontsize=6, color='0.4', va='center')
fig.savefig(OUT/'figures/fig_setup.pdf'); print('fig_setup.pdf')
