#!/usr/bin/python3.11
import rasterio
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
import sys
import textwrap

matplotlib.use('Qt5Agg')

if len(sys.argv) < 2:
    print("Usage: python showtif_with_metadata_autoscale.py <file.tif>")
    sys.exit(1)

name = sys.argv[1]
print(f"📂 Opening: {name}")

# --- Open GeoTIFF with Rasterio ---
with rasterio.open(name) as dataset:
    b1 = dataset.read(1)

    # Handle complex data
    if np.iscomplexobj(b1):
        print("⚙️ Complex data detected — displaying absolute magnitude.")
        b1 = np.abs(b1)

    # Mask invalid values
    mask_condition = (b1 == -9999) | np.isnan(b1) | np.isinf(b1)
    if mask_condition.any():
        print("⚠️ Found -9999, NaN, or Inf values — masking them for display.")
        b1 = np.ma.masked_where(mask_condition, b1)

    # Metadata text
    info_lines = [
        f"File: {name}",
        f"Driver: {dataset.driver}",
        f"Size: {dataset.width} x {dataset.height}",
        f"Bands: {dataset.count}",
        f"CRS: {dataset.crs}",
        f"Transform: {dataset.transform}",
        f"Data Type: {dataset.dtypes[0]}",
        f"Bounds: {dataset.bounds}",
    ]

    tags = dataset.tags()
    if tags:
        info_lines.append("Tags:")
        for k, v in tags.items():
            wrapped = textwrap.fill(f"{k}: {v}", width=100, subsequent_indent=" " * 8)
            info_lines.append("    " + wrapped)

# Compute valid data range
if np.ma.is_masked(b1):
    finite_vals = b1.compressed()
else:
    finite_vals = b1[np.isfinite(b1)]

if finite_vals.size == 0:
    vmin, vmax = -1, 1
    print("⚠️ No valid pixels — using default range [-1, 1].")
else:
    vmin, vmax = np.min(finite_vals), np.max(finite_vals)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        print("⚠️ Invalid/constant values — fallback range [-1, 1].")
        vmin, vmax = -1, 1

print(f"📈 Auto range: vmin={vmin:.6g}, vmax={vmax:.6g}")

# Colormap selection
if vmin < 0 and vmax > 0:
    cmap = plt.cm.RdBu_r
else:
    cmap = plt.cm.gray

# Make masked pixels transparent
cmap.set_bad(color=(0, 0, 0, 0))

# Layout
fig, (ax_img, ax_info) = plt.subplots(
    2, 1, figsize=(12, 16),
    gridspec_kw={'height_ratios': [3, 1]}
)
fig.suptitle("GeoTIFF Viewer with Metadata", fontsize=14, fontweight='bold')

# Show image
im = ax_img.imshow(b1, vmin=vmin, vmax=vmax, cmap=cmap)
ax_img.set_title(f"Image (Band 1) — Range: {vmin:.3g} to {vmax:.3g}", fontsize=12)
ax_img.axis('off')

# Colorbar
plt.colorbar(im, ax=ax_img, fraction=0.046, pad=0.04, label="Pixel Value")

# Metadata panel
ax_info.axis('off')
ax_info.text(
    0, 1, "\n".join(info_lines),
    va='top', ha='left', family='monospace', fontsize=9
)

# -------------------------------------------------------------------------
# --- BEGIN INTERACTIVE VMOD SECTION ---
# -------------------------------------------------------------------------

vmax_current = vmax  # mutable copy for key control
vmin_current = vmin
shift_step = (vmax - vmin) * 0.05  # 5% of original range





def on_key(event):
    """Keyboard handler for interactive scaling and brightness shift."""
    global vmax_current, vmin_current

    # Determine step multipliers
    if event.key.startswith('shift+'):
        scale_factor = 1.3      # 30% change (big)
        shift_mult = 3.0        # 3x brightness shift
        key = event.key[6:]     # remove 'shift+'
    elif event.key.startswith('meta+'):
        scale_factor = 1.03     # 3% change (small)
        shift_mult = 0.3        # slower brightness shift
        key = event.key[5:]     # remove 'ctrl+'
    else:
        scale_factor = 1.1      # default 10% scale
        shift_mult = 1.0        # normal shift
        key = event.key

    # Compute brightness shift base step
    shift_step_local = shift_step * shift_mult

    # ↑ Increase contrast
    if key == 'up':
        vmax_current *= scale_factor

    # ↓ Decrease contrast
    elif key == 'down':
        vmax_current /= scale_factor

    # → Brighten (shift window up)
    elif key == 'right':
        vmin_current += shift_step_local
        vmax_current += shift_step_local

    # ← Darken (shift window down)
    elif key == 'left':
        vmin_current -= shift_step_local
        vmax_current -= shift_step_local

    # r = reset
    elif key == 'r':
        vmin_current = vmin
        vmax_current = vmax

    else:
        return

    # Avoid inversion (vmax below vmin)
    if vmax_current <= vmin_current:
        vmax_current = vmin_current + 1e-12

    # Apply updated scaling
    im.set_clim(vmin_current, vmax_current)

    # Update title
    ax_img.set_title(
        f"Image (Band 1) — Range: {vmin_current:.3g} to {vmax_current:.3g}",
        fontsize=12
    )

    fig.canvas.draw_idle()

    print(f"🔧 [{event.key}] vmin={vmin_current:.6g}, vmax={vmax_current:.6g}")


fig.canvas.mpl_connect('key_press_event', on_key)

# -------------------------------------------------------------------------
# --- END INTERACTIVE VMOD SECTION ---
# -------------------------------------------------------------------------

plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.show()
