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
// `kicad-to-circuit-json` is a devDependency of the frontend (web/package.json),
// not of this repo-root `scripts/` helper — the frontend restructure (moving
// package.json + node_modules into web/) means the bare specifier below no
// longer resolves via the normal node_modules walk-up from this file's
// location. Import the installed package directly by its real path instead
// of relying on a root-level node_modules that no longer exists.
const { KicadToCircuitJsonConverter } = await import(
  new URL("../web/node_modules/kicad-to-circuit-json/dist/index.js", import.meta.url)
);

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
