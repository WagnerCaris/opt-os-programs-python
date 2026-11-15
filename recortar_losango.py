#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask


def escolher_nodata(dtype: np.dtype, nodata_original):
    """
    Define um valor NoData adequado.

    Para rasters float, usa NaN quando não existe NoData original.
    Para rasters inteiros, usa o NoData original ou zero.
    """
    if nodata_original is not None:
        return nodata_original

    if np.issubdtype(dtype, np.floating):
        return np.nan

    return 0


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Mantém uma região em formato de losango no centro do raster "
            "e remove os pixels externos usando NoData."
        )
    )

    parser.add_argument(
        "entrada",
        help="GeoTIFF de entrada"
    )

    parser.add_argument(
        "saida",
        help="GeoTIFF de saída"
    )

    args = parser.parse_args()

    entrada = Path(args.entrada)
    saida = Path(args.saida)

    if not entrada.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {entrada}")

    if entrada.resolve() == saida.resolve():
        raise ValueError("O arquivo de saída deve ser diferente do arquivo de entrada.")

    with rasterio.open(entrada) as src:
        dados = src.read()
        perfil = src.profile.copy()

        largura = src.width
        altura = src.height
        transform = src.transform

        # Vértices do losango em coordenadas de pixel:
        #
        #             topo
        #              /\
        #             /  \
        # esquerda   <    >   direita
        #             \  /
        #              \/
        #             base
        #
        pontos_pixel = [
            (largura / 2.0, 0.0),          # meio da borda superior
            (largura, altura / 2.0),        # meio da borda direita
            (largura / 2.0, altura),        # meio da borda inferior
            (0.0, altura / 2.0),            # meio da borda esquerda
        ]

        # Converte coordenadas de pixel para coordenadas geográficas/projetadas.
        pontos_mundo = [
            transform * (coluna, linha)
            for coluna, linha in pontos_pixel
        ]

        poligono = {
            "type": "Polygon",
            "coordinates": [[
                pontos_mundo[0],
                pontos_mundo[1],
                pontos_mundo[2],
                pontos_mundo[3],
                pontos_mundo[0],
            ]]
        }

        # True dentro do losango; False fora.
        mascara_interna = geometry_mask(
            [poligono],
            out_shape=(altura, largura),
            transform=transform,
            invert=True,
            all_touched=False,
        )

        dtype = np.dtype(dados.dtype)
        nodata = escolher_nodata(dtype, src.nodata)

        # Aplica a máscara a todas as bandas.
        dados[:, ~mascara_interna] = nodata

        perfil.update(
            nodata=nodata,
            compress="deflate",
            tiled=True,
            BIGTIFF="IF_SAFER",
        )

        saida.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(saida, "w", **perfil) as dst:
            dst.write(dados)

            # Máscara interna adicional para programas que interpretam
            # corretamente a máscara do GeoTIFF.
            dst.write_mask(
                np.where(mascara_interna, 255, 0).astype(np.uint8)
            )

    print(f"Entrada : {entrada}")
    print(f"Saída   : {saida}")
    print(f"Dimensão: {largura} x {altura} pixels")
    print(f"NoData  : {nodata}")
    print("Recorte em losango concluído.")


if __name__ == "__main__":
    main()
    