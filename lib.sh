# $1: name of build.json artifact
get_git_describe() {
    build_json="${1}"

    builds_count=$(jq -r '.builds | length' "${build_json}" 2>/dev/null)

    if [ "${builds_count}" -eq 0 ]; then
        retval=$(jq -r '.git_describe' "${build_json}")
    else
        retval=$(jq -r '.builds[].git_describe' "${build_json}" | head -n1)
    fi

    echo "${retval}"
}
