#!/usr/bin/env python3

"""

Get a list of kunit runs across projects

"""

import re
from collections import defaultdict
from squad_client.core.models import Squad, ALL
from squad_client.core.api import SquadApi

# Some configuration, might get parameterized later
SquadApi.configure('https://qa-reports.linaro.org')
squad = Squad()
group_slug = 'lkft'
suite_slug = 'kunit'
getid = lambda s: int(re.search('\d+', s).group())

# kunit should be in the latest kernel releases
# next, mainline

# First we need to know which projects from the selected group
# contain kunit suite
print('Fetching projects that contain "%s" suites for "%s" group' % (suite_slug, group_slug), flush=True)
suites = squad.suites(slug=suite_slug, project__group__slug=group_slug)
projects_ids = list(set([str(getid(suite.project)) for suite in suites.values()]))
projects = squad.projects(id__in=','.join(projects_ids), ordering='slug').values()

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
table = {}

for project in projects:
    print('- %s: fetching 10 builds' % project.slug, flush=True)

    environments = project.environments(count=ALL)

    for build in project.builds(count=10, ordering='-id').values():
        print('  - %s: fetching tests' % build.version, flush=True)
        results = {'summary': defaultdict(dict)}

        for test in build.tests(suite__slug=suite_slug).values():

            env = environments[getid(test.environment)].slug

            if test.status not in results['summary'][env]:
                results['summary'][env][test.status] = 0
            results['summary'][env][test.status] += 1
            
            if env not in results:
                results[env] = []
            results[env].append((test.name, test.status))

        if len(results['summary']):
            print('    - summary:', flush=True)
            summary = results.pop('summary')
            for env in sorted(summary.keys()):
                print('      - %s: %s' % (env, summary[env]), flush=True)

            for env in sorted(results.keys()):
                print('    - %s:' % env, flush=True)
                for test in sorted(results[env], key=lambda d: d[0]):
                    print('      - %s: %s' % (test[0], test[1]), flush=True)

