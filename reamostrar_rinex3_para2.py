#!/usr/bin/env python3
"""Converte RINEX 3 OBS para RINEX 2.11 OBS, gerando ZIP convencional.

Foco em conversao conservadora de observacoes GNSS para leitores RINEX 2
que exigem a declaracao '# / TYPES OF OBSERV' e o tipo 'C1'.
Preserva os valores originais dos campos selecionados (sem interpolacao).

Exemplo:
  python3 converter_rinex3_para2_ibge.py 308Q_1s.zip \
      --sistemas GR --nome-interno 308Q3080.26O \
      -o 308Q_RINEX2_IBGE.zip

'Sistemas' aceitos: G=GPS, R=GLONASS, E=Galileo.
BDS/BeiDou (C), QZSS (J) e NavIC (I) nao sao exportados, pois nao podem
ser representados adequadamente no formato RINEX 2.11 padrao.
"""
from __future__ import annotations
import argparse
import datetime as dt
import math
import os
import pathlib
import re
import sys
import zipfile

R3_RX2 = {
    'G': {
        'C1': 'C1C', 'L1': 'L1C', 'D1': 'D1C', 'S1': 'S1C',
        'P2': 'C2P', 'L2': 'L2P', 'D2': 'D2P', 'S2': 'S2P',
        'C5': 'C5Q', 'L5': 'L5Q', 'D5': 'D5Q', 'S5': 'S5Q',
    },
    'R': {
        'C1': 'C1C', 'L1': 'L1C', 'D1': 'D1C', 'S1': 'S1C',
        'C2': 'C2C', 'L2': 'L2C', 'D2': 'D2C', 'S2': 'S2C',
    },
    'E': {
        'C1': 'C1C', 'L1': 'L1C', 'D1': 'D1C', 'S1': 'S1C',
        'C5': 'C5Q', 'L5': 'L5Q', 'D5': 'D5Q', 'S5': 'S5Q',
    },
}
# C2P (GPS) corresponde a P2 no RINEX 2; C2C (GLONASS) corresponde a C2.
# Os identificadores de fase, Doppler e SNR preservam banda e fonte.
OUTPUT_OBS_ALL = ['C1', 'L1', 'D1', 'S1', 'P2', 'C2', 'L2', 'D2', 'S2',
                  'C5', 'L5', 'D5', 'S5']


def labeled(text, label):
    return f'{text[:60]:<60}{label:<20}'


def open_input(path):
    if zipfile.is_zipfile(path):
        zin = zipfile.ZipFile(path)
        candidates = [i for i in zin.infolist() if not i.is_dir()
                      and re.search(r'(?i)(\.rnx|\.obs|\.\d\do)$', i.filename)]
        if len(candidates) != 1:
            zin.close()
            raise ValueError('ZIP deve conter exatamente um arquivo OBS RINEX')
        return zin, candidates[0].filename
    return None, None


def input_lines(path, zin, inner):
    if zin:
        f = zin.open(inner, 'r')
    else:
        f = open(path, 'rb')
    try:
        for line in f:
            yield line.decode('ascii', 'strict').rstrip('\r\n')
    finally:
        f.close()


def parse_header(stream):
    header = []
    obs_types = {}
    active = None
    counts = {}
    for line in stream:
        header.append(line)
        label = line[60:80].strip()
        if label == 'SYS / # / OBS TYPES':
            if line[0] != ' ':
                active = line[0]
                obs_types[active] = []
                counts[active] = int(line[1:6])
            if active is None:
                raise ValueError('Cabecalho SYS / # / OBS TYPES inconsistente')
            obs_types[active].extend(line[7:60].split())
        if label == 'END OF HEADER':
            break
    else:
        raise ValueError('Nao ha END OF HEADER')
    if not header[0].startswith('     3.'):
        try:
            version = float(header[0][:9])
        except ValueError:
            version = None
        if not version or not 3.00 <= version < 4.00:
            raise ValueError('Entrada deve ser um RINEX 3.x de observacoes')
    for system, n in counts.items():
        if len(obs_types[system]) != n:
            raise ValueError(f'Quantidade de tipos {system} incorreta: {len(obs_types[system])} != {n}')
    if 'G' not in obs_types or 'C1C' not in obs_types['G']:
        raise ValueError('RINEX nao possui observacao GPS C1C, exigida para C1')
    return header, obs_types


def parse_epoch(line):
    vals = line[1:].split()
    if len(vals) < 8:
        raise ValueError(f'Epoca malformada: {line[:80]!r}')
    year, mo, day, hr, minute = (int(x) for x in vals[:5])
    sec = float(vals[5])
    base = dt.datetime(year, mo, day, hr, minute)
    stamp = base + dt.timedelta(seconds=sec)
    return stamp, int(vals[6]), int(vals[7]), (vals[8] if len(vals) > 8 else None)


