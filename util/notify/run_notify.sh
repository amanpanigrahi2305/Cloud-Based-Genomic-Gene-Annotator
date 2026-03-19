#!/bin/bash

# run_notify.sh
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
#
# Runs the notifier utility script
#
##

cd /home/ubuntu/gas/util/notify
source /home/ubuntu/.virtualenvs/mpcs/bin/activate
/home/ubuntu/.virtualenvs/mpcs/bin/python /home/ubuntu/gas/util/notify/notify.py

### EOF