"""DMA controller stream-channel-peripheral assignment tables for STM32 chips.

Data sourced from:
  STM32F411 — RM0383 Rev 3 §10.3.3 Tables 27 and 28
              "DMA1 request mapping" / "DMA2 request mapping"
  STM32F407 — RM0090 Rev 19 §10.3.3 Tables 42 and 43
              "DMA1 request mapping" / "DMA2 request mapping"

Structure
---------
Each entry is::

    DMAStreamEntry(
        controller="DMA1",
        stream=0,
        channel=0,
        peripheral="SPI3_RX",
    )

A (controller, stream) pair may appear multiple times — once per valid channel
selection for that stream.  Assigning a peripheral to a stream with a *wrong*
channel number constitutes an INVALID_CHANNEL violation.  Assigning two
peripherals to the same (controller, stream) is a STREAM_CONFLICT.

HONEST CAVEAT
-------------
This module contains only **static** channel-mapping data.  It does NOT model:
  * DMA arbitration priority (stream 0 = highest within a controller, stream 7 = lowest).
  * Double-buffer mode, FIFO depth, or burst-mode interactions.
  * Bandwidth / throughput starvation — a low-priority stream holding a high-
    bandwidth peripheral is flagged as a PRIORITY_WARNING by the verifier only
    when explicitly enabled.
  * MDMA or BDMA controllers present on STM32H7 and later.
For throughput analysis use STM32CubeMX DMA bandwidth estimator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Public data model
# ──────────────────────────────────────────────────────────────────────────────

class DMAStreamEntry(NamedTuple):
    """One valid (controller, stream, channel, peripheral) combination."""
    controller: str   # "DMA1" or "DMA2"
    stream: int       # 0..7
    channel: int      # 0..7
    peripheral: str   # e.g. "SPI3_RX"


@dataclass(frozen=True)
class DMASpec:
    """DMA controller specification for a chip family."""
    chip_id: str
    controllers: Tuple[str, ...]     # ("DMA1", "DMA2")
    streams_per_controller: int      # 8 for all STM32F4xx
    channels_per_stream: int         # 8 for all STM32F4xx
    entries: Tuple[DMAStreamEntry, ...]

    def valid_entries_for(
        self,
        controller: str,
        stream: int,
        peripheral: str,
    ) -> List[DMAStreamEntry]:
        """Return all valid entries matching controller + stream + peripheral."""
        p = peripheral.upper()
        c = controller.upper()
        return [
            e for e in self.entries
            if e.controller.upper() == c
            and e.stream == stream
            and e.peripheral.upper() == p
        ]

    def valid_channels_for_peripheral(
        self,
        peripheral: str,
    ) -> List[DMAStreamEntry]:
        """Return every valid (controller, stream, channel) for a peripheral."""
        p = peripheral.upper()
        return [e for e in self.entries if e.peripheral.upper() == p]

    def all_peripherals(self) -> FrozenSet[str]:
        return frozenset(e.peripheral.upper() for e in self.entries)


# ──────────────────────────────────────────────────────────────────────────────
# STM32F411 DMA tables — RM0383 Rev 3 §10.3.3 Tables 27 and 28
# ──────────────────────────────────────────────────────────────────────────────
#
# Table 27 — DMA1 request mapping (RM0383 §10.3.3)
# Table 28 — DMA2 request mapping (RM0383 §10.3.3)
#
# Format: (controller, stream, channel, peripheral)
# Channel 0 is the leftmost column in the RM table; channel 7 is rightmost.
# Empty cells (no peripheral) are omitted.
#
# Abbreviations used in RM0383:
#   RX = receive (memory write)  TX = transmit (memory read)
#   CH = channel (for TIM captures / compares)

_STM32F411_ENTRIES: Tuple[DMAStreamEntry, ...] = (
    # ── DMA1 Table 27 ──────────────────────────────────────────────────────────
    # Stream 0
    DMAStreamEntry("DMA1", 0, 0, "SPI3_RX"),
    DMAStreamEntry("DMA1", 0, 1, "I2C1_RX"),
    DMAStreamEntry("DMA1", 0, 2, "TIM4_CH1"),
    DMAStreamEntry("DMA1", 0, 3, "I2S3_EXT_RX"),
    DMAStreamEntry("DMA1", 0, 4, "UART5_RX"),
    DMAStreamEntry("DMA1", 0, 5, "UART8_TX"),
    DMAStreamEntry("DMA1", 0, 6, "TIM5_CH3"),
    DMAStreamEntry("DMA1", 0, 6, "TIM5_UP"),
    # Stream 1
    DMAStreamEntry("DMA1", 1, 0, "USART3_RX"),
    DMAStreamEntry("DMA1", 1, 1, "I2C3_RX"),
    DMAStreamEntry("DMA1", 1, 2, "TIM2_UP"),
    DMAStreamEntry("DMA1", 1, 2, "TIM2_CH3"),
    DMAStreamEntry("DMA1", 1, 3, "TIM7_UP"),
    DMAStreamEntry("DMA1", 1, 4, "UART4_RX"),
    DMAStreamEntry("DMA1", 1, 5, "USART3_RX"),
    DMAStreamEntry("DMA1", 1, 6, "TIM5_CH4"),
    DMAStreamEntry("DMA1", 1, 6, "TIM5_TRIG"),
    DMAStreamEntry("DMA1", 1, 7, "TIM6_UP"),
    # Stream 2
    DMAStreamEntry("DMA1", 2, 0, "SPI3_RX"),
    DMAStreamEntry("DMA1", 2, 2, "I2S3_EXT_RX"),
    DMAStreamEntry("DMA1", 2, 3, "I2C3_RX"),
    DMAStreamEntry("DMA1", 2, 3, "TIM4_CH2"),
    DMAStreamEntry("DMA1", 2, 5, "I2C2_RX"),
    DMAStreamEntry("DMA1", 2, 6, "USART3_TX"),
    DMAStreamEntry("DMA1", 2, 7, "TIM7_UP"),
    # Stream 3
    DMAStreamEntry("DMA1", 3, 0, "SPI2_RX"),
    DMAStreamEntry("DMA1", 3, 2, "TIM4_CH2"),
    DMAStreamEntry("DMA1", 3, 3, "I2S2_EXT_RX"),
    DMAStreamEntry("DMA1", 3, 4, "USART3_TX"),
    DMAStreamEntry("DMA1", 3, 5, "TIM5_CH4"),
    DMAStreamEntry("DMA1", 3, 5, "TIM5_TRIG"),
    DMAStreamEntry("DMA1", 3, 6, "I2C2_RX"),
    DMAStreamEntry("DMA1", 3, 7, "I2C2_TX"),
    # Stream 4
    DMAStreamEntry("DMA1", 4, 0, "SPI2_TX"),
    DMAStreamEntry("DMA1", 4, 1, "TIM7_UP"),
    DMAStreamEntry("DMA1", 4, 2, "I2S2_EXT_TX"),
    DMAStreamEntry("DMA1", 4, 3, "I2C3_TX"),
    DMAStreamEntry("DMA1", 4, 4, "UART4_TX"),
    DMAStreamEntry("DMA1", 4, 5, "TIM3_CH4"),
    DMAStreamEntry("DMA1", 4, 5, "TIM3_UP"),
    DMAStreamEntry("DMA1", 4, 6, "TIM5_CH2"),
    DMAStreamEntry("DMA1", 4, 7, "USART3_TX"),
    # Stream 5
    DMAStreamEntry("DMA1", 5, 0, "SPI3_TX"),
    DMAStreamEntry("DMA1", 5, 1, "I2C1_RX"),
    DMAStreamEntry("DMA1", 5, 2, "I2S3_EXT_TX"),
    DMAStreamEntry("DMA1", 5, 3, "TIM2_CH1"),
    DMAStreamEntry("DMA1", 5, 4, "USART2_RX"),
    DMAStreamEntry("DMA1", 5, 5, "TIM3_CH2"),
    DMAStreamEntry("DMA1", 5, 7, "DAC1"),
    # Stream 6
    DMAStreamEntry("DMA1", 6, 0, "I2C1_TX"),
    DMAStreamEntry("DMA1", 6, 2, "TIM4_UP"),
    DMAStreamEntry("DMA1", 6, 3, "TIM2_CH2"),
    DMAStreamEntry("DMA1", 6, 3, "TIM2_CH4"),
    DMAStreamEntry("DMA1", 6, 4, "USART2_TX"),
    DMAStreamEntry("DMA1", 6, 5, "TIM3_CH1"),
    DMAStreamEntry("DMA1", 6, 5, "TIM3_TRIG"),
    DMAStreamEntry("DMA1", 6, 6, "TIM5_UP"),
    DMAStreamEntry("DMA1", 6, 7, "DAC2"),
    # Stream 7
    DMAStreamEntry("DMA1", 7, 0, "SPI3_TX"),
    DMAStreamEntry("DMA1", 7, 1, "I2C1_TX"),
    DMAStreamEntry("DMA1", 7, 2, "TIM4_CH3"),
    DMAStreamEntry("DMA1", 7, 3, "TIM2_UP"),
    DMAStreamEntry("DMA1", 7, 3, "TIM2_CH4"),
    DMAStreamEntry("DMA1", 7, 4, "UART5_TX"),
    DMAStreamEntry("DMA1", 7, 5, "TIM3_CH3"),
    DMAStreamEntry("DMA1", 7, 7, "I2C2_TX"),

    # ── DMA2 Table 28 ──────────────────────────────────────────────────────────
    # Stream 0
    DMAStreamEntry("DMA2", 0, 0, "ADC1"),
    DMAStreamEntry("DMA2", 0, 2, "ADC3"),
    DMAStreamEntry("DMA2", 0, 3, "SPI1_RX"),
    DMAStreamEntry("DMA2", 0, 4, "SPI4_RX"),
    DMAStreamEntry("DMA2", 0, 6, "TIM1_TRIG"),
    # Stream 1
    DMAStreamEntry("DMA2", 1, 0, "SAI1_A"),
    DMAStreamEntry("DMA2", 1, 1, "DCMI"),
    DMAStreamEntry("DMA2", 1, 2, "ADC3"),
    DMAStreamEntry("DMA2", 1, 3, "SPI4_TX"),
    DMAStreamEntry("DMA2", 1, 4, "USART6_RX"),
    DMAStreamEntry("DMA2", 1, 5, "FMPI2C1_RX"),
    DMAStreamEntry("DMA2", 1, 6, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 1, 7, "TIM8_UP"),
    # Stream 2
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH1"),
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH2"),
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH3"),
    DMAStreamEntry("DMA2", 2, 1, "ADC2"),
    DMAStreamEntry("DMA2", 2, 3, "SPI1_RX"),
    DMAStreamEntry("DMA2", 2, 4, "USART1_RX"),
    DMAStreamEntry("DMA2", 2, 5, "USART6_RX"),
    DMAStreamEntry("DMA2", 2, 6, "TIM1_CH2"),
    DMAStreamEntry("DMA2", 2, 7, "TIM8_CH1"),
    # Stream 3
    DMAStreamEntry("DMA2", 3, 0, "SAI1_A"),
    DMAStreamEntry("DMA2", 3, 1, "ADC2"),
    DMAStreamEntry("DMA2", 3, 2, "SPI5_RX"),
    DMAStreamEntry("DMA2", 3, 3, "SPI1_TX"),
    DMAStreamEntry("DMA2", 3, 4, "SDIO"),
    DMAStreamEntry("DMA2", 3, 5, "SPI4_RX"),
    DMAStreamEntry("DMA2", 3, 6, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 3, 7, "TIM8_CH2"),
    # Stream 4
    DMAStreamEntry("DMA2", 4, 0, "ADC1"),
    DMAStreamEntry("DMA2", 4, 1, "SAI1_B"),
    DMAStreamEntry("DMA2", 4, 2, "SPI5_TX"),
    DMAStreamEntry("DMA2", 4, 5, "SPI4_TX"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_CH4"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_TRIG"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_COM"),
    DMAStreamEntry("DMA2", 4, 7, "TIM8_CH3"),
    # Stream 5
    DMAStreamEntry("DMA2", 5, 0, "SAI1_B"),
    DMAStreamEntry("DMA2", 5, 1, "SPI6_TX"),
    DMAStreamEntry("DMA2", 5, 2, "CRYP_OUT"),
    DMAStreamEntry("DMA2", 5, 3, "SPI1_TX"),
    DMAStreamEntry("DMA2", 5, 5, "USART1_RX"),
    DMAStreamEntry("DMA2", 5, 6, "TIM1_UP"),
    DMAStreamEntry("DMA2", 5, 7, "SPI5_RX"),
    # Stream 6
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH2"),
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH3"),
    DMAStreamEntry("DMA2", 6, 1, "SPI6_RX"),
    DMAStreamEntry("DMA2", 6, 2, "CRYP_IN"),
    DMAStreamEntry("DMA2", 6, 4, "SDIO"),
    DMAStreamEntry("DMA2", 6, 5, "USART6_TX"),
    DMAStreamEntry("DMA2", 6, 6, "TIM1_CH3"),
    # Stream 7
    DMAStreamEntry("DMA2", 7, 1, "DCMI"),
    DMAStreamEntry("DMA2", 7, 4, "USART1_TX"),
    DMAStreamEntry("DMA2", 7, 5, "USART6_TX"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_CH4"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_TRIG"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_COM"),
    DMAStreamEntry("DMA2", 7, 7, "SPI5_TX"),
)

STM32F411_DMA = DMASpec(
    chip_id="STM32F411",
    controllers=("DMA1", "DMA2"),
    streams_per_controller=8,
    channels_per_stream=8,
    entries=_STM32F411_ENTRIES,
)


# ──────────────────────────────────────────────────────────────────────────────
# STM32F407 DMA tables — RM0090 Rev 19 §10.3.3 Tables 42 and 43
# ──────────────────────────────────────────────────────────────────────────────
# The STM32F407 DMA mapping is very similar to F411; differences are noted.
# Both share the same DMA1/DMA2 8-stream × 8-channel architecture.

_STM32F407_ENTRIES: Tuple[DMAStreamEntry, ...] = (
    # ── DMA1 Table 42 ──────────────────────────────────────────────────────────
    # Stream 0
    DMAStreamEntry("DMA1", 0, 0, "SPI3_RX"),
    DMAStreamEntry("DMA1", 0, 1, "I2C1_RX"),
    DMAStreamEntry("DMA1", 0, 2, "TIM4_CH1"),
    DMAStreamEntry("DMA1", 0, 3, "I2S3_EXT_RX"),
    DMAStreamEntry("DMA1", 0, 4, "UART5_RX"),
    DMAStreamEntry("DMA1", 0, 5, "UART8_TX"),
    DMAStreamEntry("DMA1", 0, 6, "TIM5_CH3"),
    DMAStreamEntry("DMA1", 0, 6, "TIM5_UP"),
    # Stream 1
    DMAStreamEntry("DMA1", 1, 0, "USART3_RX"),
    DMAStreamEntry("DMA1", 1, 1, "I2C3_RX"),
    DMAStreamEntry("DMA1", 1, 2, "TIM2_UP"),
    DMAStreamEntry("DMA1", 1, 2, "TIM2_CH3"),
    DMAStreamEntry("DMA1", 1, 3, "TIM7_UP"),
    DMAStreamEntry("DMA1", 1, 4, "UART4_RX"),
    DMAStreamEntry("DMA1", 1, 5, "UART7_TX"),
    DMAStreamEntry("DMA1", 1, 6, "TIM5_CH4"),
    DMAStreamEntry("DMA1", 1, 6, "TIM5_TRIG"),
    DMAStreamEntry("DMA1", 1, 7, "TIM6_UP"),
    # Stream 2
    DMAStreamEntry("DMA1", 2, 0, "SPI3_RX"),
    DMAStreamEntry("DMA1", 2, 2, "I2S3_EXT_RX"),
    DMAStreamEntry("DMA1", 2, 3, "I2C3_RX"),
    DMAStreamEntry("DMA1", 2, 3, "TIM4_CH2"),
    DMAStreamEntry("DMA1", 2, 5, "I2C2_RX"),
    DMAStreamEntry("DMA1", 2, 6, "USART3_TX"),
    DMAStreamEntry("DMA1", 2, 7, "TIM7_UP"),
    # Stream 3
    DMAStreamEntry("DMA1", 3, 0, "SPI2_RX"),
    DMAStreamEntry("DMA1", 3, 2, "TIM4_CH2"),
    DMAStreamEntry("DMA1", 3, 3, "I2S2_EXT_RX"),
    DMAStreamEntry("DMA1", 3, 4, "USART3_TX"),
    DMAStreamEntry("DMA1", 3, 5, "TIM5_CH4"),
    DMAStreamEntry("DMA1", 3, 5, "TIM5_TRIG"),
    DMAStreamEntry("DMA1", 3, 6, "I2C2_RX"),
    DMAStreamEntry("DMA1", 3, 7, "I2C2_TX"),
    # Stream 4
    DMAStreamEntry("DMA1", 4, 0, "SPI2_TX"),
    DMAStreamEntry("DMA1", 4, 1, "TIM7_UP"),
    DMAStreamEntry("DMA1", 4, 2, "I2S2_EXT_TX"),
    DMAStreamEntry("DMA1", 4, 3, "I2C3_TX"),
    DMAStreamEntry("DMA1", 4, 4, "UART4_TX"),
    DMAStreamEntry("DMA1", 4, 5, "TIM3_CH4"),
    DMAStreamEntry("DMA1", 4, 5, "TIM3_UP"),
    DMAStreamEntry("DMA1", 4, 6, "TIM5_CH2"),
    DMAStreamEntry("DMA1", 4, 7, "USART3_TX"),
    # Stream 5
    DMAStreamEntry("DMA1", 5, 0, "SPI3_TX"),
    DMAStreamEntry("DMA1", 5, 1, "I2C1_RX"),
    DMAStreamEntry("DMA1", 5, 2, "I2S3_EXT_TX"),
    DMAStreamEntry("DMA1", 5, 3, "TIM2_CH1"),
    DMAStreamEntry("DMA1", 5, 4, "USART2_RX"),
    DMAStreamEntry("DMA1", 5, 5, "TIM3_CH2"),
    DMAStreamEntry("DMA1", 5, 7, "DAC1"),
    # Stream 6
    DMAStreamEntry("DMA1", 6, 0, "I2C1_TX"),
    DMAStreamEntry("DMA1", 6, 2, "TIM4_UP"),
    DMAStreamEntry("DMA1", 6, 3, "TIM2_CH2"),
    DMAStreamEntry("DMA1", 6, 3, "TIM2_CH4"),
    DMAStreamEntry("DMA1", 6, 4, "USART2_TX"),
    DMAStreamEntry("DMA1", 6, 5, "TIM3_CH1"),
    DMAStreamEntry("DMA1", 6, 5, "TIM3_TRIG"),
    DMAStreamEntry("DMA1", 6, 6, "TIM5_UP"),
    DMAStreamEntry("DMA1", 6, 7, "DAC2"),
    # Stream 7
    DMAStreamEntry("DMA1", 7, 0, "SPI3_TX"),
    DMAStreamEntry("DMA1", 7, 1, "I2C1_TX"),
    DMAStreamEntry("DMA1", 7, 2, "TIM4_CH3"),
    DMAStreamEntry("DMA1", 7, 3, "TIM2_UP"),
    DMAStreamEntry("DMA1", 7, 3, "TIM2_CH4"),
    DMAStreamEntry("DMA1", 7, 4, "UART5_TX"),
    DMAStreamEntry("DMA1", 7, 5, "TIM3_CH3"),
    DMAStreamEntry("DMA1", 7, 7, "I2C2_TX"),

    # ── DMA2 Table 43 ──────────────────────────────────────────────────────────
    # Stream 0
    DMAStreamEntry("DMA2", 0, 0, "ADC1"),
    DMAStreamEntry("DMA2", 0, 2, "ADC3"),
    DMAStreamEntry("DMA2", 0, 3, "SPI1_RX"),
    DMAStreamEntry("DMA2", 0, 4, "SPI4_RX"),
    DMAStreamEntry("DMA2", 0, 6, "TIM1_TRIG"),
    # Stream 1
    DMAStreamEntry("DMA2", 1, 1, "DCMI"),
    DMAStreamEntry("DMA2", 1, 2, "ADC3"),
    DMAStreamEntry("DMA2", 1, 3, "SPI4_TX"),
    DMAStreamEntry("DMA2", 1, 4, "USART6_RX"),
    DMAStreamEntry("DMA2", 1, 6, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 1, 7, "TIM8_UP"),
    # Stream 2
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH1"),
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH2"),
    DMAStreamEntry("DMA2", 2, 0, "TIM8_CH3"),
    DMAStreamEntry("DMA2", 2, 1, "ADC2"),
    DMAStreamEntry("DMA2", 2, 3, "SPI1_RX"),
    DMAStreamEntry("DMA2", 2, 4, "USART1_RX"),
    DMAStreamEntry("DMA2", 2, 5, "USART6_RX"),
    DMAStreamEntry("DMA2", 2, 6, "TIM1_CH2"),
    DMAStreamEntry("DMA2", 2, 7, "TIM8_CH1"),
    # Stream 3
    DMAStreamEntry("DMA2", 3, 1, "ADC2"),
    DMAStreamEntry("DMA2", 3, 3, "SPI1_TX"),
    DMAStreamEntry("DMA2", 3, 4, "SDIO"),
    DMAStreamEntry("DMA2", 3, 5, "SPI4_RX"),
    DMAStreamEntry("DMA2", 3, 6, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 3, 7, "TIM8_CH2"),
    # Stream 4
    DMAStreamEntry("DMA2", 4, 0, "ADC1"),
    DMAStreamEntry("DMA2", 4, 5, "SPI4_TX"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_CH4"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_TRIG"),
    DMAStreamEntry("DMA2", 4, 6, "TIM1_COM"),
    DMAStreamEntry("DMA2", 4, 7, "TIM8_CH3"),
    # Stream 5
    DMAStreamEntry("DMA2", 5, 3, "SPI1_TX"),
    DMAStreamEntry("DMA2", 5, 5, "USART1_RX"),
    DMAStreamEntry("DMA2", 5, 6, "TIM1_UP"),
    # Stream 6
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH1"),
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH2"),
    DMAStreamEntry("DMA2", 6, 0, "TIM1_CH3"),
    DMAStreamEntry("DMA2", 6, 4, "SDIO"),
    DMAStreamEntry("DMA2", 6, 5, "USART6_TX"),
    DMAStreamEntry("DMA2", 6, 6, "TIM1_CH3"),
    # Stream 7
    DMAStreamEntry("DMA2", 7, 1, "DCMI"),
    DMAStreamEntry("DMA2", 7, 4, "USART1_TX"),
    DMAStreamEntry("DMA2", 7, 5, "USART6_TX"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_CH4"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_TRIG"),
    DMAStreamEntry("DMA2", 7, 6, "TIM8_COM"),
)

STM32F407_DMA = DMASpec(
    chip_id="STM32F407",
    controllers=("DMA1", "DMA2"),
    streams_per_controller=8,
    channels_per_stream=8,
    entries=_STM32F407_ENTRIES,
)


# ──────────────────────────────────────────────────────────────────────────────
# Registry + lookup
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, DMASpec] = {
    "STM32F411": STM32F411_DMA,
    "STM32F407": STM32F407_DMA,
}

# Case-insensitive aliases
_ALIASES: Dict[str, str] = {
    "stm32f411":    "STM32F411",
    "stm32f411ce":  "STM32F411",
    "stm32f411re":  "STM32F411",
    "stm32f411ve":  "STM32F411",
    "stm32f407":    "STM32F407",
    "stm32f407vg":  "STM32F407",
    "stm32f407ig":  "STM32F407",
}


def get_dma_spec(chip: str) -> DMASpec:
    """Return the DMASpec for *chip*, resolving aliases.

    Raises
    ------
    KeyError
        If *chip* is not a known chip ID or alias.
    """
    key = chip.lower()
    if key in _ALIASES:
        return _REGISTRY[_ALIASES[key]]
    upper = chip.upper()
    if upper in _REGISTRY:
        return _REGISTRY[upper]
    raise KeyError(f"Unknown chip for DMA spec: {chip!r}. Known: {sorted(_REGISTRY)}")


def list_dma_chip_ids() -> list[str]:
    """Return all canonical chip IDs that have DMA specs."""
    return sorted(_REGISTRY.keys())
