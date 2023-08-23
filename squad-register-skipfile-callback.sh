#!/bin/bash

export QA_PROJECT="skipfile-testing"
export QA_PROJECT_NAME="Skipfile testing"
export QA_SERVER="https://qa-reports.linaro.org/"

echo "QA_SERVER: ${QA_SERVER}"
echo "QA_PROJECT: ${QA_PROJECT}"
echo "QA_PROJECT_NAME: ${QA_PROJECT_NAME}"
test -n "${QA_PROJECT_NAME}" || export QA_PROJECT_NAME="${QA_PROJECT}"

SQUAD_PROJECT="${QA_PROJECT=}"
report_job_name="callback"

# Find report job
echo "Will do tests. Need to register QA callback."
curl -f --silent "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}/jobs?scope[]=manual" >jobs-manual.json
echo "$(<jobs-manual.json)"
job_id="$(jq -r ".[] | select(.name == \"callback\") | .id" jobs-manual.json)"
callback_url="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/jobs/${job_id}/play"
echo "Callback URL: [${callback_url}]"

echo "${BUILD_ID}"
# Register callback with SQUAD
if [ -z "${BUILD_ID}" ]; then
    source lib.sh
    BUILD_ID="$(get_git_describe build.json)"
fi
registration_url="${QA_SERVER}/api/builds?version=${BUILD_ID}&project__slug=${SQUAD_PROJECT}"
echo "Registration URL: ${registration_url}"
curl -f --silent -L "${registration_url}" -o qa_build.json
build_id="$(jq -r '.results[0].id' qa_build.json)"
curl --silent \
    -X POST "${QA_SERVER}/api/builds/${build_id}/callbacks/" \
    -H "Authorization: Token ${QA_REPORTS_TOKEN}" \
    -F "callback_url=${callback_url}" \
    -F "callback_record_response=true"
