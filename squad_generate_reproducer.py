#!/usr/bin/python3


import argparse
import logging
import os
import pathlib
import pprint
import re
import sys
import requests
from pathlib import Path
from requests import HTTPError
from squad_client.core.api import SquadApi
from squad_client.core.models import Squad, Build, TestRun, ALL, Test
from squad_client.shortcuts import get_build
from squad_client.utils import getid, first
import wget
import yaml

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
        else:
            output_file = Path(filename)
            output_file.parent.mkdir(exist_ok=True, parents=True)

        with open(filename, "wb") as f:
            f.write(request.content)
        return filename
    elif os.path.exists(path):
        return path
    else:
        raise Exception(f"Path {path} not found")


def read_results(result_file):
    pass


def create_tuxsuite_plan(tuxrun, suite, results_file, test_name, retest_filename, log_file, retest_script_list):
    with open(retest_script_list, "a+") as f:
        f.seek(0)
        retest_list = f.read()
        if retest_filename not in retest_list:
            f.write(retest_filename + "\n")
    test_yaml_str = None
    if not os.path.exists(retest_filename):
        test_yaml_str = """
version: 1
name: full kernel validation for the master branch.
description: Build and test linux kernel with every toolchain
jobs:
- name: test-command
  tests:
        """
    else:
        test_yaml_str = Path(retest_filename).read_text(encoding="utf-8")

    plan = yaml.load(test_yaml_str)
    print(plan)
    for line in Path(tuxrun).read_text(encoding="utf-8").split("\n"):
        if "tuxrun --runtime" in line:
            # parameters = re.findall("--(parameters) (\S+)", line)
            # print(parameters)
            timeouts = dict([(test, int(timeout)) for test, timeout in re.findall("--timeouts (\S+)=(\d+)", line)])
            timeouts["commands"] = 5
            parameters = {"command-name": test_name}
            print(timeouts)
            kernel = re.findall("--kernel (\S+)", line)
            print(kernel)
            rootfs = re.findall("--rootfs (\S+)", line)
            print(rootfs)
            modules = re.findall("--modules (\S+)", line)
            print(modules)
            device = re.findall("--device (\S+)", line)
            print(device)
            print(type(plan))
            if not plan["jobs"][0]["tests"]:
                plan["jobs"][0]["tests"] = []


            plan["jobs"][0]["tests"].append({"timeouts": timeouts, "parameters": parameters, "kernel": kernel[0], "rootfs": rootfs[0], "modules": modules[0], "device": device[0], "commands": [f'cd /opt/ltp && ./runltp -s {test_name}']})


            pprint.pprint(plan)
            print(yaml.dump(plan, sort_keys=False, default_flow_style=False))
            with open('test.yaml', 'w') as f:
                f.write(yaml.dump(plan, sort_keys=False, default_flow_style=False))

    with open(retest_filename, 'w') as f:
        f.write(yaml.dump(plan, sort_keys=False, default_flow_style=False))
        f.close()
        print(f"file appended: {retest_filename}")

def update_tuxsuite_plan():
    pass


def update_tuxrun_script():
    pass


