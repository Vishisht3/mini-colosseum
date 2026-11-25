#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
dune build main.bc.js
cp _build/default/main.bc.js ../js/ocaml-ui.js
