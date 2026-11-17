#!/bin/bash
# Usage (Senzing SDK 4 tools image, truth set mounted at /data, output dir at /out):
#   docker run --rm -v EXPORT_DIR:/data:ro -v OUT_DIR:/out -v SCRIPTS:/work senzing/senzingsdk-tools:4.4.4 bash /work/check_senzing.sh
# Load the USORG-Bench Senzing truth set into a fresh SQLite Senzing repository, snapshot it,
# and audit the snapshot against the truth-set key with sz_audit.
set -e
mkdir -p /tmp/sqlite
export SENZING_ENGINE_CONFIGURATION_JSON='{"PIPELINE":{"CONFIGPATH":"/etc/opt/senzing","RESOURCEPATH":"/opt/senzing/er/resources","SUPPORTPATH":"/opt/senzing/data"},"SQL":{"CONNECTION":"sqlite3://na:na@/tmp/sqlite/G2C.db"}}'
SCHEMA=$(ls /opt/senzing/er/resources/schema/*sqlite*create*.sql | head -1)
echo "schema: $SCHEMA"
python3 - "$SCHEMA" <<'EOF'
import sqlite3, sys
con = sqlite3.connect("/tmp/sqlite/G2C.db")
con.executescript(open(sys.argv[1]).read())
con.commit()
EOF
sz_setup_config -a > /tmp/setup.log 2>&1 || { cat /tmp/setup.log; exit 1; }
python3 - <<'EOF'
import json, os
srcs = sorted({json.loads(l)["DATA_SOURCE"] for l in open("/data/usorgs.jsonl")})
with open("/tmp/ds.g2c", "w") as fh:
    for s in srcs:
        fh.write(f"addDataSource {s}\n")
    fh.write("save\n")
print("data sources:", srcs)
EOF
sz_configtool -f /tmp/ds.g2c > /tmp/configtool.log 2>&1 || { tail -20 /tmp/configtool.log; exit 1; }
python3 - <<'EOF'
import os
from senzing_core import SzAbstractFactoryCore
f = SzAbstractFactoryCore("usorg", os.environ["SENZING_ENGINE_CONFIGURATION_JSON"])
eng = f.create_engine()
n = 0
for line in open("/data/usorgs.jsonl"):
    import json
    r = json.loads(line)
    eng.add_record(r["DATA_SOURCE"], r["RECORD_ID"], line)
    n += 1
print("loaded", n)
EOF
cd /out
sz_snapshot -QAo snapshot > /tmp/snapshot.log 2>&1 || { tail -20 /tmp/snapshot.log; exit 1; }
ls /out
sz_audit -n snapshot.csv -p /data/usorgs_truthset_key.csv -o audit > /tmp/audit.log 2>&1 || { tail -30 /tmp/audit.log; exit 1; }
tail -40 /tmp/audit.log
ls /out
