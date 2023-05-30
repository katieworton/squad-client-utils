#!/bin/bash

GROUP_NAME=$1
PROJECT_NAME=$2

if [ "$#" -ne 2 ]; then
    echo "usage: ./run-and-push-skipfile-results <group_name> <project_name>"
else
    rm builds_for_skipfile_runs.txt
    for PLAN in skipfile-reproducer*.yaml; do
        tuxsuite plan $PLAN --json-out $PLAN.json --no-wait
        BUILD="$PLAN-$(date +'%s')"
        squad-client submit-tuxsuite --group=$GROUP_NAME --project=$PROJECT_NAME --build=$BUILD --backend tuxsuite.com --json $PLAN.json
        echo $BUILD >>builds_for_skipfile_runs.txt
    done
fi
