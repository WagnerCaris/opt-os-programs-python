from PIL import Image
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import glob

import os

# find base files like azspek_lhh.png

files = glob.glob("azspek_???.png")

for f in files:

    base = os.path.basename(f)

    # extract the ??? part

    tag = base.replace("azspek_", "").replace(".png", "")

    a_file = f"azspek_{tag}_abs.png"

    b_file = f"azspek_{tag}.png"

    c_file = f"azspek_{tag}_rk.png"

    # check if all exist

    if not all(map(os.path.exists, [a_file, b_file, c_file])):

        continue

    # load images

    a = Image.open(a_file).convert('RGBA')

    b = Image.open(b_file).convert('RGBA')

    c = Image.open(c_file).convert('RGBA')

    # same height

    h = max(a.height, b.height, c.height)

    def pad(img):

        new = Image.new('RGBA', (img.width, h), (0,0,0,0))

        new.paste(img, (0,0))

        return new

    a, b, c = map(pad, [a, b, c])

    # combine

    result = Image.new('RGBA', (a.width + b.width + c.width, h))

    result.paste(a, (0,0))

    result.paste(b, (a.width,0))

    result.paste(c, (a.width + b.width,0))

    # output name with tag

    outname = f"azspek_{tag}_combined.png"

    result.save(outname)

    print("Saved:", outname)