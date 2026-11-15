import plotly.graph_objects as go
import rasterio
import numpy as np
import panel as pn
import sys
from scipy.ndimage import gaussian_filter

name1=sys.argv[1]

with rasterio.open(name1) as src:
	elev=src.read(1)


#name2="carajas_COP30_nogeoid.tif"
#with rasterio.open(name2) as src:
	#image=src.read(1)

image=elev
image=np.nan_to_num(image)
image2=image/np.max(image)

#elev2=gaussian_filter(elev,1)
elev2=elev


surface = go.Surface(z=elev2,surfacecolor=image2)
layout = go.Layout(autosize=False,width=2000,height=2000)
fig = dict(data=[surface], layout=layout)

plotly_pane = pn.pane.Plotly(fig)
plotly_pane.show()
