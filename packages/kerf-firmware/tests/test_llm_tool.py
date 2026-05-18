"""Tests for kerf_firmware.llm_tool.make_arduino_sketch."""
from __future__ import annotations

import re

import pytest

from kerf_firmware.llm_tool import make_arduino_sketch


# ── helpers ────────────────────────────────────────────────────────────────────

def _assert_valid_sketch(result: dict) -> str:
    """Assert the result has a valid sketch and return the sketch text."""
    assert "sketch" in result, f"No 'sketch' key; got: {result}"
    assert "manifest" in result, f"No 'manifest' key; got: {result}"
    sketch: str = result["sketch"]
    assert "void setup()" in sketch, "sketch missing void setup()"
    assert "void loop()" in sketch, "sketch missing void loop()"
    return sketch


def _lib_names(result: dict) -> list[str]:
    return [lib["name"] for lib in result["manifest"].get("libraries", [])]


# ── pattern 1: blink ──────────────────────────────────────────────────────────

def test_blink_basic():
    result = make_arduino_sketch("blink LED on pin 13")
    sketch = _assert_valid_sketch(result)
    assert "13" in sketch


def test_blink_extracts_custom_pin():
    result = make_arduino_sketch("blink LED on pin 7")
    sketch = _assert_valid_sketch(result)
    assert "7" in sketch


def test_blink_manifest_board():
    result = make_arduino_sketch("blink LED")
    assert result["manifest"]["board"] == "arduino-uno-r3"


def test_blink_no_external_libraries():
    result = make_arduino_sketch("blink LED on pin 13")
    assert _lib_names(result) == []


# ── pattern 2: dht22 ─────────────────────────────────────────────────────────

def test_dht22_basic():
    result = make_arduino_sketch("read DHT22 temperature sensor on pin 4")
    sketch = _assert_valid_sketch(result)
    assert "DHT" in sketch


def test_dht22_includes_header():
    result = make_arduino_sketch("read dht22 sensor")
    sketch = _assert_valid_sketch(result)
    assert "#include" in sketch
    assert "DHT" in sketch


def test_dht22_library_dependency():
    result = make_arduino_sketch("read DHT22 temperature sensor on pin 2")
    lib_names = _lib_names(result)
    assert any("DHT" in n for n in lib_names), f"No DHT lib in {lib_names}"


def test_dht22_monitor_speed():
    result = make_arduino_sketch("DHT22 sensor on pin 3")
    assert result["manifest"]["monitor_speed"] > 0


# ── pattern 3: servo ─────────────────────────────────────────────────────────

def test_servo_basic():
    result = make_arduino_sketch("control servo with potentiometer")
    sketch = _assert_valid_sketch(result)
    assert "Servo" in sketch


def test_servo_includes_servo_lib():
    result = make_arduino_sketch("servo with pot")
    sketch = _assert_valid_sketch(result)
    assert "#include <Servo.h>" in sketch


def test_servo_library_dependency():
    result = make_arduino_sketch("control servo with potentiometer")
    lib_names = _lib_names(result)
    assert any("Servo" in n for n in lib_names), f"No Servo lib in {lib_names}"


def test_servo_uses_map():
    result = make_arduino_sketch("servo with potentiometer")
    sketch = _assert_valid_sketch(result)
    assert "map(" in sketch


# ── pattern 4: accelerometer ──────────────────────────────────────────────────

def test_accelerometer_basic():
    result = make_arduino_sketch("log accelerometer over serial")
    sketch = _assert_valid_sketch(result)
    assert "MPU6050" in sketch or "mpu" in sketch.lower()


def test_accelerometer_serial_output():
    result = make_arduino_sketch("accelerometer over serial")
    sketch = _assert_valid_sketch(result)
    assert "Serial" in sketch


def test_accelerometer_library_dependency():
    result = make_arduino_sketch("log accelerometer over serial")
    lib_names = _lib_names(result)
    assert any("MPU6050" in n for n in lib_names), f"No MPU6050 lib in {lib_names}"


def test_accelerometer_monitor_speed_115200():
    result = make_arduino_sketch("accelerometer logger")
    assert result["manifest"]["monitor_speed"] == 115200


# ── pattern 5: PWM motor ─────────────────────────────────────────────────────

def test_pwm_motor_basic():
    result = make_arduino_sketch("PWM motor speed from analog input")
    sketch = _assert_valid_sketch(result)
    assert "analogWrite" in sketch


def test_pwm_motor_analog_read():
    result = make_arduino_sketch("motor speed from analog input")
    sketch = _assert_valid_sketch(result)
    assert "analogRead" in sketch


def test_pwm_motor_map_call():
    result = make_arduino_sketch("PWM motor speed from analog input")
    sketch = _assert_valid_sketch(result)
    assert "map(" in sketch


def test_pwm_motor_no_libraries():
    result = make_arduino_sketch("PWM motor speed from analog input")
    assert _lib_names(result) == []


# ── manifest schema compliance ────────────────────────────────────────────────

@pytest.mark.parametrize("spec", [
    "blink LED on pin 13",
    "read DHT22 temperature sensor on pin 2",
    "control servo with potentiometer",
    "log accelerometer over serial",
    "PWM motor speed from analog input",
])
def test_manifest_schema_fields(spec: str):
    result = make_arduino_sketch(spec)
    assert "manifest" in result
    m = result["manifest"]
    assert "name" in m
    assert "board" in m
    assert isinstance(m["libraries"], list)
    assert isinstance(m["sources"], list)
    assert isinstance(m["build_flags"], list)
    assert isinstance(m["monitor_speed"], int)


@pytest.mark.parametrize("spec", [
    "blink LED on pin 13",
    "read DHT22 temperature sensor on pin 2",
    "control servo with potentiometer",
    "log accelerometer over serial",
    "PWM motor speed from analog input",
])
def test_all_5_patterns_produce_valid_sketch(spec: str):
    result = make_arduino_sketch(spec)
    _assert_valid_sketch(result)


# ── unknown spec ──────────────────────────────────────────────────────────────

def test_unknown_spec_returns_error():
    result = make_arduino_sketch("synthesise a quantum computer")
    assert "error" in result
    assert "spec" in result
    assert "sketch" not in result


def test_unknown_spec_preserves_original():
    spec = "do something completely unknown"
    result = make_arduino_sketch(spec)
    assert result["spec"] == spec


def test_unknown_spec_error_message_mentions_patterns():
    result = make_arduino_sketch("unknown spec xyz")
    error = result["error"]
    assert "blink" in error.lower() or "DHT22" in error or "servo" in error.lower()
