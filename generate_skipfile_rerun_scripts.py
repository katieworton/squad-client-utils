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

# some devices are named differently in the skipfiles
skipfile_device_name_lookup = {
    "qemu-armv7": "qemu_arm",
    "qemu-arm64": "qemu_arm64",
    "qemu-i386": "qemu_i386",
    "qemu-x86_64": "qemu_x86_64",
}

all_qemu_devices = ["qemu-armv7", "qemu-arm64", "qemu-i386", "qemu-x86_64"]

all_projects = [
    f"{branch}-{tree_name}" for branch, tree_name in branch_tree_lookup_stable.items()
] + [f"{branch}-{tree_name}" for tree_name, branch in branch_tree_lookup_other.items()]
all_branches = [b for b in branch_tree_lookup_stable.keys()] + [
    b for b in branch_tree_lookup_other.keys()
]




def parse_args():
    parser = argparse.ArgumentParser()

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
        "--environment", default=["all"], nargs="+"
    )

    parser.add_argument(
        "--build_names",
        required=False,
        default=["gcc-12-lkftconfig", "gcc-\d\d-lkftconfig", "gcc-\d\d-lkftconfig-64k_page_size"],
        help="A list of regexs that capture the acceptable build names.",
        nargs="+",
    )
    parser.add_argument(
        "--test_type",
        default="ltp",
        help="",
    )
    parser.add_argument(
        "--retest_list_filename",
        default="retest_list.sh",
        help="The name of the file that logs all the skip test rerun scripts.",
    )
    parser.add_argument(
        "--allow_unfinished",
        default=False,
        action="store_true",
        help="Allow use of unfinished builds.",
    )
    parser.add_argument(
        "--allow_unrecognised_devices",
        default=False,
        action="store_true",
        help=f"Allow devices which are not in the known devices list: {', '.join(all_qemu_devices)}",
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
        help="The location where reproducer scripts and related logs should be stored.",
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

    environments_skipfile = args.environment


    if not args.allow_unrecognised_devices and not all(device in all_qemu_devices for device in args.devices):
        print(f"ERROR, unrecognised device(s): {set(args.devices).difference(set(all_qemu_devices))}")
        print("Please check the device names supplied and add the --allow_unrecognised_devices if you wish to override this check")
        sys.exit(1)

    for branch_name in branches:
        if branch_name in branch_tree_lookup_stable:
            project_name = (
                f"{branch_tree_lookup_stable[branch_name]}-{branch_name}"
            )
        elif branch_name in branch_tree_lookup_other:
            project_name = (
                f"{branch_name}-{branch_tree_lookup_other[branch_name]}"
            )
        else:
            print(f"Error: branch name {branch_name} is not supported by this script")
            sys.exit(1)

        print("Project name", project_name)
        project = group.project(project_name)
        environments = [project.environment(environment) for environment in args.devices]

        # Check environments are all valid:
        if None in environments:
            print("Environment not found", [environment for environment in args.devices if not project.environment(environment)])
            print("ERROR, check environments are valid")
            sys.exit(1)

        for device_name in args.devices:
            for skipreason in skips["skiplist"]:
                print("Skipreason url", skipreason["url"])
                # Create a skiplist for each reason in the skiplist
                single_reason_skiplist = {"skiplist": [skipreason]}
                for environment in environments_skipfile:
                    skiptests = skipgen.get_skipfile_contents(
                        board=device_name if device_name not in skipfile_device_name_lookup else skipfile_device_name_lookup[device_name],
                        branch=branch_name,
                        environment=environment,
                        skips=single_reason_skiplist,
                    )
                    # don't try rerunning if there are no tests to run for this branch
                    if not skiptests:
                        continue
                    print(skiptests)
                    import squad_generate_reproducer
                    # for test_name in skiptests:
                    print(f"RUN FOR {device_name}")
                    run_args = [
                        "--run_dir",
                        args.run_dir,
                        "--group",
                        group_name,
                        "--project",
                        project_name,
                        "--device_name",
                        device_name,
                        "--build_name"] \
                        + (args.build_names) + \
                        [
                        "--test_type",
                        args.test_type,
                        "--retest_list_filename",
                        args.retest_list_filename,
                        "--debug",
                        "--rerun_name",
                        "-".join(skiptests),
                        "--tests",
                    ] + skiptests

                    if args.allow_unfinished:
                        run_args.append("--allow_unfinished")
                    if args.local:
                        run_args.append("--local")

                    squad_generate_reproducer.run(run_args)
    print("Complete!")


if __name__ == "__main__":
    import time
    start_time = time.time()
    result = run()
    print(f"!!! {(time.time() - start_time)} seconds !!!")
    sys.exit(result)
