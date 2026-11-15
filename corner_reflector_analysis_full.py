#!/usr/bin/env python3

import os
import argparse
import numpy as np
import matplotlib
import rasterio
from pyproj import Transformer
from scipy.ndimage import map_coordinates

parser = argparse.ArgumentParser(description="Corner reflector analysis from GeoTIFF")

parser.add_argument("input")
parser.add_argument("--lat", type=float)
parser.add_argument("--lon", type=float)
parser.add_argument("--win", type=int, default=100)
parser.add_argument("--win-m", type=float)
parser.add_argument("--out", default="plot.png")
parser.add_argument("-q", "--quiet", action="store_true")
parser.add_argument("--angle", type=float, default=0.0)

args = parser.parse_args()

if args.quiet or not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
else:
    matplotlib.use("Qt5Agg")

import matplotlib.pyplot as plt

# -----------------------------
# LOAD DATA
# -----------------------------
with rasterio.open(args.input) as src:
    data = src.read(1).astype(float)
    transform = src.transform
    crs = src.crs

    data = data**2
    data -= np.min(data)
    if np.max(data) > 0:
        data /= np.max(data)

    if args.lat is not None and args.lon is not None:
        if crs and crs.to_string() != "EPSG:4326":
            transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            x_geo, y_geo = transformer.transform(args.lon, args.lat)
        else:
            x_geo, y_geo = args.lon, args.lat

        y0, x0 = src.index(x_geo, y_geo)
    else:
        y0, x0 = np.unravel_index(np.argmax(data), data.shape)

# -----------------------------
# PIXEL SIZE
# -----------------------------
pixel_size_x = transform.a

if crs and crs.to_string() == "EPSG:4326":
    lat_ref = args.lat if args.lat else 0.0
    pixel_size_x *= 111320 * np.cos(np.deg2rad(lat_ref))

win = int(args.win_m / pixel_size_x) if args.win_m else args.win

# -----------------------------
# WINDOW
# -----------------------------
ymin = max(y0 - win, 0)
ymax = min(y0 + win, data.shape[0])
xmin = max(x0 - win, 0)
xmax = min(x0 + win, data.shape[1])

sub = data[ymin:ymax, xmin:xmax]

# -----------------------------
# PEAK + DISTANCE
# -----------------------------
y_peak_rel, x_peak_rel = np.unravel_index(np.argmax(sub), sub.shape)
x_peak = xmin + x_peak_rel
y_peak = ymin + y_peak_rel

dx_pix = x_peak - x0
dy_pix = y_peak - y0

distance_pix = np.sqrt(dx_pix**2 + dy_pix**2)
distance_cm = distance_pix * pixel_size_x * 100

dx_cm = dx_pix * pixel_size_x * 100
dy_cm = dy_pix * pixel_size_x * 100

x_peak_cm = (x_peak - x0) * pixel_size_x * 100
y_peak_cm = (y_peak - y0) * pixel_size_x * 100

# -----------------------------
# GRID
# -----------------------------
cy, cx = sub.shape[0] // 2, sub.shape[1] // 2

x = (np.arange(sub.shape[1]) - cx) * pixel_size_x * 100
y = (np.arange(sub.shape[0]) - cy) * pixel_size_x * 100
X, Y = np.meshgrid(x, y)

# -----------------------------
# PROFILE LINE
# -----------------------------
angle_rad = np.deg2rad(args.angle)
length = min(sub.shape)