def write_header_time(line, time):
    sec = time.second + time.microsecond / 1e6
    prefix = (f'{time.year:6d}{time.month:6d}{time.day:6d}'
              f'{time.hour:6d}{time.minute:6d}{sec:13.7f}')
    return prefix + line[43:]


def build_header(source, types, systems, interval, first, last):
    out = []
    wrote_types = False
    for line in source:
        label = line[60:80].strip()
        if label == 'RINEX VERSION / TYPE':
            syslabel = 'M (MIXED)' if len(systems) > 1 else 'G (GPS)'
            out.append(labeled(f'{2.11:9.2f}{"":11s}{"OBSERVATION DATA":20}{syslabel:20}',label))
        elif label == 'SYS / # / OBS TYPES':
            if not wrote_types:
                for start in range(0, len(types), 9):
                    prefix = f'{len(types):6d}' if start == 0 else ' '*6
                    body = ''.join(f'    {item}' for item in types[start:start+9])
                    out.append(labeled(prefix + body, '# / TYPES OF OBSERV'))
                wrote_types = True
        elif label in ('SYS / PHASE SHIFT', 'GLONASS COD/PHS/BIS',
                       'GLONASS SLOT / FRQ #', 'SIGNAL STRENGTH UNIT',
                       'SYS / DCBS APPLIED', 'SYS / PCVS APPLIED',
                       'SYS / SCALE FACTOR', 'SYS / PHASE SHIFTS'):
            continue
        elif label == 'PGM / RUN BY / DATE':
            out.append(line[:80].ljust(80))
            out.append(labeled('CONVERSAO RINEX 3.X PARA 2.11; DADOS NAO INTERPOLADOS', 'COMMENT'))
            out.append(labeled('GPS C1C->C1, C2P->P2; GLONASS C2C->C2', 'COMMENT'))
        elif label == 'INTERVAL':
            out.append(labeled(f'{interval:10.3f}' + line[10:60],label))
        elif label == 'TIME OF FIRST OBS':
            out.append(write_header_time(line, first)[:80].ljust(80))
        elif label == 'TIME OF LAST OBS':
            out.append(write_header_time(line, last)[:80].ljust(80))
        else:
            out.append(line[:80].ljust(80))
    assert wrote_types
    assert all(len(x) == 80 for x in out)
    return out


def epoch_line(timestamp, flag, sats, clk=None):
    sec = timestamp.second + timestamp.microsecond / 1e6
    yy = timestamp.year % 100
    pfx = (f'{yy:3d}{timestamp.month:3d}{timestamp.day:3d}'
           f'{timestamp.hour:3d}{timestamp.minute:3d}{sec:11.7f}'
           f'  {flag:1d}{len(sats):3d}')
    assert len(pfx) == 32, (pfx,len(pfx))
    result = []
    for start in range(0, max(len(sats), 1), 12):
        head = pfx if start == 0 else ' '*32
        ids = ''.join(sats[start:start+12])
        rec = head + ids
        if start == 0 and clk:
            rec = rec.ljust(68) + f'{float(clk):12.9f}'
        result.append(rec)
    return result


