#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    Generates a list of tests followed by theirs "stableness" (YES or a %)
"""


import argparse
from collections import defaultdict

from squad_client.core.api import SquadApi
from squad_client.core.models import Squad
from squad_client.utils import getid, parse_test_name

do_color = False


def _color(string, color):
    colors = {
        "red": "\033[31m",
        "green": "\033[42m",
        "yellow": "\033[33m",
    }

    end = "\033[0m"
    return colors[color] + string + end


red = lambda s: _color(s, "red") if do_color else s  # noqa
yellow = lambda s: _color(s, "yellow") if do_color else s  # noqa
green = lambda s: _color(s, "green") if do_color else s  # noqa


def join(array, separator=","):
    return separator.join(array)


def stableness(results, target="pass", pad=10):
    """
    A test is stable when all its results are "pass".
    Any test that doesn't fit that rule will get a
    number that represents the number of "pass" divided
    by the total number of results.
    """

    if len(results) == 0:
        return -1, red("N/A".center(pad))

    pass_count = results.count(target)
    n = pass_count / len(results)
    out = str(round(n * 100)) + "%"

    color = str
    if do_color:
        if n == 1:
            color = green
        else:
            color = yellow if n > 0.8 else red

    return n, color(out.center(pad))


def find_stable_tests(tests, envs={}, suites={}):
    """
    Print a list of stable tests

    - if environments are given

                   | envA | envb |
      suiteA       |  2/2 | 1/2  |
      - testA      |  Y   |  90% |
      - testB      |  Y   |  80% |
      suiteB/testA |  50% |  Y   |

    """

    if len(tests) == 0:
        print("*** No tests available ***")
        return

    envs_slugs = sorted([env.slug for env in envs.values()])
    tests_names = sorted(set([test.name for test in tests]))
    tests_dict = {}

    # Longest test name
    longest_test_name = max(
        [len(parse_test_name(name)[1]) for name in tests_names]
    ) + len("- ")

    # Saves a summary by suite
    suites_stableness = defaultdict(list)

    if len(envs):
        # Longest env slug
        longest_env_slug = max(10, max([len(slug) for slug in envs_slugs]))

        envs_dict = {env.slug: [] for env in envs.values()}
        tests_dict = defaultdict(lambda: envs_dict.copy())
        for test in tests:
            env = envs[getid(test.environment)]
            tests_dict[test.name][env.slug].append(test.status)

        print(" " * (3 + longest_test_name), end="")
        envs_header = "|".join([slug.center(longest_env_slug) for slug in envs_slugs])
        print(f"|{envs_header}|")

        prev_suite_slug = None
        for test_name in tests_names:
            suite_slug, test = parse_test_name(test_name)
            if suite_slug != prev_suite_slug:
                prev_suite_slug = suite_slug
                print(f"\n\033[1m{prev_suite_slug}\033[0m")

            print(f"- {test.ljust(longest_test_name)} ", end="")
            for env_slug in envs_slugs:
                n, out = stableness(
                    tests_dict[test_name][env_slug], pad=longest_env_slug
                )
                suites_stableness[suite_slug].append(n)
                print(f"|{out}", end="")
            print("|")
    else:
        tests_dict = defaultdict(list)
        for test in tests:
            tests_dict[test.name].append(test.status)

        prev_suite_slug = None
        for test_name in tests_names:
            suite_slug, test = parse_test_name(test_name)
            if suite_slug != prev_suite_slug:
                prev_suite_slug = suite_slug
                print(f"\n\033[1m{prev_suite_slug}\033[0m")

            n, out = stableness(tests_dict[test_name])
            suites_stableness[suite_slug].append(n)
            print(f"- {test.ljust(longest_test_name)} {out}")

    longest_suite_slug = max([len(slug) for slug in suites_stableness.keys()])

    print()
    print("*** Suite summary ***")
    for suite_slug in suites_stableness.keys():
        n, out = stableness(suites_stableness[suite_slug], target=1)
        print(f"\033[1m{suite_slug.ljust(longest_suite_slug)}\033[0m: {out}")


def main(args):
    global do_color

    do_color = args.color

    SquadApi.configure(args.squadapi_url)
    squad = Squad()
    print(f"I: Fetching group {args.group}")
    group = squad.group(args.group)
    print(f"I: Fetching project {args.project}")
    project = group.project(args.project)

    build_filters = {}
    if args.builds and len(args.builds):
        build_filters["version__in"] = join(args.builds)
    else:
        build_filters["count"] = args.n

    test_filters = {}
    if args.tests and len(args.tests):
        test_filters["metadata__name__in"] = join(args.tests)

    if args.suites and len(args.suites):
        print(f"I: Fetching {args.group}/{args.project} suites ({args.suites})")
        suites = project.suites(slug__in=join(args.suites))
        test_filters["suite__id__in"] = join([str(_id) for _id in suites.keys()])
    else:
        print(f"I: Fetching {args.group}/{args.project} suites")
        suites = project.suites()

    if args.no_arch:
        envs = {}
    elif args.archs and len(args.archs):
        print(f"I: Fetching {args.group}/{args.project} environments ({args.archs})")
        envs = project.environments(slug__in=join(args.archs))
        test_filters["environment__id__in"] = join([str(_id) for _id in envs.keys()])
    else:
        print(f"I: Fetching {args.group}/{args.project} environments")
        envs = project.environments()

    tests = []
    print(f"I: Fetching {args.n} builds ({build_filters}):", flush=True)
    for build in project.builds(**build_filters).values():
        print(f"D: Fetching build {build.version} tests ({test_filters})", flush=True)
        num_tests = 0
        for test in build.tests(**test_filters).values():
            if test.name.startswith("linux-log-parser"):
                continue
            tests.append(test)
            if num_tests % 1000 == 0:
                print(".", end="", flush=True)
            num_tests += 1

        if num_tests:
            print()

    print("I: Finding stable tests")
    find_stable_tests(
        tests,
        envs=envs,
        suites=suites,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default="lkft", help="Group name e.g., lkft")
    parser.add_argument(
        "--project", required=True, help="Project name e.g., linux-next-master"
    )
    parser.add_argument(
        "--builds",
        nargs="*",
        help="a list of builds (tag/sha) or the number of builds desired, e.g., next-20201204 or -n 10 . If none given, the 10 latest builds are chosen",
    )
    parser.add_argument(
        "-n",
        default=10,
        type=int,
        help="Number of builds to lookup, defaults to 10. If none given, the 10 latest builds are chosen",
    )
    parser.add_argument(
        "--archs",
        nargs="*",
        help="architectures to filter e.g. arm6 x86. If none given, show across all environments",
    )
    parser.add_argument(
        "--no-arch",
        action="store_true",
        default=False,
        help="Ignore checking for archs",
    )
    parser.add_argument(
        "--suites",
        nargs="*",
        help="Suite names to filter e.g., kunit ltp-math. If none given, show ",
    )
    parser.add_argument(
        "--tests",
        nargs="*",
        help="Test names to filter e.g. my-test-1 my-test-2 Show data for specific tests only",
    )
    parser.add_argument(
        "--squadapi_url",
        default="https://qa-reports.linaro.org",
        help="url to SQUAD server",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        default=False,
        help="Color output with green (100%), yellow (> 80%) or red",
    )

    args = parser.parse_args()
    main(args)
