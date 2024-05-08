#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Get a list of suites runs across projects
"""

import argparse
import re
from collections import defaultdict

from squad_client.core.api import SquadApi
from squad_client.core.models import ALL, Squad


def main(args):
    # Some configuration, might get parameterized later
    group_slug = args.get("group", None)
    suite_slug = args.get("suite", None)
    SquadApi.configure(args.get("squadapi_url", None))
    number_of_builds = args.get("number", None)
    squad = Squad()
    getid = lambda s: int(re.search(r"\d+", s).group())  # noqa

    # First we need to know which projects from the selected group
    # contain the specified suite.
    print(
        'Fetching projects that contain "%s" suites for "%s" group'
        % (suite_slug, group_slug),
        flush=True,
    )
    suites = squad.suites(slug=suite_slug, project__group__slug=group_slug)
    projects_ids = list(set([str(getid(suite.project)) for suite in suites.values()]))
    projects = squad.projects(id__in=",".join(projects_ids), ordering="slug").values()

    # Env/arch cache
    environments = set()

    # Table will be layed out like below
    # table = {
    #     'kernelA': {
    #         'buildA': {
    #             'summary': {
    #                 'envA': {'pass': 1, 'fail': 2, 'skip': 3},
    #                 'envB': {'pass': 1, 'fail': 2, 'skip': 3},
    #             }
    #             'envA': [
    #                 {'kunit/test1': 'pass'}
    #                 {'kunit/test2': 'fail'}
    #             ]
    #         },
    #     }
    # }
    # table = {}

    if number_of_builds == "0":
        for project in projects:
            print("- %s" % project.slug, flush=True)
        return

    for project in projects:
        print("- %s: fetching %s builds" % (project.slug, number_of_builds), flush=True)

        environments = project.environments(count=ALL)

        for build in project.builds(
            count=int(number_of_builds), ordering="-id"
        ).values():
            print("  - %s: fetching tests" % build.version, flush=True)
            results = {"summary": defaultdict(dict)}

            for test in build.tests(suite__slug=suite_slug).values():
                env = environments[getid(test.environment)].slug

                if test.status not in results["summary"][env]:
                    results["summary"][env][test.status] = 0
                results["summary"][env][test.status] += 1

                if env not in results:
                    results[env] = []
                results[env].append((test.name, test.status))

            if len(results["summary"]):
                print("    - summary:", flush=True)
                summary = results.pop("summary")
                for env in sorted(summary.keys()):
                    print("      - %s: %s" % (env, summary[env]), flush=True)

                for env in sorted(results.keys()):
                    print("    - %s:" % env, flush=True)
                    for test in sorted(results[env], key=lambda d: d[0]):
                        print("      - %s: %s" % (test[0], test[1]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True, help="Group name e.g., lkft")
    parser.add_argument("--suite", required=True, help="Suite name e.g., kunit")
    parser.add_argument(
        "--squadapi_url",
        default="https://qa-reports.linaro.org",
        help="url to SQUAD server",
    )
    parser.add_argument("--number", default="0", help="number of builds, default 0")
    args = vars(parser.parse_args())
    if args:
        main(args)
    else:
        exit(1)
