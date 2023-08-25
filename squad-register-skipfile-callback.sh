#!/bin/bash

export QA_PROJECT="${QA_PROJECT//\//_}"
export QA_PROJECT_SANITY="${QA_PROJECT_SANITY//\//_}"
echo "QA_SERVER: ${QA_SERVER}"
echo "QA_PROJECT: ${QA_PROJECT}"
echo "QA_PROJECT_NAME: ${QA_PROJECT_NAME}"
echo "QA_PROJECT_SANITY: ${QA_PROJECT_SANITY}"
echo "QA_PROJECT_NAME_SANITY: ${QA_PROJECT_NAME_SANITY}"
test -n "${QA_PROJECT_NAME}" || export QA_PROJECT_NAME="${QA_PROJECT}"
test -n "${QA_PROJECT_NAME_SANITY}" || export QA_PROJECT_NAME="${QA_PROJECT_SANITY}"

SQUAD_PROJECT="${QA_PROJECT=}"
report_job_name=”${report_job_name:='report'}”
if [ "${CI_BUILD_STAGE}" = "sanity" ]; then
  SQUAD_PROJECT="${QA_PROJECT_SANITY}"
  report_job_name="report-sanity"
fi

# Find report job
echo "Will do tests. Need to register QA callback."
curl -f --silent "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}/jobs?scope[]=manual" > jobs-manual.json
job_id="$(jq -r ".[] | select(.name == \"${report_job_name}\") | .id" jobs-manual.json)"
callback_url="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/jobs/${job_id}/play"
echo "Callback URL: [${callback_url}]"

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
