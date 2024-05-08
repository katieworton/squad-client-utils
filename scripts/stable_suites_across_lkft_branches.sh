#!/bin/bash

# Branches can also be retrieved dynamically by
# wget "https://qa-reports.linaro.org/api/projects/?group__slug=lkft&fields=slug&slug__contains=stable-rc-linux&slug__endswith=.y" -O - \
#  | jq -r '.results[].slug' \
#  | sed 's/linux-stable-rc-linux-\(.*\)\.y.*/\1/' \
#  | sort -u
branches="4.4 4.9 4.14 4.19 5.4 5.8 5.9 5.10 5.11 5.12"

# Fetch all stable tests across all LKFT stable branches
# - generate a file per branch with all tests listings (stables or not)
# - generate a file per branch with all stable suites
for branch in $branches
do
    python3 find_stable_tests.py --project linux-stable-rc-linux-$branch.y --no-arch \
            | tee stable_tests_$branch \
            | sed '1,/Suite summary/d' \
            | grep YES \
            | sed -r 's/\x1B\[([0-9]{1,3}(;[0-9]{1,2})?)?[mGK]//g' > stable_suites_$branch \
            &
done

wait

echo
echo "**************************************"
echo "* Generating a list of stable suites *"
echo "**************************************"
echo

# Generate a list of suites that are stable in at least one branch
awk '{print $1}' stable_suites_* | sort -u > stable_suites_all_branches

# For each suite, grep all stable_suites_* to check how stable the suite is across branches
for suite in `cat stable_suites_all_branches`
do
    echo -n $suite:
    not_stable_in=""
    for branch in $branches
    do
        grep -q $suite stable_suites_$branch 2>/dev/null
        if [[ $? != 0 ]]
        then
            percentage=`grep $suite stable_tests_$branch 2>/dev/null | tail -1 | awk '{print $4}'`
            if [[ $percentage == "" ]]
            then
                percentage="N/A"
            fi
            not_stable_in="$not_stable_in $branch($percentage)"
        fi
    done

    if [[ $not_stable_in == "" ]]
    then
        not_stable_in="stable"
    fi

    echo " $not_stable_in"
done
