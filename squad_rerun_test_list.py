#!/usr/bin/python3


import argparse
import logging
import os
import re
import sys
import requests
from pathlib import Path
from squad_client.core.api import SquadApi
from squad_client.core.models import Squad, Build, TestRun
from squad_client.shortcuts import download_tests as download
from squad_client.shortcuts import get_build
from squad_client.utils import getid, first

squad_host_url = "https://qa-reports.linaro.org/"
SquadApi.configure(cache=3600, url=os.getenv("SQUAD_HOST", squad_host_url))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_file(path):
    print(f"Getting file from {path}")
    if re.search(r"https?://", path):
        request = requests.get(path, allow_redirects=True)
        request.raise_for_status()
        filename = path.split("/")[-1]
        with open(filename, "wb") as f:
            f.write(request.content)
        return filename
    elif os.path.exists(path):
        return path
    else:
        raise Exception(f"Path {path} not found")


def find_good_build(
    base_build, project, environment, build_name, suite_name, test_name
):
    builds = project.builds(id__lt=base_build.id, ordering="-id", count=10).values()
    for build in builds:
        logger.debug(f'Trying to find good test in build "{build.version}"')
        for testrun in build.testruns(environment=environment.id).values():
            logger.debug(f"  - Trying to find {build_name} in {testrun.job_url}")
            if build_name == testrun.metadata.build_name:
                logger.debug(
                    f"    - Yay, found it, now looking for a passing {suite_name}/{test_name}"
                )
                candidate_test = first(
                    testrun.tests(metadata__suite=suite_name, metadata__name=test_name)
                )
                if candidate_test is None:
                    logger.debug(f"      - no test in here :(")
                    continue
                if candidate_test.result:
                    logger.debug("************** FOUND IT *************")
                    return build
    return None


def read_results(result_file):
    pass


def parse_args(raw_args):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--group",
        required=True,
        help="squad group",
    )

    parser.add_argument(
        "--project",
        required=True,
        help="squad project",
    )

    parser.add_argument(
        "--build",
        required=True,
        help="squad build",
    )
    parser.add_argument(
        "--test_type",
        required=False,
        default="ltp",
        help="Only ltp is currently supported",
    )

    parser.add_argument(
        "--build_name",
        required=True,
        help="the build name (for example, gcc-12-lkftconfig)",
    )

    parser.add_argument(
        "--device_name",
        required=True,
        help="the device name",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Display debug messages",
    )
    parser.add_argument(
        "--tests", required=True, help="List of tests to rerun", nargs="+"
    )
    parser.add_argument(
        "--rerun_name",
        required=False,
        default="rerun",
        help="Name for the group of reruns",
    )

    return parser.parse_args(raw_args)


def run(raw_args=None):
    args = parse_args(raw_args)
    if args.debug:
        logger.setLevel(level=logging.DEBUG)

    base_group = Squad().group(args.group)
    if base_group is None:
        logger.error(f"Get group failed. Group not found: '{args.group}'.")
        return -1

    base_project = base_group.project(args.project)
    if base_project is None:
        logger.error(f"Get project failed. project not found: '{args.project}'.")
        return -1

    base_build = get_build(args.build, base_project)
    if base_build is None:
        logger.error(f"Get build failed. build not found: '{args.build}'.")
        return -1

    device_name = args.device_name
    build_name = args.build_name
    test_type = args.test_type

    rerun_test_list = args.tests

    ltp_example_suite = "ltp-syscalls"
    metadata = first(Squad().suitemetadata(suite=ltp_example_suite, kind="test"))

    if metadata is None:
        print('There is no suite named "{suite_name}"')
        return -1

    environment = base_project.environment(device_name)
    if environment is None:
        print(f'There is no environment for "{device_name}"')
        return -1
    build = Build(base_build.id)
    test_options = build.tests(metadata=metadata.id, environment=environment.id)
    test = None
    for test_option in test_options.values():
        testrun = TestRun(getid(test_option.test_run))
        if testrun.metadata.build_name == build_name:
            test = test_option
            break

    if test is None:
        print(f'Build "{build.version}" has no test available on "{device_name}"')
        return -1

    # In theory there should only be one of those
    testrun = TestRun(getid(test.test_run))
    logger.debug(f"Testrun id {testrun.id}")
    download_url = testrun.metadata.download_url
    if download_url is None:
        if testrun.metadata.config is None:
            print("There is no way to determine download_url")
            return -1
        download_url = testrun.metadata.config.replace("config", "")

    # Write the retest script name to a file if it isn't already there
    retest_filename = (
        f"retest-{build_name}-{test_type}-{args.rerun_name}.sh"
    )
    retest_list_filename = "retest_list.sh"
    with open(retest_list_filename, "a+") as f:
        f.seek(0)
        retest_list = f.read()
        if retest_filename not in retest_list:
            f.write(retest_filename + "\n")
    for test_name in rerun_test_list:
        build_cmdline = ""
        results_file = f"results-{build.version}-{device_name}-{build_name}-{test_type}-{test_name}.json"
        tuxrun = get_file(f"{testrun.job_url}/reproducer")
        for line in Path(tuxrun).read_text(encoding="utf-8").split("\n").rstrip():
            if "tuxrun --runtime" in line:
                line = re.sub("--tests \S+ ", "", line)
                line = re.sub("--parameters SHARD_INDEX=\S+ ", "", line)
                line = re.sub("--parameters SHARD_NUMBER=\S+ ", "", line)
                line = re.sub("--parameters SKIPFILE=\S+ ", "", line)
                line = re.sub(f"{ltp_example_suite}=\S+", "--timeouts command=5", line)
                build_cmdline = os.path.join(
                    build_cmdline
                    + line.strip()
                    + f' --save-outputs --results {results_file} --log-file -"'
                ).strip()

        build_cmdline = build_cmdline.replace(
            '-"', f"- -- 'cd /opt/ltp && ./runltp -s {test_name}'"
        )

        if Path(retest_filename).exists():
            bisect_script_append = f"""
    {build_cmdline}
    """
            f = Path(retest_filename).open("a")
            f.write(bisect_script_append)
            f.close()
            print(f"{build_cmdline}")
            print(f"file appended: {retest_filename}")

        else:
            bisect_script = f"""#!/bin/bash
    {build_cmdline}
    """
            Path(retest_filename).write_text(bisect_script, encoding="utf-8")

            print(f"{bisect_script}")
            print(f"file created: {retest_filename}")


if __name__ == "__main__":
    sys.exit(run())