def create_tuxrun_script(
    tuxrun, suite, results_file, test_name, retest_filename, log_file, retest_script_list
):
    build_cmdline = ""
    # Write the retest script name to a file if it isn't already there
    with open(retest_script_list, "a+") as f:
        f.seek(0)
        retest_list = f.read()
        if retest_filename not in retest_list:
            f.write(retest_filename + "\n")
    for line in Path(tuxrun).read_text(encoding="utf-8").split("\n"):
        if "tuxrun --runtime" in line:
            line = re.sub("--tests \S+ ", "", line)
            line = re.sub("--parameters SHARD_INDEX=\S+ ", "", line)
            line = re.sub("--parameters SHARD_NUMBER=\S+ ", "", line)
            line = re.sub("--parameters SKIPFILE=\S+ ", "", line)
            line = re.sub(f"{suite}=\S+", "--timeouts command=5", line)
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
        "--test_type",
        required=False,
        default="ltp",
        help="Only ltp is currently supported",
    )

    parser.add_argument(
        "--build_names",
        required=True,
        help="the build name (for example, gcc-12-lkftconfig)",
        nargs="+",
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
    parser.add_argument(
        "--allow_unfinished",
        default=False,
        action="store_true",
        help="",
    )
    parser.add_argument(
        "--local",
        default=False,
        action="store_true",
        help="",
    )
    parser.add_argument(
        "--run_dir",
        default="run_dir",
        help="",
    )

    return parser.parse_args(raw_args)


def find_good_build(
    project, environment, build_names, suite_name, version=None, testrun_id=None
):
    if version:
        builds = project.builds(
            ordering="-id", count=10, version__startswith=version
        ).values()
    else:
        builds = project.builds(ordering="-id", count=10).values()

    for build in builds:
        logger.debug(f'Trying to find good test in build "{build.version}"')
        if testrun_id:
            testruns = build.testruns(
                environment=environment.id, prefetch_metadata=True, testrun=testrun_id
            )
        else:
            testruns = build.testruns(
                environment=environment.id, prefetch_metadata=True
            )

        for testrun in testruns.values():
            if not testrun.metadata.build_name:
                print("No metadata found!")
                continue
            for build_name in build_names:
                logger.debug(f"  - Trying to find {build_name} in {testrun.job_url}")
                print(f"^{build_name}$")
                print(f"{testrun.metadata.build_name}")
                re_match = re.match(f"^{build_name}$", testrun.metadata.build_name)
                if re_match:
                    logger.debug(
                        f"    - Yay, found it, now looking for a passing {suite_name}"
                    )
                    candidate_test = first(
                        testrun.tests(
                            metadata__suite=suite_name, completed=True, result=True
                        )
                    )
                    if candidate_test is None:
                        logger.debug(f"      - no test in here :(")
                        continue
                    logger.debug("************** FOUND IT *************")
                    print(testrun)
                    return build, testrun

    return None, None


def download(
    project,
    build,
    build_names,
    filter_envs=None,
    filter_suites=None,
    format_string=None,
    output_filename=None,
):
    all_environments = project.environments(count=ALL)
    all_suites = project.suites(count=ALL)
    all_testruns = build.testruns(count=ALL, prefetch_metadata=True)

    filters = {
        "count": ALL,
        "fields": "id,name,status,environment,suite,test_run,build,short_name",
    }

    envs = None
    if filter_envs:
        filters["environment__id__in"] = ",".join([str(e.id) for e in filter_envs])
        envs = ",".join([e.slug for e in filter_envs])

    suites = None
    if filter_suites:
        filters["suite__id__in"] = ",".join([str(s.id) for s in filter_suites])
        suites = ",".join([s.slug for s in filter_suites])
        print("suites", suites)
        print(filters)

    filename = output_filename or f"{build.version}.txt"
    logger.info(
        f'Downloading test results for {project.slug}/{build.version}/{envs or "(all envs)"}/{suites or "(all suites)"} to {filename}'
    )

    if format_string is None:
        format_string = "{test.environment.slug}/{test.id}/{test.name} {test.status}"

    tests = build.tests(**filters)
    output = []
    if not tests:
        print("There are no tests to print")
    testrun = None
    tests_with_build_name = []
    for test in tests.values():
        if testrun:
            break
        test.build = build
        test.environment = all_environments[getid(test.environment)]
        test.suite = all_suites[getid(test.suite)]
        test.test_run = all_testruns[getid(test.test_run)]
        for build_name in build_names:
            re_match = re.match(f"^{build_name}$", test.test_run.metadata.build_name)
            print(f"rematch ^{build_name}$ {test.test_run.metadata.build_name}")
            if re_match:
                print("match", test.test_run.metadata.build_name)
                print("adding", test.short_name)
                tests_with_build_name.append(test.test_run)
                output.append(format_string.format(test=test))
                testrun = test.test_run
                break

    # output.sort()

    with open(filename, "w") as fp:
        for line in output:
            fp.write(line + "\n")
    print("DOWNLOAD TESTS", tests_with_build_name)
    # sys.exit(0)
    return testrun


def download_tests(project, build, build_names, environments, suites, output_filename):
    testrun = download(
        project,
        build,
        build_names,
        environments,
        suites,
        "{test.environment.slug}/{test.test_run.metadata.build_name}/{test.test_run.id}/{test.name} {test.status}",
        output_filename,
    )
    print("DOWNLOAD_TESTS_2", testrun)
    return testrun


def find_build(
    regex_exps,
    build_options,
    suite_names,
    environments,
    project,
    allow_unfinished,
    device_name,
    run_dir,
):

    build = None
    build_name = None
    tests = None
    testrun = None
    suites = None

    for build_option in build_options.values():
        # only pick builds that are finished
        if not build_option.finished and not allow_unfinished:
            continue
        print("build option", build_option)
        # stop search if we have found build
        if build:
            break
        if suite_names:
            suites = []
            for s in suite_names:
                suites += project.suites(slug=s).values()
        print("Suites", suites)
        print("Environments", environments)
        test_result_filename = f"{run_dir}/result_lookup/{project.id}{build_option.id}{suites}{environments}{build_option.version}"
        if not os.path.exists(test_result_filename):
            import traceback

            try:
                # TODO REUSE IF EXISTS
                testrun = download_tests(
                    project=project,
                    build=build_option,
                    build_names=regex_exps,
                    suites=suites,
                    environments=environments,
                    output_filename=test_result_filename,
                )
                # print("len tests", len(tests))
                if not testrun:
                    print("no test run")
                    continue
            except KeyError as e:
                print(traceback.format_exc())
                print("keyerror here", e)
                continue
        # If it is empty, we know there is no testrun in here so try the next build
        elif not os.path.getsize(test_result_filename):
            continue
        else:
            test_results = (
                pathlib.Path(test_result_filename)
                .read_text(encoding="utf-8")
                .split("\n")
            )
            line = test_results[0]
            (
                device,
                test_build_name,
                testrun_id,
                suite_name,
                test_name_and_result,
            ) = line.split("/")
            print("testrun id", testrun_id)
            testrun = TestRun(testrun_id)

        if not tests or not testrun:
            print("no tests")
            continue

        else:
            continue

    if not testrun:
        print(
            f"No test for {project.id}-{build_option.id}-{suites}-{environments}-{build_option.version}"
        )
    else:
        print(testrun)
        print(testrun.metadata)
        print(testrun.metadata.build_name)
        build_name = testrun.metadata.build_name
        build = testrun.build
    return build, build_name, testrun


def create_run_dir(dir_name):
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    if not os.path.exists(dir_name + "/result_lookup"):
        os.makedirs(dir_name + "/result_lookup")
    if not os.path.exists(dir_name + "/retest"):
        os.makedirs(dir_name + "/retest")
    if not os.path.exists(dir_name + "/reproducers"):
        os.makedirs(dir_name + "/reproducers")


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

    create_run_dir(args.run_dir)
    # base_build = get_build(args.build, base_project)
    # if base_build is None:
    #     logger.error(f"Get build failed. build not found: '{args.build}'.")
    #     return -1

    device_name = args.device_name
    # build_name = args.build_name
    print(f"build name {args.build_names}")
    test_type = args.test_type

    ltp_example_suite = "ltp-syscalls"
    metadata = first(Squad().suitemetadata(suite=ltp_example_suite, kind="test"))

    if metadata is None:
        print('There is no suite named "{suite_name}"')
        return -1

    # get a build
    suite_names = ["ltp-syscalls"]
    build_options = base_project.builds(count=7, ordering="-id")
    build = None
    testrun_id = None
    environment = base_project.environment(args.device_name)
    # TODO - possible optimisation of regex over local reproducers? perhaps a "fast-mode" parameter with an explanation would help

    reproducer_regex = f"/([^-]*)/(gcc-.*)/([\d]*).sh"
    build_name = None
    found_version = None
    reproducer_dir = (
        f"{args.run_dir}/reproducers/{test_type}/{device_name}/{base_project.slug}/"
    )
    if os.path.exists(reproducer_dir):
        for build_name_dir in os.listdir(reproducer_dir):
            print(build_name_dir)
            # see if there is matching build name
            for regex_exp in args.build_names:
                if build_name:
                    break
                print(f"^{regex_exp}$")
                print(f"{build_name_dir}")
                re_match = re.match(f"^{regex_exp}$", build_name_dir)
                if not re_match:
                    print(f"no match {build_name_dir} regex {regex_exp}")
                    build_name = None
                    continue
                else:
                    print("found build name for this device regex")
                    build_name = build_name_dir
                    test_id_reproducers = os.listdir(f"{reproducer_dir}/{build_name}")
                    if test_id_reproducers:
                        print(test_id_reproducers)
                        testrun_id, file_format = test_id_reproducers[0].split(".")
                        break
                    else:
                        print("false", test_id_reproducers)

    testrun = None
    if testrun_id:
        print("reuse build", testrun_id)
        # test = Test(test_id)
        testrun = TestRun(testrun_id)
        build = Build(getid(testrun.build))
        build_name = testrun.metadata.build_name

    else:
        print("find build")
        build, build_name, testrun = find_build(
            args.build_names,
            build_options,
            suite_names,
            [environment],
            base_project,
            args.allow_unfinished,
            args.device_name,
            args.run_dir,
        )
        try:
            build = Build(getid(testrun.build))
            build_name = testrun.metadata.build_name
        except AttributeError as e:
            print(f"{e}")

    if not build or not build_name or not testrun:
        print("No build found", build, build_name, testrun)

        print(
            f"No build found for {args.project} {args.device_name} {test_type} {args.tests}"
        )
        print("logging issue in .issues_build.csv")
        f = pathlib.Path(args.run_dir, ".issues_build.csv").open("a")
        f.write(
            f"No build found for {args.project} {args.device_name} {test_type} {args.tests}!\n"
        )
        f.close()
    else:
        print("Build", build)
        print("Found build", build.url)

        # In theory there should only be one of those
        logger.debug(f"Testrun id {testrun.id}")
        download_url = testrun.metadata.download_url
        if download_url is None:
            if testrun.metadata.config is None:
                print("There is no way to determine download_url")
                return -1
            download_url = testrun.metadata.config.replace("config", "")

        for test_name in args.tests:
            results_file = f"{args.run_dir}/results-{test_type}-{test_name}-{device_name}-{build.version}-{testrun.metadata.build_name}.json"
            reproducer_file = f"{reproducer_dir}/{build_name}/{testrun.id}.sh"
            log_file = f"{args.run_dir}/log-{test_type}-{test_name}-{device_name}-{build.version}-{testrun.metadata.build_name}.txt"

            try:
                if not Path(reproducer_dir).exists():
                    tuxrun = get_file(f"{testrun.job_url}/reproducer", reproducer_file)
                else:
                    print("reusing reproducer", reproducer_file)
                    tuxrun = reproducer_file
            except HTTPError:
                print(f"Reproducer not found at {testrun.job_url}!")
                print("logging issue in .issues.csv")
                f = Path(args.run_dir, ".issues.csv").open("a")
                f.write(
                    f"Reproducer not found for test run,{testrun.url} ,{testrun.job_url}, {build.version}, {build.url}\n"
                )
                f.close()
                return 1
            if args.local:
                retest_filename = (
                    f"{args.run_dir}/retest/{test_type}-{args.rerun_name}.sh"
                )
                retest_file_list = os.path.join(args.run_dir, args.retest_list_filename)
                create_tuxrun_script(
                    tuxrun, ltp_example_suite, results_file, test_name, retest_filename, log_file, retest_file_list
                )
            else:
                retest_filename = (
                    f"{args.run_dir}/retest/{test_type}-{base_project.slug}.yaml"
                )
                retest_file_list = os.path.join(args.run_dir, args.retest_list_filename)
                create_tuxsuite_plan(
                    tuxrun, ltp_example_suite, results_file, test_name, retest_filename, log_file, retest_file_list
                )


if __name__ == "__main__":
    sys.exit(run())
