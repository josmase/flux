#Remove all in the cache repo not downloaded in the last month
jf rt-cleanup clean cache --time-unit=month --no-dl=1
