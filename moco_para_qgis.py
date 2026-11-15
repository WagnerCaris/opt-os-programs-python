#!/usr/bin/env python3
"""Gera uma trajetória GeoJSON leve a partir de um MOCO textual.

Uso:
    python3 moco_para_qgis.py arquivo.moco
    python3 moco_para_qgis.py arquivo.moco -o voo.geojson --distancia 10

Somente biblioteca padrão do Python. Coordenadas de entrada: GPST (s),
latitude e longitude em graus, nessa ordem; saída assume WGS 84.
A distância é uma amostragem espacial para visualização, não uma garantia
de erro geométrico máximo. Os dados completos permanecem no original.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile


def distancia_m(a, b):
    """Distância esférica entre pares (longitude, latitude)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, h)))


def positivo(valor):
    numero = float(valor)
    if not math.isfinite(numero) or numero <= 0:
        raise argparse.ArgumentTypeError("informe um número finito maior que zero")
    return numero


def converter(entrada, saida, distancia=5.0, lacuna=5.0):
    if entrada.resolve() == saida.resolve():
        raise ValueError("a saída precisa ser diferente da entrada")
    if saida.exists():
        raise ValueError(f"a saída já existe: {saida}; escolha outro nome com -o")

    total = vertices = trechos = 0
    inicio = fim = anterior_t = None
    ultimo = mantido = None
    quantidade = 0
    inicio_trecho = None
    temporario = None

    try:
        with entrada.open(encoding="utf-8-sig") as fonte, tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=saida.parent,
            prefix=f".{saida.name}.", suffix=".tmp", delete=False,
        ) as destino:
            temporario = Path(destino.name)
            destino.write('{"type":"FeatureCollection","features":[')

            def escrever_ponto(ponto):
                nonlocal vertices, quantidade, mantido
                if quantidade:
                    destino.write(",")
                destino.write(json.dumps(
                    [round(ponto[0], 7), round(ponto[1], 7)],
                    separators=(",", ":"), allow_nan=False,
                ))
                quantidade += 1
                vertices += 1
                mantido = ponto

            def fechar_trecho():
                # LineString exige pelo menos dois vértices, mesmo se parado.
                if ultimo != mantido or quantidade == 1:
                    escrever_ponto(ultimo)
                propriedades = {
                    "origem": entrada.name,
                    "trecho": trechos,
                    "gpst_inicio_s": inicio_trecho,
                    "gpst_fim_s": anterior_t,
                    "distancia_amostragem_m": distancia,
                }
                destino.write(']},"properties":')
                destino.write(json.dumps(propriedades, ensure_ascii=False,
                                         separators=(",", ":")))
                destino.write("}")

            for numero_linha, linha in enumerate(fonte, 1):
                linha = linha.strip()
                if not linha or linha.startswith(("%", "#")):
                    continue
                # Aceita tanto tabulações reais como a sequência literal \\t.
                campos = linha.replace("\\t", " ").split(maxsplit=3)
                try:
                    t, lat, lon = map(float, campos[:3])
                    if not all(math.isfinite(v) for v in (t, lat, lon)):
                        raise ValueError("valor não finito")
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError("coordenada fora do intervalo")
                except ValueError as erro:
                    raise ValueError(f"linha {numero_linha}: posição inválida ({erro})") from erro

                ponto = (lon, lat)
                novo_trecho = anterior_t is None or t < anterior_t or t - anterior_t > lacuna
                if novo_trecho:
                    if quantidade:
                        fechar_trecho()
                        destino.write(",")
                    trechos += 1
                    quantidade = 0
                    inicio_trecho = t
                    destino.write('{"type":"Feature","geometry":{"type":"LineString","coordinates":[')
                    escrever_ponto(ponto)
                elif distancia_m(mantido, ponto) >= distancia:
                    escrever_ponto(ponto)

                if inicio is None:
                    inicio = t
                fim = anterior_t = t
                ultimo = ponto
                total += 1

            if total == 0:
                raise ValueError("nenhuma posição encontrada no arquivo")
            fechar_trecho()
            destino.write("]}\n")

        # Publica somente após a conversão completa, sem sobrescrever arquivos.
        os.link(temporario, saida)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)

    original_bytes = entrada.stat().st_size
    saida_bytes = saida.stat().st_size
    print(f"Entrada: {entrada} ({original_bytes / 1024**2:.2f} MiB)")
    print(f"Saída:   {saida} ({saida_bytes / 1024**2:.3f} MiB)")
    print(f"Posições lidas: {total:,}; vértices: {vertices:,}; trechos: {trechos}")
    print(f"GPST inicial/final (s): {inicio:.6f} / {fim:.6f}")
    print(f"Redução de tamanho: {100 * (1 - saida_bytes / original_bytes):.3f}%")
    print("QGIS: arraste o GeoJSON para o mapa (longitude/latitude, WGS 84).")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entrada", type=Path, help="arquivo MOCO textual")
    parser.add_argument("-o", "--saida", type=Path, help="GeoJSON de saída")
    parser.add_argument("--distancia", type=positivo, default=5.0,
                        help="distância mínima entre vértices em metros (padrão: 5)")
    parser.add_argument("--lacuna", type=positivo, default=5.0,
                        help="separa trechos quando faltam dados por mais de N segundos (padrão: 5)")
    args = parser.parse_args()
    saida = args.saida or args.entrada.with_name(args.entrada.stem + "_trajetoria.geojson")
    try:
        converter(args.entrada, saida, args.distancia, args.lacuna)
    except (OSError, ValueError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
