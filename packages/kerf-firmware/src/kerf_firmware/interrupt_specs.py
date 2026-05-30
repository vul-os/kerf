"""NVIC interrupt vector tables and recommended priority bands for STM32 chips.

Data sourced from:
  STM32F411 — RM0383 Rev 3 §10.1.2 Table 37 "Vector table for STM32F411xC/E"
               (~62 maskable IRQs, positions 0–61)
  STM32F407 — RM0090 Rev 19 §10.1.2 Table 62 "Vector table for STM32F40x and STM32F41x"
               (~82 maskable IRQs, positions 0–81)

Cortex-M NVIC references:
  ARM Cortex-M Generic User Guide §B3.3 — NVIC_IPR registers, PRIGROUP, preemption/sub-priority
  ARM Cortex-M Generic User Guide §B1.5.4 — BASEPRI register (disable interrupts below threshold)

Priority band recommendations:
  These are guidance values derived from common STM32 application patterns and
  ARM Cortex-M best-practice guidance.  They are NOT mandated by RM0383 or the
  ARM Architecture Reference Manual.

Structure
---------
Each IRQSpec entry contains:
  irq_n     — IRQ position in the NVIC vector table (starting at 0 = WWDG)
  name      — peripheral/signal name (upper-case, matches assignment keys)
  rt_class  — "RT" (real-time critical), "NORMAL", or "LOW"
  aliases   — alternate names accepted in assignment dicts

HONEST CAVEAT — STATIC ANALYSIS ONLY
-------------------------------------
This module provides STATIC priority tables and band recommendations only.
It does NOT model:
  * Actual worst-case execution time (WCET) of ISR bodies.
  * Stack usage or priority inversion from RTOS mutexes.
  * Tail-chaining or late-arrival latency on Cortex-M.
  * Whether interrupts are actually enabled in firmware (no NVIC_ISER awareness).
Use ARM DS-5 / Ozone / Tracealyzer for runtime interrupt latency profiling.

References
----------
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.3
  RM0383 Rev 3 §10 — STM32F411 interrupt controller
  RM0090 Rev 19 §10 — STM32F407 interrupt controller
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

class IRQSpec(NamedTuple):
    """One IRQ vector entry.

    Attributes
    ----------
    irq_n:
        IRQ position in the NVIC vector table (0 = first maskable IRQ, WWDG on
        STM32F4xx).  Matches the ``IRQn_Type`` enum in CMSIS device headers.
    name:
        Canonical peripheral/signal name (upper-case).  E.g. ``"TIM2"``,
        ``"USART1"``, ``"EXTI0"``.
    rt_class:
        Real-time classification:
        ``"RT"``     — time-critical; should use a low priority number (high
                       precedence).  Examples: motor control timers, encoder
                       inputs, safety-critical EXTI lines.
        ``"NORMAL"`` — general-purpose peripherals (USART, SPI, I2C, etc.).
        ``"LOW"``    — non-real-time; may tolerate high priority numbers.
                       Examples: USB full-speed, ADC (polled), RTC.
    aliases:
        Alternative names that map to this IRQ (e.g. ``"TIM2_IRQn"`` or
        ``"tim2"``).  Case-insensitive matching is done by callers.
    """
    irq_n: int
    name: str
    rt_class: str  # "RT" | "NORMAL" | "LOW"
    aliases: Tuple[str, ...] = ()


@dataclass
class InterruptSpec:
    """NVIC specification for a chip family.

    Attributes
    ----------
    chip_id:
        Canonical chip identifier, e.g. ``"STM32F411"``.
    priority_bits:
        Number of implemented priority bits.  STM32F4xx implements 4 bits
        (NVIC_PRIO_BITS = 4 in CMSIS), giving 16 levels (0..15).
        Priority value 0 is HIGHEST; 15 is LOWEST.
    prigroup_default:
        Default AIRCR.PRIGROUP value assumed when not set by user.
        STM32 HAL default is PRIGROUP=4 (3 preempt bits + 1 sub-priority bit).
        See ARM Cortex-M Generic User Guide §B3.3 Table B3-2.
    irqs:
        List of all :class:`IRQSpec` entries for this chip.
    aliases:
        Chip alias strings (case-insensitive) that resolve to this spec.
        E.g. ``["stm32f411re", "stm32f411ce", "stm32f411ve"]``.
    """
    chip_id: str
    priority_bits: int
    prigroup_default: int
    irqs: List[IRQSpec]
    aliases: List[str] = field(default_factory=list)

    @property
    def max_priority(self) -> int:
        """Minimum numeric value (highest actual priority) = 0."""
        return 0

    @property
    def min_priority(self) -> int:
        """Maximum numeric value (lowest actual priority) = 2**priority_bits - 1."""
        return (1 << self.priority_bits) - 1

    def num_preempt_levels(self, prigroup: Optional[int] = None) -> int:
        """Number of preemption priority levels for a given PRIGROUP.

        ARM Cortex-M Generic User Guide §B3.3 Table B3-2:
          PRIGROUP splits the 8-bit NVIC_IPR byte.  Using the CMSIS
          NVIC_EncodePriority convention:
            preempt_bits = min(priority_bits, max(0, 7 - prigroup))
          For a 4-bit field (STM32F4xx):
            PRIGROUP=3 → preempt_bits=4, sub_bits=0 → 16 preempt levels
            PRIGROUP=4 → preempt_bits=3, sub_bits=1 →  8 preempt levels
            PRIGROUP=5 → preempt_bits=2, sub_bits=2 →  4 preempt levels
            PRIGROUP=6 → preempt_bits=1, sub_bits=3 →  2 preempt levels
            PRIGROUP=7 → preempt_bits=0, sub_bits=4 →  1 preempt level
        """
        pg = prigroup if prigroup is not None else self.prigroup_default
        # CMSIS NVIC_EncodePriority formula:
        #   PreemptPriorityBits = min(priority_bits, max(0, 7 - prigroup))
        preempt_bits = min(self.priority_bits, max(0, 7 - pg))
        return 1 << preempt_bits

    def num_sub_levels(self, prigroup: Optional[int] = None) -> int:
        """Number of sub-priority levels for a given PRIGROUP."""
        pg = prigroup if prigroup is not None else self.prigroup_default
        preempt_bits = min(self.priority_bits, max(0, 7 - pg))
        sub_bits = self.priority_bits - preempt_bits
        return 1 << sub_bits

    def irq_by_name(self, name: str) -> Optional[IRQSpec]:
        """Look up an IRQ by name or alias (case-insensitive)."""
        key = name.upper().strip()
        for irq in self.irqs:
            if irq.name.upper() == key:
                return irq
            if key in (a.upper() for a in irq.aliases):
                return irq
        return None

    def rt_irqs(self) -> List[IRQSpec]:
        """Return all IRQs classified as ``"RT"``."""
        return [i for i in self.irqs if i.rt_class == "RT"]

    def low_irqs(self) -> List[IRQSpec]:
        """Return all IRQs classified as ``"LOW"``."""
        return [i for i in self.irqs if i.rt_class == "LOW"]


# ──────────────────────────────────────────────────────────────────────────────
# Recommended priority bands  (guidance only — see docstring caveat)
# ──────────────────────────────────────────────────────────────────────────────

# For a 4-bit field (STM32F4xx) with the typical STM32 HAL default PRIGROUP=4:
#   Preempt bits = 3 → 8 preemption levels (0..7 in 3-bit space)
#   Sub bits     = 1 → 2 sub-priority levels
# With PRIGROUP=3 (all 4 bits = preemption) the full range 0..15 is available
# as independent preemption levels.
#
# The bands below use the raw 4-bit field value (0..15) regardless of PRIGROUP,
# so they apply with either default.

PRIORITY_BAND_RT_MAX    = 3   # 0..3  — real-time critical (e.g. TIM, EXTI)
PRIORITY_BAND_NORMAL_MAX = 8  # 4..8  — general peripherals (USART, SPI, I2C)
PRIORITY_BAND_LOW_MAX   = 15  # 9..15 — low-priority / background (USB, RTC)

RT_BAND     = range(0, PRIORITY_BAND_RT_MAX + 1)       # 0..3
NORMAL_BAND = range(PRIORITY_BAND_RT_MAX + 1, PRIORITY_BAND_NORMAL_MAX + 1)  # 4..8
LOW_BAND    = range(PRIORITY_BAND_NORMAL_MAX + 1, 16)  # 9..15


# ──────────────────────────────────────────────────────────────────────────────
# STM32F411 IRQ table  (RM0383 Rev 3 §10.1.2 Table 37)
# ──────────────────────────────────────────────────────────────────────────────
# Only the 62 maskable IRQs (positions 0–61) are listed.
# Cortex-M system exceptions (NMI, HardFault, MemManage, BusFault, UsageFault,
# SVCall, DebugMonitor, PendSV, SysTick) are not NVIC-configurable via priority
# registers and are therefore excluded from this verifier's scope.

_F411_IRQS: List[IRQSpec] = [
    # Position 0–10: system watchdog + interrupts
    IRQSpec(0,  "WWDG",       "NORMAL", ("WWDG_IRQn",)),
    IRQSpec(1,  "PVD",        "NORMAL", ("PVD_IRQn",)),
    IRQSpec(2,  "TAMP_STAMP", "LOW",    ("TAMP_STAMP_IRQn",)),
    IRQSpec(3,  "RTC_WKUP",   "LOW",    ("RTC_WKUP_IRQn", "RTC")),
    IRQSpec(4,  "FLASH",      "NORMAL", ("FLASH_IRQn",)),
    IRQSpec(5,  "RCC",        "NORMAL", ("RCC_IRQn",)),
    # EXTI lines — typically real-time (encoder inputs, buttons, safety signals)
    IRQSpec(6,  "EXTI0",      "RT",     ("EXTI0_IRQn",)),
    IRQSpec(7,  "EXTI1",      "RT",     ("EXTI1_IRQn",)),
    IRQSpec(8,  "EXTI2",      "RT",     ("EXTI2_IRQn",)),
    IRQSpec(9,  "EXTI3",      "RT",     ("EXTI3_IRQn",)),
    IRQSpec(10, "EXTI4",      "RT",     ("EXTI4_IRQn",)),
    # DMA1 streams
    IRQSpec(11, "DMA1_STREAM0", "NORMAL", ("DMA1_Stream0_IRQn", "DMA1_S0")),
    IRQSpec(12, "DMA1_STREAM1", "NORMAL", ("DMA1_Stream1_IRQn", "DMA1_S1")),
    IRQSpec(13, "DMA1_STREAM2", "NORMAL", ("DMA1_Stream2_IRQn", "DMA1_S2")),
    IRQSpec(14, "DMA1_STREAM3", "NORMAL", ("DMA1_Stream3_IRQn", "DMA1_S3")),
    IRQSpec(15, "DMA1_STREAM4", "NORMAL", ("DMA1_Stream4_IRQn", "DMA1_S4")),
    IRQSpec(16, "DMA1_STREAM5", "NORMAL", ("DMA1_Stream5_IRQn", "DMA1_S5")),
    IRQSpec(17, "DMA1_STREAM6", "NORMAL", ("DMA1_Stream6_IRQn", "DMA1_S6")),
    # ADC — low priority (polled or background)
    IRQSpec(18, "ADC",        "LOW",    ("ADC_IRQn", "ADC1", "ADC1_2", "ADC1_2_3")),
    # Position 19–22: reserved on STM32F411 (CAN not present)
    # EXTI9_5 — may carry RT signals (rotary encoder, etc.)
    IRQSpec(23, "EXTI9_5",    "RT",     ("EXTI9_5_IRQn",)),
    # Timers — motor control / PWM generation: RT
    IRQSpec(24, "TIM1_BRK_TIM9",  "RT", ("TIM1_BRK_TIM9_IRQn", "TIM1_BRK", "TIM9")),
    IRQSpec(25, "TIM1_UP_TIM10",  "RT", ("TIM1_UP_TIM10_IRQn", "TIM1_UP", "TIM10")),
    IRQSpec(26, "TIM1_TRG_COM_TIM11", "RT",
            ("TIM1_TRG_COM_TIM11_IRQn", "TIM1_TRG", "TIM1_COM", "TIM11")),
    IRQSpec(27, "TIM1_CC",    "RT",     ("TIM1_CC_IRQn",)),
    IRQSpec(28, "TIM2",       "RT",     ("TIM2_IRQn",)),
    IRQSpec(29, "TIM3",       "RT",     ("TIM3_IRQn",)),
    IRQSpec(30, "TIM4",       "RT",     ("TIM4_IRQn",)),
    # I2C
    IRQSpec(31, "I2C1_EV",    "NORMAL", ("I2C1_EV_IRQn",)),
    IRQSpec(32, "I2C1_ER",    "NORMAL", ("I2C1_ER_IRQn",)),
    IRQSpec(33, "I2C2_EV",    "NORMAL", ("I2C2_EV_IRQn",)),
    IRQSpec(34, "I2C2_ER",    "NORMAL", ("I2C2_ER_IRQn",)),
    # SPI
    IRQSpec(35, "SPI1",       "NORMAL", ("SPI1_IRQn",)),
    IRQSpec(36, "SPI2",       "NORMAL", ("SPI2_IRQn",)),
    # USART
    IRQSpec(37, "USART1",     "NORMAL", ("USART1_IRQn",)),
    IRQSpec(38, "USART2",     "NORMAL", ("USART2_IRQn",)),
    # Position 39: reserved on STM32F411 (USART3 not present)
    # EXTI15_10 — may carry RT signals
    IRQSpec(40, "EXTI15_10",  "RT",     ("EXTI15_10_IRQn",)),
    # RTC alarm
    IRQSpec(41, "RTC_ALARM",  "LOW",    ("RTC_Alarm_IRQn", "RTC_ALARM_IRQn")),
    # USB FS wakeup
    IRQSpec(42, "OTG_FS_WKUP", "LOW",  ("OTG_FS_WKUP_IRQn",)),
    # Positions 43–46: reserved on STM32F411 (TIM8 not present)
    # DMA1 stream 7
    IRQSpec(47, "DMA1_STREAM7", "NORMAL", ("DMA1_Stream7_IRQn", "DMA1_S7")),
    # Position 48: reserved on STM32F411 (FSMC not present)
    # SDIO
    IRQSpec(49, "SDIO",       "NORMAL", ("SDIO_IRQn",)),
    # TIM5 — general-purpose timer
    IRQSpec(50, "TIM5",       "RT",     ("TIM5_IRQn",)),
    # SPI3
    IRQSpec(51, "SPI3",       "NORMAL", ("SPI3_IRQn",)),
    # Positions 52–55: reserved on STM32F411 (UART4/5, TIM6/7 not present)
    # DMA2 streams
    IRQSpec(56, "DMA2_STREAM0", "NORMAL", ("DMA2_Stream0_IRQn", "DMA2_S0")),
    IRQSpec(57, "DMA2_STREAM1", "NORMAL", ("DMA2_Stream1_IRQn", "DMA2_S1")),
    IRQSpec(58, "DMA2_STREAM2", "NORMAL", ("DMA2_Stream2_IRQn", "DMA2_S2")),
    IRQSpec(59, "DMA2_STREAM3", "NORMAL", ("DMA2_Stream3_IRQn", "DMA2_S3")),
    IRQSpec(60, "DMA2_STREAM4", "NORMAL", ("DMA2_Stream4_IRQn", "DMA2_S4")),
    # Positions 61–62: reserved on STM32F411 (ETH not present)
    # USB OTG FS — low priority (USB enumeration + bulk transfers)
    IRQSpec(67, "OTG_FS",     "LOW",    ("OTG_FS_IRQn", "USB_OTG_FS", "USB")),
    # DMA2 streams 5–7
    IRQSpec(68, "DMA2_STREAM5", "NORMAL", ("DMA2_Stream5_IRQn", "DMA2_S5")),
    IRQSpec(69, "DMA2_STREAM6", "NORMAL", ("DMA2_Stream6_IRQn", "DMA2_S6")),
    IRQSpec(70, "DMA2_STREAM7", "NORMAL", ("DMA2_Stream7_IRQn", "DMA2_S7")),
    # USART6
    IRQSpec(71, "USART6",     "NORMAL", ("USART6_IRQn",)),
    # I2C3
    IRQSpec(72, "I2C3_EV",    "NORMAL", ("I2C3_EV_IRQn",)),
    IRQSpec(73, "I2C3_ER",    "NORMAL", ("I2C3_ER_IRQn",)),
    # Positions 74–77: reserved on STM32F411 (OTG_HS, ETH not present)
    # RNG — low priority (software-driven)
    IRQSpec(80, "RNG",        "LOW",    ("RNG_IRQn", "HASH_RNG")),
    # FPU
    IRQSpec(81, "FPU",        "NORMAL", ("FPU_IRQn",)),
    # SPI4/5 (STM32F411 only)
    IRQSpec(84, "SPI4",       "NORMAL", ("SPI4_IRQn",)),
    IRQSpec(85, "SPI5",       "NORMAL", ("SPI5_IRQn",)),
]


# ──────────────────────────────────────────────────────────────────────────────
# STM32F407 IRQ table  (RM0090 Rev 19 §10.1.2 Table 62)
# ──────────────────────────────────────────────────────────────────────────────
# STM32F407 has a superset of F411 IRQs (Ethernet, CAN, DCMI, TIM8, etc.)

_F407_IRQS: List[IRQSpec] = [
    IRQSpec(0,  "WWDG",       "NORMAL", ("WWDG_IRQn",)),
    IRQSpec(1,  "PVD",        "NORMAL", ("PVD_IRQn",)),
    IRQSpec(2,  "TAMP_STAMP", "LOW",    ("TAMP_STAMP_IRQn",)),
    IRQSpec(3,  "RTC_WKUP",   "LOW",    ("RTC_WKUP_IRQn", "RTC")),
    IRQSpec(4,  "FLASH",      "NORMAL", ("FLASH_IRQn",)),
    IRQSpec(5,  "RCC",        "NORMAL", ("RCC_IRQn",)),
    IRQSpec(6,  "EXTI0",      "RT",     ("EXTI0_IRQn",)),
    IRQSpec(7,  "EXTI1",      "RT",     ("EXTI1_IRQn",)),
    IRQSpec(8,  "EXTI2",      "RT",     ("EXTI2_IRQn",)),
    IRQSpec(9,  "EXTI3",      "RT",     ("EXTI3_IRQn",)),
    IRQSpec(10, "EXTI4",      "RT",     ("EXTI4_IRQn",)),
    IRQSpec(11, "DMA1_STREAM0", "NORMAL", ("DMA1_Stream0_IRQn", "DMA1_S0")),
    IRQSpec(12, "DMA1_STREAM1", "NORMAL", ("DMA1_Stream1_IRQn", "DMA1_S1")),
    IRQSpec(13, "DMA1_STREAM2", "NORMAL", ("DMA1_Stream2_IRQn", "DMA1_S2")),
    IRQSpec(14, "DMA1_STREAM3", "NORMAL", ("DMA1_Stream3_IRQn", "DMA1_S3")),
    IRQSpec(15, "DMA1_STREAM4", "NORMAL", ("DMA1_Stream4_IRQn", "DMA1_S4")),
    IRQSpec(16, "DMA1_STREAM5", "NORMAL", ("DMA1_Stream5_IRQn", "DMA1_S5")),
    IRQSpec(17, "DMA1_STREAM6", "NORMAL", ("DMA1_Stream6_IRQn", "DMA1_S6")),
    IRQSpec(18, "ADC",        "LOW",    ("ADC_IRQn", "ADC1", "ADC1_2_3")),
    # CAN (not present on F411)
    IRQSpec(19, "CAN1_TX",    "NORMAL", ("CAN1_TX_IRQn",)),
    IRQSpec(20, "CAN1_RX0",   "NORMAL", ("CAN1_RX0_IRQn",)),
    IRQSpec(21, "CAN1_RX1",   "NORMAL", ("CAN1_RX1_IRQn",)),
    IRQSpec(22, "CAN1_SCE",   "NORMAL", ("CAN1_SCE_IRQn",)),
    IRQSpec(23, "EXTI9_5",    "RT",     ("EXTI9_5_IRQn",)),
    IRQSpec(24, "TIM1_BRK_TIM9",  "RT", ("TIM1_BRK_TIM9_IRQn", "TIM9")),
    IRQSpec(25, "TIM1_UP_TIM10",  "RT", ("TIM1_UP_TIM10_IRQn", "TIM10")),
    IRQSpec(26, "TIM1_TRG_COM_TIM11", "RT", ("TIM1_TRG_COM_TIM11_IRQn", "TIM11")),
    IRQSpec(27, "TIM1_CC",    "RT",     ("TIM1_CC_IRQn",)),
    IRQSpec(28, "TIM2",       "RT",     ("TIM2_IRQn",)),
    IRQSpec(29, "TIM3",       "RT",     ("TIM3_IRQn",)),
    IRQSpec(30, "TIM4",       "RT",     ("TIM4_IRQn",)),
    IRQSpec(31, "I2C1_EV",    "NORMAL", ("I2C1_EV_IRQn",)),
    IRQSpec(32, "I2C1_ER",    "NORMAL", ("I2C1_ER_IRQn",)),
    IRQSpec(33, "I2C2_EV",    "NORMAL", ("I2C2_EV_IRQn",)),
    IRQSpec(34, "I2C2_ER",    "NORMAL", ("I2C2_ER_IRQn",)),
    IRQSpec(35, "SPI1",       "NORMAL", ("SPI1_IRQn",)),
    IRQSpec(36, "SPI2",       "NORMAL", ("SPI2_IRQn",)),
    IRQSpec(37, "USART1",     "NORMAL", ("USART1_IRQn",)),
    IRQSpec(38, "USART2",     "NORMAL", ("USART2_IRQn",)),
    IRQSpec(39, "USART3",     "NORMAL", ("USART3_IRQn",)),
    IRQSpec(40, "EXTI15_10",  "RT",     ("EXTI15_10_IRQn",)),
    IRQSpec(41, "RTC_ALARM",  "LOW",    ("RTC_Alarm_IRQn",)),
    IRQSpec(42, "OTG_FS_WKUP", "LOW",  ("OTG_FS_WKUP_IRQn",)),
    IRQSpec(43, "TIM8_BRK_TIM12", "RT", ("TIM8_BRK_TIM12_IRQn", "TIM12")),
    IRQSpec(44, "TIM8_UP_TIM13",  "RT", ("TIM8_UP_TIM13_IRQn", "TIM13")),
    IRQSpec(45, "TIM8_TRG_COM_TIM14", "RT", ("TIM8_TRG_COM_TIM14_IRQn", "TIM14")),
    IRQSpec(46, "TIM8_CC",    "RT",     ("TIM8_CC_IRQn",)),
    IRQSpec(47, "DMA1_STREAM7", "NORMAL", ("DMA1_Stream7_IRQn", "DMA1_S7")),
    IRQSpec(48, "FSMC",       "LOW",    ("FSMC_IRQn",)),
    IRQSpec(49, "SDIO",       "NORMAL", ("SDIO_IRQn",)),
    IRQSpec(50, "TIM5",       "RT",     ("TIM5_IRQn",)),
    IRQSpec(51, "SPI3",       "NORMAL", ("SPI3_IRQn",)),
    IRQSpec(52, "UART4",      "NORMAL", ("UART4_IRQn",)),
    IRQSpec(53, "UART5",      "NORMAL", ("UART5_IRQn",)),
    IRQSpec(54, "TIM6_DAC",   "RT",     ("TIM6_DAC_IRQn", "TIM6", "DAC")),
    IRQSpec(55, "TIM7",       "RT",     ("TIM7_IRQn",)),
    IRQSpec(56, "DMA2_STREAM0", "NORMAL", ("DMA2_Stream0_IRQn", "DMA2_S0")),
    IRQSpec(57, "DMA2_STREAM1", "NORMAL", ("DMA2_Stream1_IRQn", "DMA2_S1")),
    IRQSpec(58, "DMA2_STREAM2", "NORMAL", ("DMA2_Stream2_IRQn", "DMA2_S2")),
    IRQSpec(59, "DMA2_STREAM3", "NORMAL", ("DMA2_Stream3_IRQn", "DMA2_S3")),
    IRQSpec(60, "DMA2_STREAM4", "NORMAL", ("DMA2_Stream4_IRQn", "DMA2_S4")),
    IRQSpec(61, "ETH",        "NORMAL", ("ETH_IRQn",)),
    IRQSpec(62, "ETH_WKUP",   "LOW",    ("ETH_WKUP_IRQn",)),
    IRQSpec(63, "CAN2_TX",    "NORMAL", ("CAN2_TX_IRQn",)),
    IRQSpec(64, "CAN2_RX0",   "NORMAL", ("CAN2_RX0_IRQn",)),
    IRQSpec(65, "CAN2_RX1",   "NORMAL", ("CAN2_RX1_IRQn",)),
    IRQSpec(66, "CAN2_SCE",   "NORMAL", ("CAN2_SCE_IRQn",)),
    IRQSpec(67, "OTG_FS",     "LOW",    ("OTG_FS_IRQn", "USB")),
    IRQSpec(68, "DMA2_STREAM5", "NORMAL", ("DMA2_Stream5_IRQn", "DMA2_S5")),
    IRQSpec(69, "DMA2_STREAM6", "NORMAL", ("DMA2_Stream6_IRQn", "DMA2_S6")),
    IRQSpec(70, "DMA2_STREAM7", "NORMAL", ("DMA2_Stream7_IRQn", "DMA2_S7")),
    IRQSpec(71, "USART6",     "NORMAL", ("USART6_IRQn",)),
    IRQSpec(72, "I2C3_EV",    "NORMAL", ("I2C3_EV_IRQn",)),
    IRQSpec(73, "I2C3_ER",    "NORMAL", ("I2C3_ER_IRQn",)),
    IRQSpec(74, "OTG_HS_EP1_OUT", "LOW", ("OTG_HS_EP1_OUT_IRQn",)),
    IRQSpec(75, "OTG_HS_EP1_IN",  "LOW", ("OTG_HS_EP1_IN_IRQn",)),
    IRQSpec(76, "OTG_HS_WKUP",    "LOW", ("OTG_HS_WKUP_IRQn",)),
    IRQSpec(77, "OTG_HS",    "LOW",    ("OTG_HS_IRQn",)),
    IRQSpec(78, "DCMI",       "NORMAL", ("DCMI_IRQn",)),
    IRQSpec(80, "RNG",        "LOW",    ("RNG_IRQn", "HASH_RNG")),
    IRQSpec(81, "FPU",        "NORMAL", ("FPU_IRQn",)),
]


# ──────────────────────────────────────────────────────────────────────────────
# Instantiated specs
# ──────────────────────────────────────────────────────────────────────────────

STM32F411_IRQ = InterruptSpec(
    chip_id="STM32F411",
    priority_bits=4,
    prigroup_default=4,  # HAL default: 3 preempt bits + 1 sub bit
    irqs=_F411_IRQS,
    aliases=["stm32f411ce", "stm32f411re", "stm32f411ve", "stm32f411"],
)

STM32F407_IRQ = InterruptSpec(
    chip_id="STM32F407",
    priority_bits=4,
    prigroup_default=4,
    irqs=_F407_IRQS,
    aliases=["stm32f407vg", "stm32f407ig", "stm32f407ze", "stm32f407"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, InterruptSpec] = {
    spec.chip_id: spec
    for spec in [STM32F411_IRQ, STM32F407_IRQ]
}

# Populate aliases
for _spec in list(_REGISTRY.values()):
    for _alias in _spec.aliases:
        _REGISTRY[_alias.upper()] = _spec


def get_interrupt_spec(chip: str) -> InterruptSpec:
    """Return the :class:`InterruptSpec` for *chip*, resolving aliases.

    Parameters
    ----------
    chip:
        Chip string, e.g. ``"STM32F411"``, ``"stm32f411re"``, ``"STM32F407"``.
        Case-insensitive.

    Raises
    ------
    KeyError
        If the chip is not in the registry.
    """
    key = chip.upper().strip()
    if key not in _REGISTRY:
        raise KeyError(
            f"Unknown chip {chip!r}. "
            f"Known chips: {sorted(set(s.chip_id for s in _REGISTRY.values()))}."
        )
    return _REGISTRY[key]


def list_interrupt_chip_ids() -> List[str]:
    """Return the canonical chip IDs in the interrupt registry."""
    return sorted({s.chip_id for s in _REGISTRY.values()})
