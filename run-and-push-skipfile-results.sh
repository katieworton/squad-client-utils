#!/bin/bash

GROUP_NAME=$1
PROJECT_NAME=$2

if [ "$#" -ne 2 ]; then
    echo "usage: ./run-and-push-skipfile-results <group_name> <project_name>"
else

    run_list=builds_for_skipfile_runs.txt
    if test -f "$run_list"; then
        rm "$run_list"
    fi
    for PLAN in skipfile-reproducer*.yaml; do
        if test -f "$PLAN"; then
            echo "$PLAN"
            tuxsuite plan $PLAN --json-out $PLAN.json --no-wait
            export BUILD_ID="$PLAN-$(date +'%s')"
            squad-client submit-tuxsuite --group=$GROUP_NAME --project=$PROJECT_NAME --build=$BUILD_ID --backend tuxsuite.com --json $PLAN.json
            echo $BUILD_ID >>builds_for_skipfile_runs.txt
        fi
    done
fi
echo "build ${BUILD_ID}"