t = np.linspace(-length//2, length//2, length)

x_line = cx + t * np.cos(angle_rad)
y_line = cy + t * np.sin(angle_rad)

x_line_cm = (x_line - cx) * pixel_size_x * 100
y_line_cm = (y_line - cy) * pixel_size_x * 100

# -----------------------------
# DB SCALE
# -----------------------------
sub_db = 10 * np.log10(sub + 1e-12)
sub_db -= np.max(sub_db)
sub_db = np.clip(sub_db, -20, 0)

z_line = map_coordinates(sub_db, [y_line, x_line], order=3)

# -----------------------------
# PROFILE + RESOLUTION
# -----------------------------
profile = map_coordinates(sub, [y_line, x_line], order=1)
profile /= np.max(profile)
profile_db = 10 * np.log10(profile + 1e-12)

x_cm = t * pixel_size_x * 100

threshold_db = -3
indices = np.where(profile_db >= threshold_db)[0]

resolution_cm = None
if len(indices) > 0:
    left_cm = x_cm[indices[0]]
    right_cm = x_cm[indices[-1]]
    resolution_cm = right_cm - left_cm

# -----------------------------
# FIGURE
# -----------------------------
fig = plt.figure(figsize=(18, 18))

ax1 = fig.add_subplot(2, 2, 1, projection='3d')
ax2 = fig.add_subplot(2, 2, 2, projection='3d')

for ax in [ax1, ax2]:

    surf = ax.plot_surface(X, Y, sub_db, cmap='inferno', linewidth=0, shade=False)

    ax.plot(x_line_cm, y_line_cm, z_line, color='cyan', linewidth=3)
    ax.scatter(0, 0, 0, color='lime', s=60)
    ax.scatter(x_peak_cm, y_peak_cm, 0, color='red', s=60)

    ax.set_xlabel("Range (cm)")
    ax.set_ylabel("Azimuth (cm)")
    ax.set_zlabel("Amplitude (dB)")
    ax.set_zlim(-20, 0)

# views
ax1.view_init(elev=30, azim=135)
ax1.set_title("3D View")

ax2.view_init(elev=90, azim=0)
ax2.set_title("Top View")

# -----------------------------
# COLORBAR
# -----------------------------
cax = fig.add_axes([0.9, 0.55, 0.02, 0.3])
fig.colorbar(surf, cax=cax)

# -----------------------------
# PROFILE PLOT
# -----------------------------
ax3 = fig.add_subplot(2, 1, 2)

ax3.plot(x_cm, profile_db, label=f"Angle {args.angle}°")

if resolution_cm is not None:
    left_idx = indices[0]
    right_idx = indices[-1]

    left_cm = x_cm[left_idx]
    right_cm = x_cm[right_idx]

    ax3.plot(left_cm, profile_db[left_idx], 'o')
    ax3.plot(right_cm, profile_db[right_idx], 'o')

    ax3.plot([left_cm, right_cm], [threshold_db, threshold_db], linewidth=3)

    ax3.text(
        (left_cm + right_cm)/2,
        threshold_db + 1,
        f"{resolution_cm:.1f} cm",
        ha='center',
        fontsize=12,
        fontweight='bold'
    )

ax3.axhline(threshold_db, linestyle='--', label='-3 dB')
ax3.set_title("Resolution Profile (dB)")
ax3.set_xlabel("Distance (cm)")
ax3.set_ylabel("Amplitude (dB)")
ax3.set_ylim(-20, 1)
ax3.grid(True)
ax3.legend()

# -----------------------------
# INFO BOX
# -----------------------------
height, width = data.shape
center_y, center_x = height // 2, width // 2
center_lon, center_lat = src.xy(center_y, center_x)

dist_text = (
    f"Distance from center: {distance_cm:.1f} cm"
    if args.lat is None else
    f"Distance from given coord: {distance_cm:.1f} cm"
)

info_text = (
    f"GeoTIFF Info\n"
    f"----------------------\n"
    f"Size: {width} x {height} px\n"
    f"Pixel size: {pixel_size_x*100:.3f} cm\n"
    f"Center: ({center_lon:.6f}, {center_lat:.6f})\n\n"
    f"{dist_text}\n"
    f"dx={dx_cm:.1f} cm, dy={dy_cm:.1f} cm\n"
)

if resolution_cm is not None:
    info_text += f"Resolution (-3 dB): {resolution_cm:.1f} cm\n"

fig.text(
    0.7, 0.3,
    info_text,
    fontsize=10,
    bbox=dict(facecolor='white', alpha=0.85)
)

# -----------------------------
# SAVE
# -----------------------------
plt.tight_layout()
plt.savefig(args.out, dpi=300, bbox_inches='tight')

if not args.quiet:
    plt.show()