def convert(src, output, systems, interval, inner, overwrite=False, incluir_banda5=False):
    if output.exists() and not overwrite:
        raise FileExistsError(f'Ja existe: {output} (use --sobrescrever)')
    zin, src_inner = open_input(src)
    try:
        s = input_lines(src, zin, src_inner)
        hdr, orig_types = parse_header(s)
        if any(x not in orig_types for x in systems):
            raise ValueError('Uma das constelacoes solicitadas nao existe no cabecalho')
        all_types = [name for name in OUTPUT_OBS_ALL
                     if (incluir_banda5 or name[1] != '5')
                     and any(name in R3_RX2[sys] and R3_RX2[sys][name] in orig_types[sys]
                            for sys in systems)]
        if 'C1' not in all_types:
            raise ValueError('Nao ha observacao C1 para exportacao')
        orig_indices = {sys: {typ: idx for idx,typ in enumerate(orig_types[sys])}
                        for sys in systems}
        maps = {sys: [orig_indices[sys].get(R3_RX2[sys].get(name)) for name in all_types]
                for sys in systems}
        first_source = first = last = None
        total_input = total_output = 0
        # Varredura de epocas para escrever o tempo final correto no cabecalho.
        for line in s:
            if not line.startswith('>'):
                continue
            stamp, flag, _nsat, _clk = parse_epoch(line)
            if flag not in (0,1):
                raise ValueError('Arquivo contem eventos RINEX; conversao manual requerida')
            total_input += 1
            if first_source is None:
                first_source = stamp
            delta = (stamp-first_source).total_seconds()
            if abs(delta/interval - round(delta/interval)) < 0.0001:
                total_output += 1
                first = stamp if first is None else first
                last = stamp
        if not first or not last:
            raise ValueError('Nao foram selecionadas epocas')
        if inner is None:
            stem = pathlib.Path(src_inner).stem if src_inner else src.stem
            station = re.sub(r'[^A-Z0-9]', '', stem.upper())[:4].ljust(4, 'X')
            inner = f'{station}{first.timetuple().tm_yday:03d}0.{first.year % 100:02d}O'
        hdr2 = build_header(hdr, all_types, systems, interval, first, last)
        s = input_lines(src, zin, src_inner)
        parse_header(s)
        n_input = n_output = n_sats = 0
        current = None
        epoch_sats = []
        epoch_records = []
        unselected_sats = set()

        def writeline(out, line):
            out.write((line+'\n').encode('ascii'))

        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(output.name+'.incompleto')
        try:
            with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=9, allowZip64=False) as zout:
                with zout.open(inner, 'w') as dst:
                    for line in hdr2:
                        writeline(dst, line)
                    def flush():
                        nonlocal n_sats, n_output
                        if current is None or not current[4]:
                            return
                        sat_ids = [item[0] for item in epoch_records]
                        for e in epoch_line(current[0], current[1], sat_ids, current[3]):
                            writeline(dst, e)
                        for sid, obs in epoch_records:
                            sys = sid[0]
                            for begin in range(0, len(all_types), 5):
                                fields = []
                                for index in maps[sys][begin:begin+5]:
                                    if index is None:
                                        fields.append(' '*16)
                                    else:
                                        start = 3 + 16*index
                                        fields.append(obs[start:start+16].ljust(16))
                                writeline(dst, ''.join(fields))
                            n_sats += 1
                        n_output += 1

                    for line in s:
                        if line.startswith('>'):
                            flush()
                            stamp, flag, n_raw, clk = parse_epoch(line)
                            n_input += 1
                            delta = (stamp-first_source).total_seconds()
                            keep = abs(delta/interval-round(delta/interval)) < 0.0001
                            current = (stamp, flag, n_raw, clk, keep)
                            epoch_sats = []
                            epoch_records = []
                        else:
                            if current is None or not current[4]:
                                continue
                            sid = line[:3]
                            if sid[0] in systems:
                                epoch_records.append((sid, line))
                            else:
                                unselected_sats.add(sid[0])
                    flush()
            if n_input != total_input or n_output != total_output:
                raise AssertionError('Contagem de epocas mudou durante a conversao')
            with zipfile.ZipFile(temp) as z:
                if z.testzip():
                    raise IOError('Falha CRC do ZIP resultante')
                assert z.namelist() == [inner]
                assert z.getinfo(inner).extract_version == 20, 'ZIP64 inesperado'
            os.replace(temp, output)
        finally:
            if temp.exists():
                temp.unlink()
        return {'entrada':n_input, 'epocas':n_output,'sat_observacoes':n_sats,
                'tipos': all_types, 'sistemas': systems,
                'removidos': sorted(unselected_sats), 'primeira':first,
                'ultima':last, 'bytes':output.stat().st_size,
                'zip':str(output),'interno':inner}
    finally:
        if zin:zin.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('entrada', type=pathlib.Path)
    ap.add_argument('-o','--saida', type=pathlib.Path)
    ap.add_argument('--sistemas', choices=['G','GR','GRE'], default='GR')
    ap.add_argument('--intervalo', type=int, default=1)
    ap.add_argument('--nome-interno', default=None,
                    help='Nome do RINEX 2 dentro do ZIP (ex.: 308Q3080.26O); automatico se omitido')
    ap.add_argument('--banda5', action='store_true',
                    help='Tambem exporta sinais GPS L5 / Galileo E5 quando presentes')
    ap.add_argument('--sobrescrever', action='store_true')
    a=ap.parse_args()
    if a.intervalo < 1:
        ap.error('intervalo deve ser inteiro maior que zero')
    if a.nome_interno is not None and not re.search(r'\.\d\do$',a.nome_interno,re.I):
        ap.error('nome-interno deve terminar em .YYO (RINEX 2)')
    output=a.saida or a.entrada.with_name(a.entrada.stem+'_RINEX2_IBGE.zip')
    info=convert(a.entrada,output,a.sistemas,a.intervalo,a.nome_interno,a.sobrescrever,a.banda5)
    for k,v in info.items():print(f'{k}: {v}')

if __name__=='__main__':main()
