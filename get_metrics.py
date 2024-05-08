#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from squad_client.core.models import ALL, Squad

group_slug = "lkft"
project_slug = "linux-mainline-master"


group = Squad().group(group_slug)
project = group.project(project_slug)
builds = project.builds(count=10, created_at__lt="2020-09-30T20:40:50.341386Z")

for build in builds.values():
    print("Getting metrics for build %s" % build.version)
    metrics = (
        Squad()
        .metrics(
            fields="id,short_name,result,test_run,suite",
            ordering="name",
            count=ALL,
            test_run__build=build.id,
        )
        .values()
    )
    for metric in metrics:
        print("\t%s: %.2f" % (metric.short_name, metric.result))
