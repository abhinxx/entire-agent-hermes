#!/usr/bin/env bash
# Install entire-agent-hermes: protocol binary + Hermes plugin.
set -euo pipefail
cd "$(dirname "$0")"

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
PLUGINS_DIR="${PLUGINS_DIR:-${HERMES_HOME:-$HOME/.hermes}/plugins}"

chmod +x bin/entire-agent-hermes
mkdir -p "$BIN_DIR" "$PLUGINS_DIR"
cp bin/entire-agent-hermes "$BIN_DIR/entire-agent-hermes"
rm -rf "$PLUGINS_DIR/hermes-entire-bridge"
cp -r plugin/hermes-entire-bridge "$PLUGINS_DIR/hermes-entire-bridge"

echo "Installed:"
echo "  $BIN_DIR/entire-agent-hermes"
echo "  $PLUGINS_DIR/hermes-entire-bridge"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your \$PATH; the Entire CLI will not discover the binary."; ;;
esac
echo
echo "Next steps:"
echo "  1. restart Hermes (plugins load at start)"
echo "  2. in each repo: entire enable --agent hermes --telemetry=false"
echo "  3. work through Hermes, then: entire checkpoint list"
