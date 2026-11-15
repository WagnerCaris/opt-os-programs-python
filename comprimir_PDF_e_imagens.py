#!/usr/bin/env python3

import shutil
import subprocess
import sys
from pathlib import Path


EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def tamanho_mb(arquivo):
    return arquivo.stat().st_size / (1024 * 1024)


def comprimir_imagem(entrada, saida):
    try:
        from PIL import Image
    except ImportError:
        print("ERRO: Pillow não está instalado.")
        print("Instale com:")
        print("  python3 -m pip install Pillow")
        sys.exit(1)

    extensao = entrada.suffix.lower()

    with Image.open(entrada) as img:
        if extensao in {".jpg", ".jpeg"}:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            img.save(
                saida,
                format="JPEG",
                quality=85,
                optimize=True,
                progressive=True,
            )

        elif extensao == ".png":
            img.save(
                saida,
                format="PNG",
                optimize=True,
                compress_level=9,
            )

        elif extensao == ".webp":
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            img.save(
                saida,
                format="WEBP",
                quality=85,
                method=6,
            )

        elif extensao == ".bmp":
            # BMP praticamente não comprime.
            # A saída é convertida automaticamente para PNG.
            img.save(
                saida,
                format="PNG",
                optimize=True,
                compress_level=9,
            )


def comprimir_pdf(entrada, saida):
    gs = shutil.which("gs")

    if gs is None:
        print("ERRO: Ghostscript não está instalado.")
        print("Instale com:")
        print("  sudo apt install ghostscript")
        sys.exit(1)

    comando = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.6",
        "-dPDFSETTINGS=/ebook",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        f"-sOutputFile={saida}",
        str(entrada),
    ]

    subprocess.run(comando, check=True)


def main():
    if len(sys.argv) != 2:
        print()
        print("Uso:")
        print(f"  python3 {Path(sys.argv[0]).name} ARQUIVO")
        print()
        print("Exemplos:")
        print(f"  python3 {Path(sys.argv[0]).name} foto.jpg")
        print(f"  python3 {Path(sys.argv[0]).name} documento.pdf")
        print()
        sys.exit(1)

    entrada = Path(sys.argv[1]).expanduser()

    if not entrada.is_file():
        print(f"ERRO: arquivo não encontrado: {entrada}")
        sys.exit(1)

    extensao = entrada.suffix.lower()

    if extensao == ".bmp":
        saida = entrada.with_name(
            entrada.stem + "_comprimido.png"
        )
    else:
        saida = entrada.with_name(
            entrada.stem + "_comprimido" + entrada.suffix.lower()
        )

    if saida.exists():
        print(f"ERRO: o arquivo de saída já existe:")
        print(saida)
        print("Remova ou renomeie esse arquivo antes de executar novamente.")
        sys.exit(1)

    print()
    print("========================================")
    print(" Compressão de arquivo")
    print("========================================")
    print(f"Entrada : {entrada}")
    print(f"Saída   : {saida}")
    print()

    try:
        if extensao in EXTENSOES_IMAGEM:
            comprimir_imagem(entrada, saida)

        elif extensao == ".pdf":
            comprimir_pdf(entrada, saida)

        else:
            print(f"ERRO: formato não suportado: {extensao}")
            print("Formatos: JPG, JPEG, PNG, WEBP, BMP e PDF")
            sys.exit(1)

    except Exception as erro:
        if saida.exists():
            saida.unlink()

        print(f"ERRO durante a compressão: {erro}")
        sys.exit(1)

    original = tamanho_mb(entrada)
    final = tamanho_mb(saida)

    if original > 0:
        reducao = (1 - final / original) * 100
    else:
        reducao = 0

    print("========================================")
    print(" Resultado")
    print("========================================")
    print(f"Original : {original:.2f} MB")
    print(f"Final    : {final:.2f} MB")
    print(f"Redução  : {reducao:.1f}%")
    print()
    print(f"Arquivo criado:")
    print(saida)


if __name__ == "__main__":
    main()
