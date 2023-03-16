#!/usr/bin/python3
# -*- coding: utf-8 -*-
# vim: set ts=4

import argparse
import os
import pathlib
import pprint
import re
import sys
from squad_client.core.api import SquadApi
from squad_client.core.models import Squad
import wget

# example: ./generate_skipfile_rerun_scripts.py --test_type ltp --devices "qemu-armv7" "qemu-arm64" "qemu-i386" "qemu-x86_64"

branch_tree_lookup_stable = {
    "linux-4.14.y": "linux-stable-rc",
    "linux-4.19.y": "linux-stable-rc",
    "linux-5.4.y": "linux-stable-rc",
    "linux-5.10.y": "linux-stable-rc",
    "linux-5.15.y": "linux-stable-rc",
    "linux-6.1.y": "linux-stable-rc",
    "linux-6.2.y": "linux-stable-rc",
}

branch_tree_lookup_other = {
    "linux-mainline": "master",
    "linux-next": "master",
}

all_qemu_devices = ["qemu-armv7", "qemu-arm64", "qemu-i386", "qemu-x86_64"]

all_projects = [
    f"{branch}-{tree_name}" for branch, tree_name in branch_tree_lookup_stable.items()
] + [f"{branch}-{tree_name}" for tree_name, branch in branch_tree_lookup_other.items()]
all_branches = [b for b in branch_tree_lookup_stable.keys()] + [
    b for b in branch_tree_lookup_other.keys()
]

compare_builds_url = "https://raw.githubusercontent.com/Linaro/squad-client-utils/master/squad-compare-builds"

compare_builds_script_name = "squad_compare_builds.py"

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--kernel_versions",
        required=False,
        help="kernel versions to test on",
        nargs="+",
    )

    parser.add_argument(
        "--branches",
        required=False,
        default=all_branches,
        help="Branches - defaults to all",
        nargs="+",
    )

    parser.add_argument(
        "--devices", default=all_qemu_devices, help="Devices to test on", nargs="+"
    )

    parser.add_argument(
        "--preferred_build_names",
        required=False,
        default=["gcc-12-lkftconfig"],
        help="The preferred build names",
        nargs="+",
    )
    parser.add_argument(
        "--other_accepted_build_names_regex",
        required=False,
        default="gcc-\d\d-lkftconfig.*",
        help="If the preferred build name doesn't exist, allow build names that match this regex",
    )
    parser.add_argument(
        "--test_type",
        default="ltp",
        help="",
    )
    parser.add_argument(
        "--retest_list_filename",
        default="retest_list.sh",
        help="A list of scripts that contain reproducers",
    )
    parser.add_argument(
        "--allow_unfinished",
        default=False,
        action="store_true",
        help="",
    )

    return parser.parse_args()


