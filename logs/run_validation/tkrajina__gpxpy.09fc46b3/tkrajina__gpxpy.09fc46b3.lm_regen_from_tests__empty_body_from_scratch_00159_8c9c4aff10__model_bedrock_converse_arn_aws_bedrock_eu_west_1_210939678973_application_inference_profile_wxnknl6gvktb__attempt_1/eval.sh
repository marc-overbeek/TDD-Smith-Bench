#!/bin/bash
set -uxo pipefail
cd /testbed
: '>>>>> Start Test Output'
source /opt/miniconda3/bin/activate; conda activate testbed; pytest test.py --verbose --color=no --tb=no --disable-warnings
: '>>>>> End Test Output'
