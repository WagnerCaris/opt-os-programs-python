#!/usr/bin/env python3

import subprocess
import sys
from pathlib import Path


def comprimir_video(entrada):
    entrada = Path(entrada)

    if not entrada.exists():
        print(f"ERRO: arquivo não encontrado: {entrada}")
        sys.exit(1)

    saida = entrada.with_name(
        entrada.stem + "_chatgpt.mp4"
    )

    comando = [
        "ffmpeg",
        "-i", str(entrada),

        # Reduz para no máximo 1920x1080 mantendo proporção
        "-vf",
        "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",

        # Para tutorial de tela, 15 FPS normalmente é suficiente
        "-r", "15",

        # Codec de vídeo amplamente compatível
        "-c:v", "libx264",

        # Qualidade / compressão
        # menor CRF = mais qualidade e arquivo maior
        "-crf", "24",

        # Compressão mais eficiente
        "-preset", "slow",

        # Compatibilidade
        "-pix_fmt", "yuv420p",

        # Áudio
        "-c:a", "aac",
        "-b:a", "96k",
        "-ac", "1",

        # Facilita streaming/leitura do MP4
        "-movflags", "+faststart",

        "-y",
        str(saida)
    ]

    print()
    print("========================================")
    print(" Compressão para análise no ChatGPT")
    print("========================================")
    print(f"Entrada : {entrada}")
    print(f"Saída   : {saida}")
    print()
    print("Configuração:")
    print("  Resolução máxima : 1920x1080")
    print("  FPS               : 15")
    print("  Vídeo             : H.264")
    print("  CRF               : 24")
    print("  Áudio             : AAC 96 kbps mono")
    print()

    subprocess.run(comando, check=True)

    tamanho_original = entrada.stat().st_size
    tamanho_final = saida.stat().st_size

    original_gb = tamanho_original / (1024 ** 3)
    final_mb = tamanho_final / (1024 ** 2)

    reducao = (1 - tamanho_final / tamanho_original) * 100

    print()
    print("========================================")
    print(" Resultado")
    print("========================================")
    print(f"Original : {original_gb:.2f} GB")
    print(f"Final    : {final_mb:.1f} MB")
    print(f"Redução  : {reducao:.1f}%")
    print()
    print(f"Arquivo criado:")
    print(saida)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print()
        print("Uso:")
        print(f"  python3 {Path(sys.argv[0]).name} VIDEO.mov")
        print()
        print("Exemplo:")
        print(
            f'  python3 {Path(sys.argv[0]).name} '
            '"tutorial_radar.mov"'
        )
        sys.exit(1)

    comprimir_video(sys.argv[1])