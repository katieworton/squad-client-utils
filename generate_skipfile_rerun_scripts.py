#!/usr/bin/python3
# -*- coding: utf-8 -*-
# vim: set ts=4

import argparse
import os
import pathlib
import sys
from squad_client.core.api import SquadApi
from squad_client.core.models import Squad
from squad_client.utils import first
import wget

# example: ./generate_skipfile_rerun_scripts.py --test_type ltp --devices "qemu-armv7" "qemu-arm64" "qemu-i386" "qemu-x86_64" --project linux-stable-rc-linux-6.1.y


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--kernel_versions",
        required=False,
        help="kernel versions to test on",
        nargs="+",
    )

    parser.add_argument("--project", required=True, help="squad project")

    parser.add_argument(
        "--devices", required=True, help="Devices to test on", nargs="+"
    )

    parser.add_argument(
        "--build_name",
        required=False,
        default="gcc-12-lkftconfig",
        help="Build config to test on",
    )

    parser.add_argument(
        "--test_type",
        required=True,
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
    project_name = args.project
    project = group.project(project_name)

    devices = args.devices
    kernel_versions = args.kernel_versions if args.kernel_versions else ["latest"]
    environments = ["all"]
    for skipreason in skips["skiplist"]:
        print(skipreason["url"])
        # Create a skiplist for each reason in the skiplist
        single_reason_skiplist = {"skiplist": [skipreason]}
        for device_name in devices:
            for kernel_name in kernel_versions:
                if args.kernel_versions:
                    build = first(
                        project.builds(
                            count=1,
                            ordering="-id",
                            metadata__kernel_version=kernel_name,
                        )
                    )
                else:
                    build = first(project.builds(count=1, ordering="-id"))
                for environment in environments:
                    skiptests = skipgen.get_skipfile_contents(
                        board=device_name,
                        branch=kernel_name,
                        environment=environment,
                        skips=single_reason_skiplist,
                    )
                    # don't try rerunning if there are no tests to run for this branch
                    if not skiptests:
                        continue

                    import squad_rerun_test_list

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
                        args.build_name,
                        "--test_type",
                        args.test_type,
                        "--debug",
                        "--rerun_name",
                        "-".join(skiptests),
                        "--tests",
                    ] + skiptests

                    squad_rerun_test_list.run(run_args)


if __name__ == "__main__":
    sys.exit(run())