def run():
    args = parse_args()
    # run skipgen on skipfile
    skipgen_file_name = "skipgen.py"
    if os.path.exists(skipgen_file_name):
        os.remove(skipgen_file_name)
    url = "https://gitlab.com/Linaro/lkft/users/katie.worton/skipgen-py/-/raw/main/skipgen.py"
    wget.download(url)

    skipfile_filename = "skipfile-lkft.yaml"
    # download skipfile
    if os.path.exists(skipfile_filename):
        os.remove(skipfile_filename)

    url = f"https://raw.githubusercontent.com/Linaro/test-definitions/master/automated/linux/{args.test_type}/skipfile-lkft.yaml"
    wget.download(url)

    import skipgen
    skipfile = pathlib.Path(skipfile_filename).read_text()

    skips = skipgen.parse_skipfile(skipfile)
    SquadApi.configure(url="https://qa-reports.linaro.org/")

    group_name = "lkft"
    group = Squad().group(group_name)
    branches = args.branches

    devices = args.devices
    environments_skipfile = ["all"]

    # Grab download_tests from squad_compare_builds
    if pathlib.Path(compare_builds_script_name).exists():
        os.remove(compare_builds_script_name)
    filename = wget.download(compare_builds_url, out=compare_builds_script_name)
    print(filename)
    from squad_compare_builds import download_tests
    suite_names = ["ltp-syscalls"]

    for branch_name in branches:
        if branch_name in branch_tree_lookup_stable:
            project_name = (
                f"{branch_tree_lookup_stable[branch_name]}-{branch_name}"
            )
        elif branch_tree_lookup_other:
            project_name = (
                f"{branch_name}-{branch_tree_lookup_other[branch_name]}"
            )

        print(project_name)
        project = group.project(project_name)
        environments = [project.environment(environment) for environment in all_qemu_devices]
        build_options = project.builds(count=5, ordering="-id")
        # find the latest finished build - filtering for
        # "finished=True" in the query doesn't seem to work
        build = None
        select_build_name = None
        for build_option in build_options.values():
            # only pick builds that are finished, unless explicitly allowed
            if not build_option.finished and not args.allow_unfinished:
                continue
            # stop search if we have found build
            if build:
                break
            test_result_filename = "test.txt"
            suites = None
            if suite_names:
                suites = []
                for s in suite_names:
                    suites += project.suites(slug=s).values()
            print(suites)
            # download the test results from the suite we want and see if all devices were used
            try:
                download_tests(project=project, build=build_option, suites=suites, environments=environments, output_filename=test_result_filename)
            except KeyError as e:
                print("keyerror", e)
                continue
            test_results = pathlib.Path(test_result_filename).read_text(encoding="utf-8").split("\n")

            device_build_names = {}

            # find all the gcc versions for each arch and pick highest
            for line in test_results:
                if build:
                    break
                if len(line):
                    # create a mapping to devices to build to look up if correct build exists
                    device, build_name, suite_name, test_name_and_result = line.split("/")
                    if device in device_build_names:
                        device_build_names[device].add(build_name)
                    else:
                        print(device)
                        device_build_names[device] = {build_name}

            pprint.pprint(device_build_names)
            if all(device in all_qemu_devices for device in device_build_names):
                print("all devices accounted for")
                for build_name_list in device_build_names.values():
                    if not any(item in args.preferred_build_names for item in build_name_list):
                        print(f"Couldn't find acceptable build name in {device_build_names.values()}")
                        build = None
                        select_build_name = None
                        break
                    else:
                        print("keep checking")
                        build = build_option
                        select_build_name = None
            else:
                print("keep trying", device_build_names.keys())
                continue
        # try with diff, but regex
        # TODO - put in function
        print("try regex gcc-..-lkftconfig")

        environments = [project.environment(environment) for environment in all_qemu_devices]
        print(build_options)
        build_options = project.builds(count=15, ordering="-id")
        print(build_options)
        if not build:
            for build_option in build_options.values():
                # only pick builds that are finished
                if not build_option.finished and not args.allow_unfinished:
                    continue
                # stop search if we have found build
                if build:
                    break
                test_result_filename = "test.txt"
                suites = None
                if suite_names:
                    suites = []
                    for s in suite_names:
                        suites += project.suites(slug=s).values()
                print(suites)
                print(environments)
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
                            print(device)
                            device_build_names[device] = {build_name}

                pprint.pprint(device_build_names)
                if all(item in all_qemu_devices for item in device_build_names):
                    print("all devices accounted for")
                    for build_name_list in device_build_names.values():
                        for build_name_option in build_name_list:
                            if not re.match(args.other_accepted_build_names_regex, build_name_option):
                                print(f"no match {build_name_option} regex")
                                build = None
                                continue
                            else:
                                print("found build name for this device regex")
                                build = build_option
                                break
                        if not build:
                            continue
                else:
                    print("keep trying", device_build_names.keys())
                    continue

        if build:
            print("Found build", build.url)
        else:
            print("No build found")

            print(f"No build found for {branch_name}!")
            print("logging issue in .issues_build.csv")
            f = pathlib.Path(".issues_build.csv").open("a")
            f.write(f"No build found for, {branch_name}!\n")
            f.close()

        print(build)
        if build:
            for device_name in devices:
                for skipreason in skips["skiplist"]:
                    print(skipreason["url"])
                    # Create a skiplist for each reason in the skiplist
                    single_reason_skiplist = {"skiplist": [skipreason]}
                    for environment in environments_skipfile:
                        skiptests = skipgen.get_skipfile_contents(
                            board=device_name,
                            branch=branch_name,
                            environment=environment,
                            skips=single_reason_skiplist,
                        )
                        # don't try rerunning if there are no tests to run for this branch
                        if not skiptests:
                            continue

                        import squad_generate_reproducer

                        # for test_name in skiptests:
                        run_args = [
                            "--group",
                            group_name,
                            "--project",
                            project_name,
                            "--build",
                            build.version,
                            "--device_name",
                            device_name,
                            "--build_name",
                            select_build_name,
                            "--test_type",
                            args.test_type,
                            "--retest_list_filename",
                            args.retest_list_filename,
                            "--debug",
                            "--rerun_name",
                            "-".join(skiptests),
                            "--tests",
                        ] + skiptests

                        squad_generate_reproducer.run(run_args)


if __name__ == "__main__":
    sys.exit(run())
