# Op-Amp Board

LM358 non-inverting amplifier with DC sweep analysis.

## Files

- `main.circuit.tsx` — tscircuit: LM358, 2 resistors (10k each), 100nF decoupling cap, 10µF bulk cap, VIN/VOUT/GND pads
- `amp.simulation` — DC sweep -5V to +5V on VIN with VOUT and I_R2 probes

## Circuit

- Non-inverting amplifier gain = 1 + R2/R1 = 2
- VIN → R1 → R2 → U1 pin 1 (inverting input)
- U1 pin 3 (non-inverting) = VIN
- 100nF cap on VCC (pin 8) for high-frequency decoupling
- 10µF bulk cap on VCC/VEE for low-frequency filtering

## Analysis

DC sweep on VIN (-5V to +5V) with probes on VOUT and current through R2.