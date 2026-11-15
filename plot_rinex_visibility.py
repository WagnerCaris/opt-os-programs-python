#!/usr/bin/env python3

"""
Create an RTKPLOT-like satellite visibility plot from a RINEX 3/4
observation file and calculate receiver-reported cycle-slip statistics.

Outputs:
    <input>_visibility.png
    <input>_visibility.bmp
    <input>_cycle_slips.csv
    <input>_summary.txt

Primary comparison metric:

    slip-event rate [%] =
        100 * unique satellite-epoch slip events
        / satellite-phase epochs

A satellite-phase epoch is one satellite at one epoch containing at least
one valid carrier-phase observation.

A unique slip event is counted only once per satellite and epoch, even if
the LLI slip bit is set simultaneously on multiple carrier-phase signals.

Important:
    This program reads the RINEX Loss of Lock Indicator, LLI. It does not
    independently detect cycle slips using Doppler, geometry-free phase,
    Melbourne-Wubbena, triple differences, or other mathematical methods.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

PROGRAM_VERSION = "RTKPLOT-style v2.1"


# RTKPLOT-like colors. Both frequencies are drawn on the same satellite row.
# The secondary frequency is drawn after the primary frequency, so green is
# visible only where a valid secondary carrier-phase observation exists.
BAND_COLORS = {
    "L1": "#00a8dc",  # blue: primary RTKLIB frequency index
    "L2": "#19c83b",  # green: secondary RTKLIB frequency index
}

SYSTEM_NAMES = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "S": "SBAS",
    "I": "NavIC",
}


@dataclass
class Observation:
    """One RINEX observation field."""

    value: float | None
    lli: int | None
    ssi: int | None


@dataclass
class Epoch:
    """One RINEX observation epoch."""

    time: datetime
    flag: int
    satellites: dict[str, dict[str, Observation]]


def parse_int_character(character: str) -> int | None:
    """Convert one RINEX integer character to an integer."""

    character = character.strip()

    if not character:
        return None

    try:
        return int(character)
    except ValueError:
        return None


def parse_float_field(text: str) -> float | None:
    """Convert a RINEX floating-point field to a Python float."""

    text = text.strip()

    if not text:
        return None

    try:
        return float(text.replace("D", "E"))
    except ValueError:
        return None


def parse_observation_field(field: str) -> Observation:
    """
    Parse a 16-character RINEX observation field.

    Character positions:
        0:14   observation value
        14     Loss of Lock Indicator, LLI
        15     signal-strength indicator, SSI
    """

    field = field.ljust(16)

    return Observation(
        value=parse_float_field(field[:14]),
        lli=parse_int_character(field[14]),
        ssi=parse_int_character(field[15]),
    )


def read_header(
    stream: TextIO,
) -> tuple[float, dict[str, list[str]], list[str]]:
    """
    Read the RINEX observation-file header.

    Returns:
        RINEX version
        observation types for each GNSS system
        original header lines
    """

    observation_types: dict[str, list[str]] = defaultdict(list)
    expected_counts: dict[str, int] = {}
    header_lines: list[str] = []
    version: float | None = None
    current_system: str | None = None

    while True:
        line = stream.readline()

        if not line:
            raise ValueError(
                "Unexpected end of file while reading the RINEX header."
            )

        line = line.rstrip("\n\r")
        header_lines.append(line)

        label = line[60:80].strip() if len(line) >= 60 else ""

        if label == "RINEX VERSION / TYPE":
            try:
                version = float(line[:9])
            except ValueError as exc:
                raise ValueError(
                    "Could not determine the RINEX version."
                ) from exc

        elif label == "SYS / # / OBS TYPES":
            system = line[0].strip()

            if system:
                current_system = system

                try:
                    expected_counts[current_system] = int(line[3:6])
                except ValueError:
                    expected_counts[current_system] = 0

            elif current_system is None:
                raise ValueError(
                    "Invalid SYS / # / OBS TYPES continuation line."
                )

            fields = line[7:60].split()

            if current_system is not None:
                observation_types[current_system].extend(fields)

        elif label == "END OF HEADER":
            break

    if version is None:
        raise ValueError(
            "RINEX VERSION / TYPE was not found in the header."
        )

    if version < 3.0:
        raise ValueError(
            f"This program currently expects RINEX 3 or 4; "
            f"found version {version:.2f}."
        )

    for system, expected_count in expected_counts.items():
        if expected_count > 0:
            observation_types[system] = observation_types[system][
                :expected_count
            ]

    return version, dict(observation_types), header_lines


def parse_epoch_header(line: str) -> tuple[datetime, int, int]:
    """
    Parse a RINEX 3/4 epoch line beginning with '>'.
    """

    if not line.startswith(">"):
        raise ValueError(f"Not a valid RINEX epoch line: {line!r}")

    parts = line[1:].split()

    if len(parts) < 8:
        raise ValueError(f"Malformed RINEX epoch line: {line!r}")

    year = int(parts[0])
    month = int(parts[1])
    day = int(parts[2])
    hour = int(parts[3])
    minute = int(parts[4])
    seconds_float = float(parts[5])
    event_flag = int(parts[6])
    satellite_count = int(parts[7])

    whole_seconds = int(math.floor(seconds_float))
    microseconds = int(
        round((seconds_float - whole_seconds) * 1_000_000)
    )

    epoch_time = datetime(
        year,
        month,
        day,
        hour,
        minute,
        whole_seconds,
    ) + timedelta(microseconds=microseconds)

    return epoch_time, event_flag, satellite_count


def read_satellite_record(
    stream: TextIO,
    first_line: str,
    observation_names: list[str],
) -> tuple[str, dict[str, Observation]]:
    """
    Read one complete RINEX satellite observation record.

    Each observation occupies 16 characters.

    The function supports both:
        - standard 80-character RINEX continuation records;
        - nonstandard longer lines written by some converters.
    """

    satellite = first_line[:3].strip()

    if len(satellite) < 2:
        raise ValueError(
            f"Invalid satellite identifier in line: {first_line!r}"
        )

    required_characters = 16 * len(observation_names)
    data_text = first_line[3:].rstrip("\n\r")

    while len(data_text) < required_characters:
        continuation = stream.readline()

        if not continuation:
            raise ValueError(
                "Unexpected end of file while reading observations "
                f"for satellite {satellite}."
            )

        continuation = continuation.rstrip("\n\r")

        # Standard continuation records contain three leading spaces.
        if len(continuation) >= 3:
            data_text += continuation[3:]
        else:
            data_text += continuation

    observations: dict[str, Observation] = {}

    for index, observation_name in enumerate(observation_names):
        start = index * 16
        field = data_text[start : start + 16]

        observations[observation_name] = parse_observation_field(
            field
        )

    return satellite, observations


def read_rinex_observations(
    filename: Path,
) -> tuple[float, dict[str, list[str]], list[Epoch]]:
    """
    Read all ordinary observation epochs from a RINEX 3/4 OBS file.
    """

    epochs: list[Epoch] = []

    with filename.open(
        "r",
        encoding="ascii",
        errors="replace",
    ) as stream:
        version, observation_types, _ = read_header(stream)

        while True:
            line = stream.readline()

            if not line:
                break

            line = line.rstrip("\n\r")

            if not line:
                continue

            if not line.startswith(">"):
                continue

            epoch_time, flag, satellite_count = parse_epoch_header(
                line
            )

            # Epoch flags 0 and 1 normally contain observation records.
            # Other flags can represent special events or header changes.
            if flag not in (0, 1):
                for _ in range(satellite_count):
                    stream.readline()

                continue

            satellite_data: dict[
                str,
                dict[str, Observation],
            ] = {}

            for _ in range(satellite_count):
                satellite_line = stream.readline()

                if not satellite_line:
                    raise ValueError(
                        "Unexpected end of file while reading "
                        "satellite observation records."
                    )

                system = satellite_line[0]

                if system not in observation_types:
                    raise ValueError(
                        "No observation-type definition was found "
                        f"for GNSS system {system!r}."
                    )

                satellite, observations = read_satellite_record(
                    stream=stream,
                    first_line=satellite_line,
                    observation_names=observation_types[system],
                )

                satellite_data[satellite] = observations

            epochs.append(
                Epoch(
                    time=epoch_time,
                    flag=flag,
                    satellites=satellite_data,
                )
            )

    if not epochs:
        raise ValueError(
            "No ordinary observation epochs were found."
        )

    return version, observation_types, epochs


def is_carrier_phase(observation_name: str) -> bool:
    """
    Return True for carrier-phase observations such as L1C or L2X.
    """

    return observation_name.startswith("L")


def lli_has_cycle_slip(lli: int | None) -> bool:
    """
    Return True when RINEX LLI bit 0 is set.

    LLI bit 0 indicates a possible loss of lock between the previous
    and current observations.

    Consequently, LLI values 1, 3, 5 and 7 contain the slip bit.
    """

    return lli is not None and bool(lli & 1)


def carrier_band(system: str, observation_name: str) -> str | None:
    """Map a RINEX phase signal to RTKLIB's first or second frequency slot.

    RTKPLOT's OBS 1/OBS 2 are frequency *indices*, not simply RINEX signal
    numbers 1 and 2.  This matters especially for Galileo and BeiDou:

      GPS/QZSS/SBAS:  L1 -> first, L2 -> second
      GLONASS:        G1/L1 -> first, G2/L2 -> second
      Galileo:        E1/L1 -> first, E5b/L7 -> second
      BeiDou:         B1I/L2 and B1C/L1 -> first, B2I/B2b/L7 -> second
      NavIC:          L5 -> first, S-band/L9 -> second

    The labels L1 and L2 below therefore mean primary and secondary RTKLIB
    frequency slots, matching the visual logic of RTKPLOT_Qt.
    """

    if not is_carrier_phase(observation_name) or len(observation_name) < 2:
        return None

    frequency_digit = observation_name[1]

    primary_digits = {
        "G": {"1"},
        "R": {"1"},
        "E": {"1"},
        "C": {"1", "2"},
        "J": {"1"},
        "S": {"1"},
        "I": {"5"},
    }
    secondary_digits = {
        "G": {"2"},
        "R": {"2"},
        "E": {"7"},
        "C": {"7"},
        "J": {"2"},
        "S": {"5"},
        "I": {"9"},
    }

    if frequency_digit in primary_digits.get(system, {"1"}):
        return "L1"
    if frequency_digit in secondary_digits.get(system, {"2"}):
        return "L2"
    return None


def collect_results(
    epochs: list[Epoch],
) -> tuple[
    dict[tuple[str, str], list[datetime]],
    dict[tuple[str, str], list[tuple[datetime, str, int]]],
    list[dict[str, object]],
]:
    """Collect L1/L2 visibility and signal-level LLI events."""

    visibility_times: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    slip_flags: dict[tuple[str, str], list[tuple[datetime, str, int]]] = defaultdict(list)
    slip_rows: list[dict[str, object]] = []

    for epoch in epochs:
        for satellite, observations in epoch.satellites.items():
            bands_available: set[str] = set()

            for observation_name, observation in observations.items():
                band = carrier_band(satellite[0], observation_name)
                if band is None:
                    continue

                if observation.value is not None:
                    bands_available.add(band)

                if observation.value is not None and lli_has_cycle_slip(observation.lli):
                    lli_value = int(observation.lli)
                    key = (satellite, band)
                    slip_flags[key].append((epoch.time, observation_name, lli_value))
                    slip_rows.append({
                        "time": epoch.time,
                        "satellite": satellite,
                        "system": satellite[0],
                        "band": band,
                        "signal": observation_name,
                        "lli": lli_value,
                    })

            for band in bands_available:
                visibility_times[(satellite, band)].append(epoch.time)

    return dict(visibility_times), dict(slip_flags), slip_rows


def calculate_slip_statistics(
    epochs: list[Epoch],
    slip_rows: list[dict[str, object]],
) -> dict[str, float | int]:
    """
    Calculate normalized cycle-slip statistics.

    satellite_phase_epochs:
        Number of satellite-epoch combinations having at least one
        valid carrier-phase observation.

    valid_phase_observations:
        Total number of valid carrier-phase observations. L1 and L2,
        for example, are counted separately.

    unique_slip_events:
        One event per satellite and epoch, independently of how many
        carrier-phase signals have their LLI slip bit set.

    signal_lli_flags:
        Every carrier-phase signal having LLI bit 0 set.

    slip_event_percent:
        100 * unique_slip_events / satellite_phase_epochs

    signal_lli_percent:
        100 * signal_lli_flags / valid_phase_observations
    """

    satellite_phase_epochs = 0
    valid_phase_observations = 0

    for epoch in epochs:
        for observations in epoch.satellites.values():
            valid_phase_count = 0

            for observation_name, observation in observations.items():
                if (
                    is_carrier_phase(observation_name)
                    and observation.value is not None
                ):
                    valid_phase_count += 1

            if valid_phase_count > 0:
                satellite_phase_epochs += 1
                valid_phase_observations += valid_phase_count

    unique_events = {
        (
            row["time"],
            row["satellite"],
        )
        for row in slip_rows
    }

    unique_slip_events = len(unique_events)
    signal_lli_flags = len(slip_rows)

    if satellite_phase_epochs > 0:
        slip_event_percent = (
            100.0
            * unique_slip_events
            / satellite_phase_epochs
        )
    else:
        slip_event_percent = 0.0

    if valid_phase_observations > 0:
        signal_lli_percent = (
            100.0
            * signal_lli_flags
            / valid_phase_observations
        )
    else:
        signal_lli_percent = 0.0

    return {
        "satellite_phase_epochs": satellite_phase_epochs,
        "valid_phase_observations": valid_phase_observations,
        "unique_slip_events": unique_slip_events,
        "signal_lli_flags": signal_lli_flags,
        "slip_event_percent": slip_event_percent,
        "signal_lli_percent": signal_lli_percent,
    }


def satellite_sort_key(
    satellite: str,
) -> tuple[int, int, str]:
    """Sort satellites by constellation and PRN number."""

    system_order = {
        "G": 0,
        "R": 1,
        "E": 2,
        "C": 3,
        "J": 4,
        "S": 5,
        "I": 6,
    }

    system = satellite[0]

    try:
        number = int(satellite[1:])
    except ValueError:
        number = 999

    return (
        system_order.get(system, 99),
        number,
        satellite,
    )


def estimate_nominal_interval(
    epochs: list[Epoch],
) -> float:
    """
    Estimate the nominal epoch interval using the median interval.
    """

    timestamps = np.array(
        [
            epoch.time.timestamp()
            for epoch in epochs
        ],
        dtype=float,
    )

    differences = np.diff(timestamps)
    differences = differences[differences > 0]

    if differences.size == 0:
        return 1.0

    return float(np.median(differences))


def split_into_continuous_segments(
    times: list[datetime],
    maximum_gap_seconds: float,
) -> list[list[datetime]]:
    """
    Split satellite observation times into continuous tracking arcs.
    """

    if not times:
        return []

    sorted_times = sorted(set(times))
    segments: list[list[datetime]] = [[sorted_times[0]]]

    for current_time in sorted_times[1:]:
        previous_time = segments[-1][-1]

        gap_seconds = (
            current_time - previous_time
        ).total_seconds()

        if gap_seconds <= maximum_gap_seconds:
            segments[-1].append(current_time)
        else:
            segments.append([current_time])

    return segments


def unique_slip_epochs(
    slip_flags: dict[tuple[str, str], list[tuple[datetime, str, int]]],
) -> dict[tuple[str, str], list[datetime]]:
    """Reduce signal-level LLI events to one event per satellite, band and epoch."""

    return {
        key: sorted({record[0] for record in records})
        for key, records in slip_flags.items()
    }


def calculate_tracking_gaps(
    visibility_times: dict[tuple[str, str], list[datetime]],
    maximum_gap_seconds: float,
) -> dict[
    tuple[str, str],
    list[tuple[datetime, datetime, float]],
]:
    """
    Find carrier-phase tracking gaps for every satellite.

    A tracking gap is not necessarily a cycle slip.
    """

    gaps: dict[
        tuple[str, str],
        list[tuple[datetime, datetime, float]],
    ] = {}

    for key, times in visibility_times.items():
        satellite_gaps: list[
            tuple[datetime, datetime, float]
        ] = []

        sorted_times = sorted(set(times))

        for previous_time, current_time in zip(
            sorted_times[:-1],
            sorted_times[1:],
        ):
            gap_seconds = (
                current_time - previous_time
            ).total_seconds()

            if gap_seconds > maximum_gap_seconds:
                satellite_gaps.append(
                    (
                        previous_time,
                        current_time,
                        gap_seconds,
                    )
                )

        gaps[key] = satellite_gaps

    return gaps


def plot_visibility(
    output_png: Path,
    visibility_times: dict[tuple[str, str], list[datetime]],
    unique_slips: dict[tuple[str, str], list[datetime]],
    nominal_interval: float,
    title: str,
    statistics: dict[str, float | int],
) -> None:
    """Create an RTKPLOT-like plot with both frequencies on one row."""

    satellites = sorted(
        {satellite for satellite, _band in visibility_times},
        key=satellite_sort_key,
    )
    if not satellites:
        raise ValueError(
            "No valid primary or secondary carrier-phase observations were found."
        )

    maximum_continuous_gap = nominal_interval * 1.5
    figure_height = max(7.0, 0.19 * len(satellites) + 2.5)
    fig, ax = plt.subplots(figsize=(16, figure_height), dpi=150)
    y_positions: dict[str, int] = {}

    # Draw the primary frequency first (blue), then the secondary one (green),
    # just as RTKPLOT visually replaces blue with green where OBS 2 is present.
    for index, satellite in enumerate(satellites):
        y_position = len(satellites) - 1 - index
        y_positions[satellite] = y_position

        for band in ("L1", "L2"):
            key = (satellite, band)
            times = visibility_times.get(key, [])
            color = BAND_COLORS[band]

            segments = split_into_continuous_segments(
                times=times,
                maximum_gap_seconds=maximum_continuous_gap,
            )
            for segment in segments:
                if len(segment) == 1:
                    ax.plot(
                        segment, [y_position], marker=".", linestyle="none",
                        color=color, markersize=4,
                        zorder=2 if band == "L1" else 3,
                    )
                else:
                    ax.plot(
                        segment, np.full(len(segment), y_position),
                        color=color, linewidth=2.8, solid_capstyle="butt",
                        zorder=2 if band == "L1" else 3,
                    )

        # RTKPLOT uses one red indication on the satellite row. Merge LLI
        # events from both frequency slots to avoid duplicate red marks.
        slip_times = sorted(
            set(unique_slips.get((satellite, "L1"), []))
            | set(unique_slips.get((satellite, "L2"), []))
        )
        for slip_time in slip_times:
            ax.vlines(
                slip_time, y_position - 0.34, y_position + 0.34,
                color="red", linewidth=1.2, zorder=5,
            )

    ax.set_yticks([y_positions[satellite] for satellite in satellites])
    ax.set_yticklabels(satellites, fontsize=8)
    ax.set_ylim(-1, len(satellites))
    ax.set_ylabel("Satellite No.")
    ax.set_xlabel("Time")
    ax.set_title(
        f"{title} [{PROGRAM_VERSION}]\nCycle-slip event rate: "
        f"{float(statistics['slip_event_percent']):.4f}%",
        fontsize=12,
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=12))
    ax.grid(axis="both", linestyle=":", linewidth=0.5, alpha=0.65)

    statistics_text = (
        "Receiver-reported LLI statistics\n"
        f"Unique slip events: {int(statistics['unique_slip_events'])}\n"
        f"Slip-event rate: {float(statistics['slip_event_percent']):.4f}%\n"
        f"Signal-level LLI flags: {int(statistics['signal_lli_flags'])}\n"
        f"Signal-level LLI rate: {float(statistics['signal_lli_percent']):.4f}%\n"
        f"Satellite-phase epochs: {int(statistics['satellite_phase_epochs'])}\n"
        f"Valid phase observations: {int(statistics['valid_phase_observations'])}"
    )
    ax.text(
        0.995, 0.01, statistics_text, transform=ax.transAxes,
        horizontalalignment="right", verticalalignment="bottom", zorder=10,
        fontsize=9, bbox={
            "facecolor": "lightblue", "alpha": 1.0,
            "edgecolor": "steelblue", "linewidth": 1.0,
            "boxstyle": "round,pad=0.4",
        },
    )
    ax.text(
        0.005, 0.01,
        "Blue line: primary frequency (OBS 1)\n"
        "Green line: secondary frequency (OBS 2)\n"
        "Red mark: LLI bit 0 set",
        transform=ax.transAxes, horizontalalignment="left",
        verticalalignment="bottom", fontsize=8,
        bbox={
            "facecolor": "white", "alpha": 0.85,
            "edgecolor": "0.7", "boxstyle": "round,pad=0.3",
        },
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_png, bbox_inches="tight")
    plt.close(fig)

def write_slip_csv(
    output_csv: Path,
    slip_rows: list[dict[str, object]],
) -> None:
    """
    Write every signal-level LLI slip indication to CSV.
    """

    with output_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.writer(stream)

        writer.writerow(
            [
                "time",
                "satellite",
                "system",
                "band",
                "signal",
                "lli",
            ]
        )

        sorted_rows = sorted(
            slip_rows,
            key=lambda item: (
                item["time"],
                item["satellite"],
                item["signal"],
            ),
        )

        for row in sorted_rows:
            timestamp = row["time"]

            if isinstance(timestamp, datetime):
                timestamp_text = timestamp.isoformat(
                    sep=" ",
                    timespec="milliseconds",
                )
            else:
                timestamp_text = str(timestamp)

            writer.writerow(
                [
                    timestamp_text,
                    row["satellite"],
                    row["system"],
                    row.get("band", ""),
                    row["signal"],
                    row["lli"],
                ]
            )


def write_summary(
    output_file: Path,
    input_file: Path,
    version: float,
    epochs: list[Epoch],
    visibility_times: dict[tuple[str, str], list[datetime]],
    slip_flags: dict[tuple[str, str], list[tuple[datetime, str, int]]],
    unique_slips: dict[tuple[str, str], list[datetime]],
    tracking_gaps: dict[tuple[str, str], list[tuple[datetime, datetime, float]]],
    nominal_interval: float,
    statistics: dict[str, float | int],
) -> None:
    """Write a human-readable summary for RTKLIB frequency slots."""

    total_tracking_gaps = sum(len(records) for records in tracking_gaps.values())
    with output_file.open("w", encoding="utf-8") as stream:
        stream.write(f"Input file: {input_file}\n")
        stream.write(f"RINEX version: {version:.2f}\n")
        stream.write(f"First epoch: {epochs[0].time}\n")
        stream.write(f"Last epoch: {epochs[-1].time}\n")
        stream.write(f"Epochs: {len(epochs)}\n")
        stream.write(f"Estimated nominal interval: {nominal_interval:.6f} s\n")
        stream.write(f"Satellite/frequency slots with carrier phase: {len(visibility_times)}\n\n")
        stream.write(f"UNIQUE SATELLITE-EPOCH LLI SLIP EVENTS: {int(statistics['unique_slip_events'])}\n")
        stream.write(f"SATELLITE-PHASE EPOCHS: {int(statistics['satellite_phase_epochs'])}\n")
        stream.write(f"SLIP-EVENT RATE: {float(statistics['slip_event_percent']):.6f}%\n\n")
        stream.write(f"SIGNAL-LEVEL LLI FLAGS: {int(statistics['signal_lli_flags'])}\n")
        stream.write(f"VALID CARRIER-PHASE OBSERVATIONS: {int(statistics['valid_phase_observations'])}\n")
        stream.write(f"SIGNAL-LEVEL LLI RATE: {float(statistics['signal_lli_percent']):.6f}%\n")
        stream.write(f"TRACKING GAPS (>1.5 nominal intervals): {total_tracking_gaps}\n\n")
        stream.write("Per-satellite/frequency summary:\n")
        stream.write("Satellite Band phase_epochs unique_slip_events slip_rate_percent signal_lli_flags tracking_gaps\n")
        for key in sorted(visibility_times, key=lambda item: (satellite_sort_key(item[0]), item[1])):
            satellite, band = key
            phase_epochs = len(set(visibility_times[key]))
            unique_event_count = len(unique_slips.get(key, []))
            signal_flag_count = len(slip_flags.get(key, []))
            tracking_gap_count = len(tracking_gaps.get(key, []))
            percent = 100.0 * unique_event_count / phase_epochs if phase_epochs else 0.0
            stream.write(f"{satellite:9s} {band:4s} {phase_epochs:12d} "
                         f"{unique_event_count:18d} {percent:17.6f} "
                         f"{signal_flag_count:16d} {tracking_gap_count:13d}\n")


def convert_png_to_bmp(
    input_png: Path,
    output_bmp: Path,
) -> None:
    """Convert the generated PNG plot to BMP."""

    with Image.open(input_png) as image:
        image.convert("RGB").save(
            output_bmp,
            format="BMP",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plot RINEX satellite visibility and calculate "
            "receiver-reported cycle-slip percentages from "
            "carrier-phase LLI fields."
        )
    )

    parser.add_argument(
        "rinex_obs",
        type=Path,
        help="RINEX 3/4 observation file",
    )

    parser.add_argument(
        "--output-prefix",
        type=Path,
        help=(
            "Output prefix. By default, the input filename "
            "without its suffix is used."
        ),
    )

    arguments = parser.parse_args()

    print(f"plot_rinex_visibility: {PROGRAM_VERSION}")
    print("Display mode: one row per satellite; blue=OBS1, green=OBS2 overlay")

    input_file = arguments.rinex_obs.expanduser().resolve()

    if not input_file.is_file():
        print(
            f"Error: file not found: {input_file}",
            file=sys.stderr,
        )
        return 1

    if arguments.output_prefix:
        prefix = arguments.output_prefix.expanduser()
    else:
        prefix = input_file.with_suffix("")

    output_png = Path(
        f"{prefix}_visibility.png"
    )

    output_bmp = Path(
        f"{prefix}_visibility.bmp"
    )

    output_csv = Path(
        f"{prefix}_cycle_slips.csv"
    )

    output_summary = Path(
        f"{prefix}_summary.txt"
    )

    try:
        version, observation_types, epochs = (
            read_rinex_observations(input_file)
        )

        (
            visibility_times,
            slip_flags,
            slip_rows,
        ) = collect_results(epochs)

        statistics = calculate_slip_statistics(
            epochs=epochs,
            slip_rows=slip_rows,
        )

        nominal_interval = estimate_nominal_interval(
            epochs
        )

        maximum_tracking_gap = nominal_interval * 1.5

        unique_slips = unique_slip_epochs(
            slip_flags
        )

        tracking_gaps = calculate_tracking_gaps(
            visibility_times=visibility_times,
            maximum_gap_seconds=maximum_tracking_gap,
        )

        plot_visibility(
            output_png=output_png,
            visibility_times=visibility_times,
            unique_slips=unique_slips,
            nominal_interval=nominal_interval,
            title=input_file.name,
            statistics=statistics,
        )

        convert_png_to_bmp(
            input_png=output_png,
            output_bmp=output_bmp,
        )

        write_slip_csv(
            output_csv=output_csv,
            slip_rows=slip_rows,
        )

        write_summary(
            output_file=output_summary,
            input_file=input_file,
            version=version,
            epochs=epochs,
            visibility_times=visibility_times,
            slip_flags=slip_flags,
            unique_slips=unique_slips,
            tracking_gaps=tracking_gaps,
            nominal_interval=nominal_interval,
            statistics=statistics,
        )

    except Exception as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Input: {input_file}")
    print(f"RINEX version: {version:.2f}")
    print(f"Epochs: {len(epochs)}")
    print(f"Satellite/frequency slots: {len(visibility_times)}")

    print(
        "Nominal interval: "
        f"{nominal_interval:.6f} s"
    )

    print()

    print(
        "Unique satellite-epoch LLI slip events: "
        f"{int(statistics['unique_slip_events'])}"
    )

    print(
        "Satellite-phase epochs: "
        f"{int(statistics['satellite_phase_epochs'])}"
    )

    print(
        "Slip-event rate: "
        f"{float(statistics['slip_event_percent']):.6f}%"
    )

    print()

    print(
        "Signal-level LLI flags: "
        f"{int(statistics['signal_lli_flags'])}"
    )

    print(
        "Valid carrier-phase observations: "
        f"{int(statistics['valid_phase_observations'])}"
    )

    print(
        "Signal-level LLI rate: "
        f"{float(statistics['signal_lli_percent']):.6f}%"
    )

    print()
    print(f"PNG:     {output_png}")
    print(f"BMP:     {output_bmp}")
    print(f"CSV:     {output_csv}")
    print(f"Summary: {output_summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())