# I2S Protocol Primer

## Overview

I2S (Inter-IC Sound) is a serial bus interface standard for connecting digital audio devices developed
by Philips Semiconductor. It is designed specifically for audio data and is unrelated to I2C despite
the similar name. I2S is synchronous, full-duplex (with two separate channels), and uses a separate
word-select line to distinguish left and right audio channels.

## Signal Lines

| Pin | Direction | Description |
|-----|-----------|-------------|
| SCK / BCLK | Master → Slave | Bit Clock — one pulse per audio bit |
| WS / LRCK | Master → Slave | Word Select / Left-Right Clock — LOW = left channel, HIGH = right channel |
| SD / SDATA | Bidirectional | Serial Data — MSB first |
| MCLK | Optional | Master Clock — typically 256 × fs or 384 × fs |

## Frame Format

```
WS:   ‾‾‾‾‾‾‾‾╗________________╔‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾╗________
SCK:  ╚╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗_╔╗
SD:     L15 L14 ...              L0 R15 R14 ...      R0
```

- WS LOW = Left channel (I2S standard)
- WS HIGH = Right channel
- Data changes on falling edge of SCK, sampled on rising edge
- MSB transmitted first, one clock after WS transitions (I2S justified format)

## Data Justification Variants

| Variant | Description |
|---------|-------------|
| I2S (Philips) | MSB is on the 2nd SCK after WS edge |
| Left Justified | MSB is on the 1st SCK after WS edge |
| Right Justified | LSB aligned to end of WS phase |
| DSP/PCM Mode A | Short sync pulse, data immediately after |

## Sample Rates

Common audio sample rates: 8, 11.025, 16, 22.05, 32, 44.1, 48, 96, 192 kHz.

MCLK is typically 256 × fs. For 44.1 kHz audio: MCLK = 11.2896 MHz.

## Word Lengths

Supported word lengths: 8, 16, 20, 24, 32 bits (padded with zeros if shorter than the SCK frame).

## C Example (ESP32 IDF)

```c
#include "driver/i2s.h"

#define I2S_NUM         I2S_NUM_0
#define SAMPLE_RATE     44100
#define BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT

void i2s_init(int pin_bclk, int pin_lrck, int pin_dout, int pin_din) {
    i2s_config_t cfg = {
        .mode = I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX,
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = BITS_PER_SAMPLE,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 64,
        .use_apll = false,
        .tx_desc_auto_clear = true,
    };
    i2s_driver_install(I2S_NUM, &cfg, 0, NULL);

    i2s_pin_config_t pins = {
        .bck_io_num = pin_bclk,
        .ws_io_num = pin_lrck,
        .data_out_num = pin_dout,
        .data_in_num = pin_din,
    };
    i2s_set_pin(I2S_NUM, &pins);
}

/* Write PCM samples (interleaved L/R, 16-bit) */
void i2s_write_samples(const int16_t *samples, size_t count) {
    size_t bytes_written;
    i2s_write(I2S_NUM, samples, count * sizeof(int16_t), &bytes_written, portMAX_DELAY);
}
```

## Common Audio ICs Using I2S

| Device | Type |
|--------|------|
| MAX98357A | I2S DAC + class-D amplifier |
| PCM5102A | Hi-Fi stereo DAC |
| INMP441 | MEMS microphone |
| WM8960 | Audio codec (ADC + DAC) |
| SPH0645LM4H | MEMS microphone (PDM) |

## Common Pitfalls

1. **MCLK requirement** — Some codecs require MCLK; check if the MCU can generate the needed frequency.
2. **Justification mismatch** — Philips I2S and Left/Right Justified are NOT interchangeable; configure both master and slave to the same format.
3. **DMA buffer underrun** — Insufficient DMA buffers cause audio glitches; increase `dma_buf_count` and `dma_buf_len`.
4. **Clock accuracy** — Audio is sensitive to jitter; use APLL on ESP32 for better accuracy at 44.1/88.2 kHz rates.
5. **PDM vs I2S** — Some MEMS mics output PDM (Pulse Density Modulation), not I2S. PDM requires decimation filtering.

## See Also

- `drivers.md` — Kerf driver catalogue
- `spi.md` — SPI primer (also uses a clock + data structure)
