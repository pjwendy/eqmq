#!/usr/bin/env bash
# Regenerate eqmq/proto/headless_pb2.py from the EQEmu fork's common/proto/headless.proto,
# using the protoc that vcpkg builds inside the akk-stack container.
set -euo pipefail

CONTAINER=${CONTAINER:-akk-stack-eqemu-server-1}
PROTOC=/home/eqemu/build/vcpkg_installed/x64-linux/tools/protobuf/protoc-29.5.0
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/eqmq/proto/headless_pb2.py"
# Git Bash: container paths must not be rewritten, so convert the local path ourselves
if command -v cygpath >/dev/null 2>&1; then OUT=$(cygpath -w "$OUT"); fi

export MSYS_NO_PATHCONV=1
docker exec "$CONTAINER" bash -c "mkdir -p /tmp/pygen && $PROTOC -I /home/eqemu/code/common/proto --python_out=/tmp/pygen /home/eqemu/code/common/proto/headless.proto"
docker cp "$CONTAINER:/tmp/pygen/headless_pb2.py" "$OUT"
echo "updated $OUT"
