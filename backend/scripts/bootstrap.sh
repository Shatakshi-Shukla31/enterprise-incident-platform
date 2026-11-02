#!/bin/sh
set -eu

alembic upgrade head

if [ ! -f "${ARTIFACTS_DIR}/sla_risk/LATEST" ]; then
    python -m app.ml.train
fi

python -m scripts.seed_demo
