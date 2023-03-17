#!/usr/bin/python3


import argparse
import logging
import os
import re
import sys
import requests
from pathlib import Path
from requests import HTTPError
from squad_client.core.api import SquadApi
from squad_client.core.models import Squad, Build, TestRun
from squad_client.shortcuts import get_build
from squad_client.utils import getid, first

squad_host_url = "https://qa-reports.linaro.org/"
SquadApi.configure(cache=3600, url=os.getenv("SQUAD_HOST", squad_host_url))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_file(path, filename=None):
    print(f"Getting file from {path}")
    if re.search(r"https?://", path):
        request = requests.get(path, allow_redirects=True)
        request.raise_for_status()
        if not filename:
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
    parser.add_argument(
        "--retest_list_filename",
        required=False,
        default="retest_list.sh",
        help="Name for the group of reruns",
    )

    return parser.parse_args(raw_args)

def find_build(regex_exps, build_options, suite_names, environments, project, allow_unfinished, devices):
    # download compare builds with a name that can be imported
    compare_builds_url = "https://raw.githubusercontent.com/Linaro/squad-client-utils/master/squad-compare-builds"
    compare_builds_script_name = "squad_compare_builds.py"
    # Grab download_tests from squad_compare_builds
    if pathlib.Path(compare_builds_script_name).exists():
        os.remove(compare_builds_script_name)
    filename = wget.download(compare_builds_url, out=compare_builds_script_name)
    print("Filename", filename)
    from squad_compare_builds import download_tests

    build = None
    select_build_name = None
    for build_option in build_options.values():
        # only pick builds that are finished
        if not build_option.finished and not allow_unfinished:
            continue
        print("build option", build_option)
        # stop search if we have found build
        if build:
            break
        test_result_filename = "test.txt"
        suites = None
        if suite_names:
            suites = []
            for s in suite_names:
                suites += project.suites(slug=s).values()
        print("Suites", suites)
        print("Environments", environments)
        import traceback
        try:
            download_tests(project=project, build=build_option, suites=suites, environments=environments, output_filename=test_result_filename)
        except KeyError as e:
            print(traceback.format_exc())
            print("keyerror here", e)
            continue
        test_results = pathlib.Path(test_result_filename).read_text(encoding="utf-8").split("\n")

        device_build_names = {}

        # find all the gcc versions for each arch and pick highest
        for line in test_results:
            if build:
                break
            if len(line):
                device, build_name, suite_name, test_name_and_result = line.split("/")
                if device in device_build_names:
                    device_build_names[device].add(build_name)
                else:
                    print("device", device)
                    device_build_names[device] = {build_name}

        pprint.pprint(f"device build names {device_build_names}")
        if all(item in device_build_names for item in devices):
            print("all devices accounted for")
            for regex_exp in regex_exps:
                if build:
                    break
                for build_name_list in device_build_names.values():
                    for build_name_option in build_name_list:
                        re_match = re.match(f"^{regex_exp}$", build_name_option)
                        if not re_match:
                            print(f"no match {build_name_option} regex {regex_exp}")
                            build = None
                            select_build_name = None
                            continue
                        else:
                            print("found build name for this device regex")
                            build = build_option
                            select_build_name = regex_exp
                            break
                    if not build:
                        continue
        else:
            print("keep trying", device_build_names.keys())
            continue

    return build, select_build_name


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

    # get a build
    suite_names = ["ltp-syscalls"]
    build_options = base_project.builds(count=5, ordering="-id")
    build = None
    build, select_build_name = find_build(args.preferred_build_names, build_options, suite_names, environments, base_project, args.allow_unfinished, args.devices)
    print("try regex gcc-..-lkftconfig")

    print("build_options", build_options)
    build_options = base_project.builds(count=15, ordering="-id")
    print("build options", build_options)
    if not build:
        print("try again!!")
        build, select_build_name = find_build(args.other_accepted_build_names_regex, build_options, suite_names, environments, base_project, args.allow_unfinished, args.devices)

    if build:
        print("Found build", build.url)
    else:
        print("No build found")

        print(f"No build found for {branch_name}!")
        print("logging issue in .issues_build.csv")
        f = pathlib.Path(".issues_build.csv").open("a")
        f.write(f"No build found for, {branch_name}!\n")
        f.close()

    print("Build", build)





    environment = base_project.environment(device_name)
    if environment is None:
        print(f'There is no environment for "{device_name}"')
        return -1
    build = Build(base_build.id)
    test_options = build.tests(metadata=metadata.id, environment=environment.id)
    test = None

    # for test_option in test_options.values():
    #     testrun = TestRun(getid(test_option.test_run))
    #     if testrun.metadata.build_name == build_name:
    #         test = test_option
    #         print(f"Yes {testrun.metadata.build_name}")
    #         break
    #     else:
    #         print(f"Not {testrun.metadata.build_name}")
    # # find a back up if needed
    # if not test:
    #     alternatives = ["gcc-10-lkftconfig", "gcc-11-lkftconfig", "gcc-12-lkftconfig"]
    #     for test_option in test_options.values():
    #         testrun = TestRun(getid(test_option.test_run))
    #         if testrun.metadata.build_name in alternatives:
    #             test = test_option
    #             print(f"Yes {testrun.metadata.build_name}")
    #             break
    #         else:
    #             print(f"Not {testrun.metadata.build_name}")
    # # find a back up if needed
    # see if file exists that matches regex:
    reproducer_regex = f"reproducer-{test_type}-{device_name}-{build.version}-({select_build_name}).sh"
    found_build_name = None
    for filename in os.listdir("."):
        m = re.match(reproducer_regex, filename)
        if m:
            found_build_name = m.group(1)
            print(found_build_name)
    # if no reproducer found, grab test
    if not found_build_name:
        for test_option in test_options.values():
            testrun = TestRun(getid(test_option.test_run))
            # prefer exact matches
            if re.match(f"^{build_name}$", testrun.metadata.build_name):
                test = test_option
                print(f"Yes {testrun.metadata.build_name}, ^{build_name}$")
                break
        if not test:
            for test_option in test_options.values():
                if re.match(f"{build_name}", testrun.metadata.build_name):
                    test = test_option
                    print(f"Yes {testrun.metadata.build_name}, {build_name}")
                    break
                else:
                    print(f"Not {testrun.metadata.build_name}, {build_name}")

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
        f"retest-{test_type}-{args.rerun_name}.sh"
    )
    with open(args.retest_list_filename, "a+") as f:
        f.seek(0)
        retest_list = f.read()
        if retest_filename not in retest_list:
            f.write(retest_filename + "\n")

    for test_name in rerun_test_list:
        build_cmdline = ""
        if not found_build_name:
            results_file = f"results-{test_type}-{test_name}-{device_name}-{build.version}-{testrun.metadata.build_name}.json"
            reproducer_file = f"reproducer-{test_type}-{device_name}-{build.version}-{testrun.metadata.build_name}.sh"
            log_file = f"log-{test_type}-{test_name}-{device_name}-{build.version}-{testrun.metadata.build_name}.txt"
            print(testrun.job_url)
            print(testrun.url)
        else:
            results_file = f"results-{test_type}-{test_name}-{device_name}-{build.version}-{found_build_name}.json"
            reproducer_file = f"reproducer-{test_type}-{device_name}-{build.version}-{found_build_name}.sh"
            log_file = f"log-{test_type}-{test_name}-{device_name}-{build.version}-{found_build_name}.txt"

        try:
            if not Path(reproducer_file).exists():
                tuxrun = get_file(f"{testrun.job_url}/reproducer", reproducer_file)
            else:
                print("reusing reproducer", reproducer_file)
                tuxrun = reproducer_file
        except HTTPError:
            print(f"Reproducer not found at {testrun.job_url}!")
            print("logging issue in .issues.csv")
            f = Path(".issues.csv").open("a")
            f.write(f"Reproducer not found for test run,{testrun.url} ,{testrun.job_url}, {build.version}, {build.url}\n")
            f.close()
            return 1
        for line in Path(tuxrun).read_text(encoding="utf-8").split("\n"):
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
            '-"', f"{log_file} -- 'cd /opt/ltp && ./runltp -s {test_name}'"
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
