#!/usr/bin/env python3
"""
reamostrar_rinex_zip.py

Decima um arquivo RINEX de observacao sem interpolar nem fazer media:
mantem apenas epocas originais no intervalo solicitado e gera um ZIP.

Suporta:
- RINEX 2.x e RINEX 3.x
- entrada RINEX simples ou .zip contendo um RINEX de observacao
- atualizacao de INTERVAL, TIME OF FIRST OBS e TIME OF LAST OBS
- eventos RINEX (flags diferentes de 0/1) sao preservados
- modo --auto-fit para aumentar o intervalo ate o ZIP caber no limite

Exemplos:
  python3 reamostrar_rinex_zip.py 4905321225M.26O.zip
  python3 reamostrar_rinex_zip.py 4905321225M.26O.zip --interval 1
  python3 reamostrar_rinex_zip.py 4905321225M.26O.zip --interval 2
  python3 reamostrar_rinex_zip.py 4905321225M.26O.zip --interval 1 --max-mb 25 --auto-fit
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional, TextIO, Tuple

EpochInfo = Tuple[dt.datetime, int]

OBS_RE = re.compile(r"(?i)(\.obs|\.rnx|\.\d{2}o)$")


def parse_rinex2_epoch(line: str) -> Optional[EpochInfo]:
    """Retorna (data_hora, flag) se a linha for uma epoca RINEX 2."""
    if len(line) < 32:
        return None

    try:
        yy = int(line[0:3])
        month = int(line[3:6])
        day = int(line[6:9])
        hour = int(line[9:12])
        minute = int(line[12:15])
        sec = float(line[15:26])
        flag = int(line[28:29])
        nrec = int(line[29:32])
    except ValueError:
        return None

    if not (
        0 <= yy <= 99
        and 1 <= month <= 12
        and 1 <= day <= 31
        and 0 <= hour <= 23
        and 0 <= minute <= 59
        and 0.0 <= sec < 61.0
        and 0 <= flag <= 6
        and 0 <= nrec <= 99
    ):
        return None

    year = 1900 + yy if yy >= 80 else 2000 + yy
    sec_int = int(math.floor(sec))
    usec = int(round((sec - sec_int) * 1_000_000))

    if usec >= 1_000_000:
        sec_int += 1
        usec -= 1_000_000

    try:
        timestamp = dt.datetime(
            year, month, day, hour, minute, sec_int, usec
        )
    except ValueError:
        return None

    return timestamp, flag


def parse_rinex3_epoch(line: str) -> Optional[EpochInfo]:
    """Retorna (data_hora, flag) se a linha for uma epoca RINEX 3."""
    if not line.startswith(">"):
        return None

    parts = line[1:].split()
    if len(parts) < 8:
        return None

    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        hour = int(parts[3])
        minute = int(parts[4])
        sec = float(parts[5])
        flag = int(parts[6])
    except ValueError:
        return None

    sec_int = int(math.floor(sec))
    usec = int(round((sec - sec_int) * 1_000_000))

    if usec >= 1_000_000:
        sec_int += 1
        usec -= 1_000_000

    try:
        timestamp = dt.datetime(
            year, month, day, hour, minute, sec_int, usec
        )
    except ValueError:
        return None

    return timestamp, flag


def open_rinex_text(path: Path):
    """
    Abre RINEX simples ou ZIP.
    Retorna (stream_texto, nome_interno, objeto_zip_ou_None).
    """
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path, "r")
        candidates = [
            name
            for name in zf.namelist()
            if not name.endswith("/") and OBS_RE.search(Path(name).name)
        ]

        if len(candidates) != 1:
            zf.close()
            raise RuntimeError(
                "O ZIP deve conter exatamente um RINEX de observacao "
                f"(.obs, .rnx ou .??O). Encontrados: {candidates}"
            )

        name = candidates[0]
        raw = zf.open(name, "r")
        text = io.TextIOWrapper(
            raw, encoding="ascii", errors="strict", newline=None
        )
        return text, Path(name).name, zf

    if not OBS_RE.search(path.name):
        raise RuntimeError(
            "A entrada nao parece ser um RINEX de observacao "
            "(.obs, .rnx ou .??O)."
        )

    text = path.open("r", encoding="ascii", errors="strict", newline=None)
    return text, path.name, None


def read_header(stream: TextIO):
    header = []

    while True:
        line = stream.readline()
        if line == "":
            raise RuntimeError("Fim de arquivo antes de END OF HEADER.")

        line = line.rstrip("\r\n")
        header.append(line)

        if "END OF HEADER" in line:
            break

    try:
        version = float(header[0][:9])
    except ValueError as exc:
        raise RuntimeError("Nao foi possivel identificar a versao RINEX.") from exc

    input_interval = None
    for line in header:
        if len(line) >= 68 and line[60:68] == "INTERVAL":
            try:
                input_interval = float(line[:10])
            except ValueError:
                pass

    return header, version, input_interval


def format_header_time(original: str, timestamp: dt.datetime) -> str:
    sec = timestamp.second + timestamp.microsecond / 1_000_000.0

    prefix = (
        f"{timestamp.year:6d}"
        f"{timestamp.month:6d}"
        f"{timestamp.day:6d}"
        f"{timestamp.hour:6d}"
        f"{timestamp.minute:6d}"
        f"{sec:13.7f}"
    )

    # Os campos de tempo ocupam as colunas 1-43.
    # Preserva sistema de tempo e rotulo do cabecalho original.
    tail = original[43:] if len(original) > 43 else ""
    return prefix + tail


def update_header(
    header,
    interval: float,
    first_obs: Optional[dt.datetime],
    last_obs: Optional[dt.datetime],
):
    result = []

    for line in header:
        label = line[60:80] if len(line) >= 60 else ""

        if "INTERVAL" in label:
            line = f"{interval:10.3f}" + line[10:]

        elif "TIME OF FIRST OBS" in label and first_obs is not None:
            line = format_header_time(line, first_obs)

        elif "TIME OF LAST OBS" in label and last_obs is not None:
            line = format_header_time(line, last_obs)

        result.append(line)

    return result


def interval_tag(seconds: float) -> str:
    if abs(seconds - round(seconds)) < 1e-9:
        return f"{int(round(seconds))}s"
    return f"{seconds:g}s".replace(".", "p")


def default_output_path(input_path: Path, rinex_name: str, interval: float) -> Path:
    p = Path(rinex_name)
    return input_path.parent / f"{p.stem}_{interval_tag(interval)}.zip"


def output_rinex_name(rinex_name: str, interval: float) -> str:
    p = Path(rinex_name)
    return f"{p.stem}_{interval_tag(interval)}{p.suffix}"


def write_block(temp, block):
    for line in block:
        temp.write((line + "\n").encode("ascii"))


def decimate_once(
    input_path: Path,
    interval: float,
    output_path: Optional[Path],
    compresslevel: int,
    force: bool,
):
    if interval <= 0:
        raise ValueError("O intervalo deve ser maior que zero.")

    stream, rinex_name, zf = open_rinex_text(input_path)

    temp_name = None

    try:
        header, version, input_interval = read_header(stream)
        detector: Callable[[str], Optional[EpochInfo]]
        detector = parse_rinex3_epoch if version >= 3.0 else parse_rinex2_epoch

        if output_path is None:
            output_path = default_output_path(input_path, rinex_name, interval)

        if output_path.exists() and not force:
            raise FileExistsError(
                f"Arquivo de saida ja existe: {output_path}\n"
                "Use --force para sobrescrever."
            )

        first_kept = None
        last_kept = None
        first_observation = None
        next_due = None

        total_obs_epochs = 0
        kept_obs_epochs = 0
        kept_events = 0

        # Tolerancia apenas para erros numericos pequenos do timestamp.
        tolerance = 1e-4

        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix="rinex_decim_", suffix=".tmp", delete=False
        ) as temp:
            temp_name = temp.name

            current_block = []
            current_info = None
            prelude = []

            def flush_current():
                nonlocal first_kept
                nonlocal last_kept
                nonlocal first_observation
                nonlocal next_due
                nonlocal total_obs_epochs
                nonlocal kept_obs_epochs
                nonlocal kept_events

                if not current_block or current_info is None:
                    return

                timestamp, flag = current_info

                # Flags 0 e 1 representam epocas de observacao.
                if flag in (0, 1):
                    total_obs_epochs += 1

                    if first_observation is None:
                        first_observation = timestamp
                        next_due = timestamp

                    keep = False

                    if timestamp + dt.timedelta(seconds=tolerance) >= next_due:
                        keep = True

                        # Avanca a grade temporal ate ficar depois da epoca atual.
                        while (
                            next_due
                            <= timestamp + dt.timedelta(seconds=tolerance)
                        ):
                            next_due += dt.timedelta(seconds=interval)

                    if keep:
                        write_block(temp, current_block)
                        kept_obs_epochs += 1

                        if first_kept is None:
                            first_kept = timestamp
                        last_kept = timestamp

                else:
                    # Preserva eventos/metadados RINEX especiais.
                    write_block(temp, current_block)
                    kept_events += 1

            for raw_line in stream:
                line = raw_line.rstrip("\r\n")
                info = detector(line)

                if info is not None:
                    if current_block:
                        flush_current()
                    elif prelude:
                        write_block(temp, prelude)
                        prelude.clear()

                    current_block = [line]
                    current_info = info
                else:
                    if current_block:
                        current_block.append(line)
                    else:
                        prelude.append(line)

            if current_block:
                flush_current()
            elif prelude:
                write_block(temp, prelude)

        if kept_obs_epochs == 0:
            raise RuntimeError(
                "Nenhuma epoca de observacao foi mantida. "
                "Verifique o arquivo e o intervalo solicitado."
            )

        new_header = update_header(header, interval, first_kept, last_kept)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            output_path.unlink()

        inner_name = output_rinex_name(rinex_name, interval)

        with zipfile.ZipFile(
            output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=compresslevel,
            allowZip64=True,
        ) as zout:
            with zout.open(inner_name, "w", force_zip64=True) as out:
                for line in new_header:
                    out.write((line + "\n").encode("ascii"))

                with open(temp_name, "rb") as temp:
                    shutil.copyfileobj(temp, out, length=1024 * 1024)

        result = {
            "version": version,
            "input_interval": input_interval,
            "interval": interval,
            "total_epochs": total_obs_epochs,
            "kept_epochs": kept_obs_epochs,
            "events": kept_events,
            "first": first_kept,
            "last": last_kept,
            "output": output_path,
            "inner_name": inner_name,
            "size_bytes": output_path.stat().st_size,
        }

        return result

    finally:
        try:
            stream.close()
        except Exception:
            pass

        if zf is not None:
            try:
                zf.close()
            except Exception:
                pass

        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def print_result(result, max_mb: Optional[float]):
    size_mb = result["size_bytes"] / 1_000_000

    print()
    print("Resultado")
    print("---------")
    print(f"RINEX                 : {result['version']:.2f}")

    if result["input_interval"] is not None:
        print(f"Intervalo original    : {result['input_interval']:.3f} s")

    print(f"Intervalo de saida    : {result['interval']:.3f} s")
    print(f"Epocas originais      : {result['total_epochs']}")
    print(f"Epocas mantidas       : {result['kept_epochs']}")
    print(f"Primeira epoca        : {result['first']}")
    print(f"Ultima epoca          : {result['last']}")
    print(f"Arquivo dentro do ZIP : {result['inner_name']}")
    print(f"ZIP gerado            : {result['output']}")
    print(f"Tamanho               : {size_mb:.2f} MB")

    if max_mb is not None:
        limit = max_mb * 1_000_000
        if result["size_bytes"] <= limit:
            print(f"Limite de {max_mb:g} MB : OK")
        else:
            print(f"Limite de {max_mb:g} MB : EXCEDIDO")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reamostra/decima RINEX OBS preservando as medicoes originais "
            "e gera um arquivo ZIP."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="RINEX OBS ou ZIP contendo exatamente um RINEX OBS",
    )

    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        help="intervalo desejado em segundos (padrao: 1.0)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="nome do ZIP de saida",
    )

    parser.add_argument(
        "--max-mb",
        type=float,
        default=None,
        help="limite de tamanho em MB decimais, por exemplo 25",
    )

    parser.add_argument(
        "--auto-fit",
        action="store_true",
        help=(
            "se ultrapassar --max-mb, dobra o intervalo e tenta novamente "
            "ate caber"
        ),
    )

    parser.add_argument(
        "--compresslevel",
        type=int,
        choices=range(0, 10),
        default=9,
        metavar="0..9",
        help="nivel DEFLATE do ZIP (padrao: 9)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="sobrescreve arquivo de saida existente",
    )

    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Arquivo nao encontrado: {args.input}")

    if args.auto_fit and args.max_mb is None:
        parser.error("--auto-fit exige --max-mb")

    interval = args.interval
    requested_output = args.output

    while True:
        # Se o intervalo mudar pelo auto-fit, deixa o nome ser recalculado.
        output = requested_output if interval == args.interval else None

        result = decimate_once(
            input_path=args.input,
            interval=interval,
            output_path=output,
            compresslevel=args.compresslevel,
            force=args.force or interval != args.interval,
        )

        print_result(result, args.max_mb)

        if args.max_mb is None:
            break

        if result["size_bytes"] <= args.max_mb * 1_000_000:
            break

        if not args.auto_fit:
            print()
            print(
                "O arquivo excede o limite. "
                "Use um intervalo maior ou execute novamente com --auto-fit."
            )
            break

        old_output = result["output"]
        try:
            old_output.unlink()
        except OSError:
            pass

        interval *= 2.0

        print()
        print(
            f"ZIP acima do limite; nova tentativa com intervalo "
            f"{interval:g} s..."
        )


if __name__ == "__main__":
    main()
