#!/usr/bin/env node
// kicad_oracle_convert.mjs — CI conformance oracle helper for T-526b.
//
// Runs the independent `kicad-to-circuit-json` converter (MIT, tscircuit)
// over a .kicad_pcb file and prints the resulting Circuit JSON array to
// stdout. This exists so packages/kerf-electronics/tests/test_kicad_oracle.py
// can diff kerf's own kicad_io.py reader against a genuinely independent
// implementation, rather than only checking against hand-authored fixtures.
//
// Deliberately a thin, dumb wrapper: all interpretation/normalization of the
// output happens on the Python side of the test. This script's only jobs are
// (1) invoke the converter and (2) fail loudly (non-zero exit + stderr) if
// anything goes wrong, so the calling test never mistakes a broken oracle
// for a passing one.

import { readFileSync } from "node:fs";
import { KicadToCircuitJsonConverter } from "kicad-to-circuit-json";

const inputPath = process.argv[2];
if (!inputPath) {
  console.error("usage: kicad_oracle_convert.mjs <path-to.kicad_pcb>");
  process.exit(2);
}

let content;
try {
  content = readFileSync(inputPath, "utf8");
} catch (err) {
  console.error(`kicad_oracle_convert: could not read ${inputPath}: ${err.message}`);
  process.exit(2);
}

try {
  const converter = new KicadToCircuitJsonConverter();
  converter.addFile("board.kicad_pcb", content);
  converter.runUntilFinished();
  const output = converter.getOutput();
  process.stdout.write(JSON.stringify(output));
} catch (err) {
  console.error(`kicad_oracle_convert: conversion failed: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
}
