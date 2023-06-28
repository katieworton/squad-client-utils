#!/usr/bin/python3
# -*- coding: utf-8 -*-
# vim: set ts=4
#
# Copyright 2023-present Linaro Limited
#
# SPDX-License-Identifier: MIT


from logging import DEBUG, INFO, basicConfig, getLogger
from os import path, remove
from pathlib import Path
from re import match, search, sub

from requests import HTTPError, get
from squad_client.core.models import Squad, TestRun
from squad_client.shortcuts import download_tests
from squad_client.utils import first

basicConfig(level=INFO)
logger = getLogger(__name__)


class ReproducerNotFound(Exception):
    """
    Raised when no reproducer can be found.
    """

    def __init__(self, message="No reproducer found"):
        super().__init__(message)


def get_file(path, filename=None):
    """
    Download file if a URL is passed in, then return the filename of the
    downloaded file. If an existing file path is passed in, return the path. If
    a non-existent path is passed in, raise an exception.
    """
    logger.debug(f"Getting file from {path}")
    if search(r"https?://", path):
        request = get(path, allow_redirects=True)
        request.raise_for_status()
        if not filename:
            filename = path.split("/")[-1]
        else:
            output_file = Path(filename)
            output_file.parent.mkdir(exist_ok=True, parents=True)

        with open(filename, "wb") as f:
            f.write(request.content)
        return filename
    elif path.exists(path):
        return path
    else:
        raise Exception(f"Path {path} not found")


def find_first_good_testrun(
    build_names,
    builds,
    suite_names,
    envs,
    project,
    allow_unfinished=False,
    output_filename="result.txt",
):
    """
    Given a list of builds IDs to choose from in a project, find the first one
    that has a match for the build name, suite names and environments
    """

    # Given a list of builds IDs, find one that contains the suites and that
    # has a matching build name
    for build in builds.values():
        suites = []
        # Only pick builds that are finished, unless we specify that unfinished
        # builds are allowed
        if not build.finished and not allow_unfinished:
            logger.debug(f"Skipping {build.id} as build is not marked finished")
            continue
        logger.debug(f"Checking build {build.id}")
        # Create the list of suite IDs from the suite names
        if suite_names:
            for s in suite_names:
                suites += project.suites(slug=s).values()

        if path.exists(output_filename):
            remove(output_filename)

        # Use download_tests to gather filtered test results (build_name does not
        # currently work as a filter)
        download_tests(
            project,
            build,
            envs,
            suites,
            "{test.test_run.metadata.build_name}/{test.test_run.id}",
            output_filename,
        )

        # Look in the file that contains the downloaded tests and see if there is a
        # match for one of the desired build_names
        file_open = open(output_filename, "r")
        file_lines = file_open.readlines()

        for line in file_lines:
            build_name, run_id = line.split("/")
            for allowed_build_name in build_names:
                re_match = match(f"^{allowed_build_name}$", build_name)
                if re_match:
                    # Return a TestRun with a matching build name, project, environment, suite
                    # if it exists
                    return TestRun(run_id)

    # If no matching testrun found
    return None


def get_reproducer(
    group,
    project,
    device_name,
    debug,
    build_names,
    suite_name,
    count,
    filename,
    allow_unfinished=False,
    local=False,
):
    """
    Given a group, project, device and accepted build names, return a
    reproducer for a test run that meets these conditions.
    """
    if debug:
        logger.setLevel(level=DEBUG)

    base_group = Squad().group(group)
    if base_group is None:
        logger.error(f"Get group failed. Group not found: {group}")
        raise ReproducerNotFound

    base_project = base_group.project(project)
    if base_project is None:
        logger.error(f"Get project failed. project not found: {project}")
        raise ReproducerNotFound

    logger.debug(f"build name {build_names}")

    metadata = first(Squad().suitemetadata(suite=suite_name, kind="test"))

    if metadata is None:
        logger.error(f"There is no suite named: {suite_name}")
        raise ReproducerNotFound

    # == get a build that contains a run of the specified suite ==

    # Get the latest N builds in the project so we don't pick something old
    builds = base_project.builds(count=count, ordering="-id")
    environment = base_project.environment(device_name)

    logger.debug("Find build")

    testrun = find_first_good_testrun(
        build_names, builds, [suite_name], [environment], base_project, allow_unfinished
    )

    # Get the reproducer if a testrun is found
    if testrun:
        logger.debug(
            f"Found testrun {testrun} with build_name {testrun.metadata.build_name}, url: {testrun.url}"
        )

        # In theory there should only be one of those
        logger.debug(f"Testrun id: {testrun.id}")

        try:
            if local:
                reproducer = get_file(
                    f"{testrun.job_url}/reproducer", filename=filename
                )
            else:
                reproducer = get_file(
                    f"{testrun.job_url}/tuxsuite_reproducer", filename=filename
                )
        except HTTPError:
            logger.error(f"Reproducer not found at {testrun.job_url}!")
            raise ReproducerNotFound
        return Path(reproducer).read_text(encoding="utf-8")
    else:
        raise ReproducerNotFound


def create_custom_reproducer(reproducer, suite, custom_commands, filename, local=False):
    """
    Given an existing TuxRun or TuxTest reproducer, edit this reproducer to run
    a given custom command.
    """
    build_cmdline = ""

    for line in reproducer.split("\n"):
        if ("tuxsuite test submit" in line and not local) or (
            "tuxrun --runtime" in line and local
        ):
            line = sub(r"--tests \S+ ", "", line)
            line = sub(r"--parameters SHARD_INDEX=\S+ ", "", line)
            line = sub(r"--parameters SHARD_NUMBER=\S+ ", "", line)
            line = sub(r"--parameters SKIPFILE=\S+ ", "", line)
            line = sub(f"{suite}=\\S+", "commands=5", line)
            if local:
                build_cmdline = path.join(
                    build_cmdline + line.strip() + ' --save-outputs --log-file -"'
                ).strip()
                build_cmdline = build_cmdline.replace('-"', f"- -- '{custom_commands}'")
            else:
                build_cmdline = path.join(
                    build_cmdline
                    + line.strip()
                    + f''' --commands "'{custom_commands}'"'''
                ).strip()

    reproducer_list = f"""#!/bin/bash\n{build_cmdline}"""
    Path(filename).write_text(reproducer_list, encoding="utf-8")

    return Path(filename).read_text(encoding="utf-8")


def create_ltp_custom_command(tests):
    return f"cd /opt/ltp && ./runltp -s {' '.join(tests)}"
