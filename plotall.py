# plotall.py
import os
import argparse
import numpy as np
from scipy.io import readsav
import matplotlib  # set backend before importing pyplot

# Choose backend depending on display
if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
else:
    matplotlib.use("Qt5Agg")  # case-sensitive backend name

import matplotlib.pyplot as plt

# Try to import mplcursors (optional)
try:
    import mplcursors
    HAVE_MPLCURSORS = True
except Exception:
    HAVE_MPLCURSORS = False


def to_string(val):
    try:
        if isinstance(val, (bytes, bytearray)):
            return val.decode("utf-8", "ignore").strip()
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, (np.ndarray, list, tuple)):
            flat = np.ravel(val)
            if flat.size == 1:
                return to_string(flat[0])
            return "".join(to_string(v) for v in flat).strip()
        return str(val).strip()
    except Exception:
        return "unknown"


parser = argparse.ArgumentParser(
    description="Plot structured variables from IDL/GDL .sav files",
    epilog=(
        "Example of sav file contents:\n"
        "  corist={x:inc(s), y:corist(s), xt:'inc', yt:'ref', label:'corist'}"
    ),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("sav_file", help="Path to the .sav file")
parser.add_argument(
    "--title",
    default="Plotagem de estruturas IDL/GDL",
    help="Plot title (default: %(default)s)",
)
parser.add_argument(
    "-q", "--quiet",
    action="store_true",
    help="Do not display plot (useful for batch processing)"
)
parser.add_argument("--out", default="plot.png", help="Output image file")
parser.add_argument(
    "--scale",
    type=float,
    default=None,
    help="Y-axis scale: sets range to [scale, 0]"
)
args = parser.parse_args()

data = readsav(args.sav_file, verbose=False)

plt.figure(figsize=(12, 7))
found = False
for key, val in data.items():

    # -----------------------------
    # CASE: array of structures (recarray or structured array)
    # -----------------------------
    if hasattr(val, "dtype") and val.dtype.names is not None:

        field_names = [name.lower() for name in val.dtype.names]

        if all(name in field_names for name in ("x", "y", "xt", "yt", "label")):

            for i in range(len(val)):
                elem = val[i]

                try:
                    x = np.array(elem["x"])
                    y = np.array(elem["y"])

                    label = to_string(elem["label"]).capitalize()
                    xlabel = elem["xt"].decode("utf-8") if isinstance(elem["xt"], bytes) else str(elem["xt"])
                    ylabel = elem["yt"].decode("utf-8") if isinstance(elem["yt"], bytes) else str(elem["yt"])
                    print(type(elem["xt"]), elem["xt"])
                    print(type(elem["yt"]), elem["yt"])

                    print("Plotting:", label)  # debug


                    line, = plt.plot(x, y, label=label)

                    idx = np.argmin(y)
                    xmin = x[idx]
                    ymin = y[idx]

                    # marker
                    plt.plot(xmin, ymin, 'o', color=line.get_color(), markersize=6)

                    # dynamic offset
                    offset = 0.05 * (np.max(y) - np.min(y))
 
                    color = line.get_color()
                    # label
                    plt.text(xmin, ymin + offset, f"{label}\n{ymin:.2f}", ha='center', va='bottom',         fontsize=12,color=color)

                    plt.xlabel(xlabel)
                    plt.ylabel(ylabel)
                    found = True
                    plt.title(args.title)
                    plt.legend()
                    if args.scale is not None:
                        plt.ylim(args.scale, 0)
                    plt.savefig(args.out, dpi=300, bbox_inches='tight')

                except Exception as e:
                    print(f"Erro ao processar '{key}[{i}]': {e}")

if found:
    if args.scale is not None:
        plt.ylim(args.scale, 0)
    if HAVE_MPLCURSORS:
        mplcursors.cursor(hover=True)
    plt.tight_layout()
    if not args.quiet:
        plt.show(block=False)
        plt.pause(0.1)
else:
    print("Nenhuma estrutura compatível encontrada no arquivo .sav.")
