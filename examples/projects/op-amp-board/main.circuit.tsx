import { Circuit } from "tscircuit"

export default (
  <board width="60mm" height="40mm">
    <chip
      name="U1"
      chipName="LM358"
      footprint="DIP-8"
      pcbX={15}
      pcbY={25}
      schX={0}
      schY={0}
    />
    <resistor name="R1" resistance="10k" footprint="0805" pcbX={35} pcbY={10} schX={5} schY={-3} />
    <resistor name="R2" resistance="10k" footprint="0805" pcbX={35} pcbY={18} schX={5} schY={0} />
    <capacitor name="C1" capacitance="100nF" footprint="0805" pcbX={15} pcbY={8} schX={0} schY={-3} />
    <capacitor name="C2" capacitance="10uF" footprint="0805" pcbX={15} pcbY={38} schX={0} schY={3} />
    <pad name="VIN" pcbX={5} pcbY={10} schX={-5} schY={-3} />
    <pad name="VOUT" pcbX={55} pcbY={25} schX={10} schY={0} />
    <pad name="GND" pcbX={30} pcbY={38} schX={5} schY={3} />
    <trace from=".U1 > .pin8" to=".VIN > .pin1" />
    <trace from=".R1 > .pin1" to=".VIN > .pin1" />
    <trace from=".R1 > .pin2" to=".R2 > .pin1" />
    <trace from=".R2 > .pin2" to=".U1 > .pin1" />
    <trace from=".U1 > .pin4" to="net.GND" />
    <trace from=".U1 > .pin3" to=".VIN > .pin1" />
    <trace from=".U1 > .pin1" to=".VOUT > .pin1" />
    <trace from=".C1 > .pin1" to=".U1 > .pin8" />
    <trace from=".C1 > .pin2" to="net.GND" />
    <trace from=".C2 > .pin1" to=".U1 > .pin4" />
    <trace from=".C2 > .pin2" to="net.GND" />
    <trace from=".GND > .pin1" to="net.GND" />
  </board>
)