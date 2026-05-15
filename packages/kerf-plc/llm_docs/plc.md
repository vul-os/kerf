# IEC 61131-3 Structured Text (`.plc.st`)

Structured Text (ST) is one of the five IEC 61131-3 programming languages for
Programmable Logic Controllers (PLCs). Its syntax is Pascal-shaped: block
delimiters like `END_IF`, `END_FOR`, `END_FUNCTION_BLOCK`, typed variable
declarations (`VAR … END_VAR`), and a rich set of built-in types.

Kerf uses [MATIEC](https://github.com/thiagoralves/OpenPLC_v3/tree/master/utils/matiec_src)
(GPLv3, invoked as a subprocess) to parse and lint `.plc.st` files offline.

---

## File kind

| Property | Value |
|---|---|
| Extension | `.plc.st` |
| Kind | `plc_st` |
| Editor | Monaco with `iec61131-st` custom language |
| Lint | MATIEC `iec2c` subprocess (graceful degradation when absent) |

---

## Language overview

### Program Organisation Units (POUs)

| POU | Keyword | Purpose |
|---|---|---|
| Function | `FUNCTION … END_FUNCTION` | Stateless, returns a value |
| Function Block | `FUNCTION_BLOCK … END_FUNCTION_BLOCK` | Stateful; instances hold memory |
| Program | `PROGRAM … END_PROGRAM` | Top-level scan cycle |

### Variable sections

```st
VAR                  (* local *)
VAR_INPUT            (* inputs — read-only inside the POU *)
VAR_OUTPUT           (* outputs — written inside the POU *)
VAR_IN_OUT           (* read-write by both caller and POU *)
VAR_GLOBAL           (* global scope *)
VAR_EXTERNAL         (* access global from POU *)
VAR_TEMP             (* temporary, not retained *)
END_VAR
```

### Data types

| Category | Types |
|---|---|
| Boolean | `BOOL` |
| Integer | `SINT`, `INT`, `DINT`, `LINT`, `USINT`, `UINT`, `UDINT`, `ULINT` |
| Real | `REAL`, `LREAL` |
| Time | `TIME`, `DATE`, `TIME_OF_DAY` (alias `TOD`), `DATE_AND_TIME` (alias `DT`) |
| String | `STRING`, `WSTRING` |
| Bit string | `BYTE`, `WORD`, `DWORD`, `LWORD` |

### Operators

```
AND  OR  XOR  NOT           (* boolean *)
+  -  *  /  MOD             (* arithmetic *)
=  <>  <  >  <=  >=         (* comparison *)
:=                           (* assignment *)
```

### Control flow

```st
(* IF / ELSIF / ELSE *)
IF condition THEN
  statements;
ELSIF other_condition THEN
  statements;
ELSE
  statements;
END_IF

(* CASE *)
CASE selector OF
  1: statement_a;
  2, 3: statement_b;
ELSE
  statement_default;
END_CASE

(* FOR loop *)
FOR i := 0 TO 9 BY 1 DO
  statements;
END_FOR

(* WHILE loop *)
WHILE condition DO
  statements;
END_WHILE

(* REPEAT … UNTIL *)
REPEAT
  statements;
UNTIL condition
END_REPEAT
```

### Standard function blocks (IEC 61131-3 stdlib)

| Name | Purpose |
|---|---|
| `TON` | On-delay timer |
| `TOF` | Off-delay timer |
| `TP` | Pulse timer |
| `SR` | Set-Reset flip-flop |
| `RS` | Reset-Set flip-flop |
| `CTU` | Up counter |
| `CTD` | Down counter |
| `CTUD` | Up/Down counter |
| `R_TRIG` | Rising-edge detector |
| `F_TRIG` | Falling-edge detector |

---

## Minimal example — START/STOP latch

The classic industrial latch: pressing START sets the motor output; pressing
STOP (or a fault) clears it.  This is the "hello world" of PLC programming.

```st
PROGRAM StartStopLatch

VAR_INPUT
  start_pb  : BOOL;  (* Start pushbutton — momentary, NO *)
  stop_pb   : BOOL;  (* Stop pushbutton  — momentary, NC (inverted) *)
  fault     : BOOL;  (* Overload / fault input *)
END_VAR

VAR_OUTPUT
  motor_run : BOOL;  (* Motor contactor coil *)
END_VAR

(* Latch logic:
   Set   when start_pb pressed AND no fault AND stop not pressed.
   Reset when stop_pb pressed OR fault active. *)

IF (start_pb AND NOT stop_pb AND NOT fault) THEN
  motor_run := TRUE;
END_IF

IF (stop_pb OR fault) THEN
  motor_run := FALSE;
END_IF

END_PROGRAM
```

---

## Lint tool

### `run_plc_lint`

Lint a `.plc.st` source string via MATIEC.

```json
{
  "source": "PROGRAM MyPLC\n...\nEND_PROGRAM"
}
```

Returns:
```json
{
  "diagnostics": [
    { "severity": "error", "message": "...", "line": 5, "column": 3, "source": "matiec" }
  ],
  "warnings": []
}
```

- `diagnostics` — structured per-location issues for Monaco marker layer.
- `warnings` — top-level informational messages (e.g. "MATIEC not installed").
- When MATIEC is absent, `diagnostics` is empty and `warnings` contains one
  advisory; **no exception is raised**.

---

## MATIEC install

```bash
# Debian / Ubuntu
apt install matiec

# Build from source
git clone https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3/utils/matiec_src
make
sudo cp iec2c /usr/local/bin/
```

The plugin resolves the binary via `shutil.which("iec2c")`.  Timeout defaults
to 5 s; override with `MATIEC_TIMEOUT` env var.

---

## Licensing note

MATIEC is **GPLv3**. Kerf invokes it as a separate subprocess — there is no
in-process linking. This subprocess boundary keeps the hosted service and local
install MIT-licensed. See `packages/kerf-plc/README.md` for details.
