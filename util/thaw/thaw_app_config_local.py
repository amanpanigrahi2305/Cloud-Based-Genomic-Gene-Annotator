# thaw_app_config.py
#
# Copyright (C) 2015-2024 Vas Vasiliadis
# University of Chicago
#
# Set app configuration options for thaw utility
#
##
__author__ = "Vas Vasiliadis <vas@uchicago.edu>"

import os

# Get the IAM username that was stashed at launch time
try:
    with open("/home/ubuntu/.launch_user", "r") as file:
        iam_username = file.read().replace("\n", "")
except FileNotFoundError as e:
    if "LAUNCH_USER" in os.environ:
        iam_username = os.environ["LAUNCH_USER"]
    else:
        # Unable to set username, so exit
        print("Unable to find launch user name in local file or environment!")
        raise e


class Config(object):

    CSRF_ENABLED = True

    AWS_REGION_NAME = "us-east-1"

    # AWS DynamoDB table
    AWS_DYNAMODB_ANNOTATIONS_TABLE = f"{iam_username}_annotations"

    # AWS Glacier
    AWS_GLACIER_VAULT = "<YOUR_GLACIER_VAULT_NAME>"

    # AWS SNS Topic for Glacier to notify when thaw is complete
    AWS_RESTORE_TOPIC = f"arn:aws:sns:us-east-1:<ACCOUNT_ID>:{iam_username}_a17_job_restore"

    AWS_THAW_QUEUE_NAME = f"{iam_username}_a17_job_thaw"

    # SQS Polling settings
    MAX_MESSAGES = 1
    WAIT_TIME = 15
### EOF
