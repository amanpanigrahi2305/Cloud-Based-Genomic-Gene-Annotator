# archive_app_config.py
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
#
# Set app configuration options for archive utility
#
##
__author__ = "Aman Panigrahi"

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

    # AWS Region configuration
    AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "us-east-1")

    # AWS DynamoDB table
    # Dynamically generates table name based on the username
    AWS_DYNAMODB_ANNOTATIONS_TABLE = f"{iam_username}_annotations"

    # AWS S3 Settings
    AWS_S3_RESULTS_BUCKET = os.environ.get("AWS_S3_RESULTS_BUCKET", "your-results-bucket-name")

    # AWS SQS Settings
    # Replace <ACCOUNT_ID> with your 12-digit AWS Account ID
    AWS_SQS_ARCHIVE_URL = os.environ.get(
        "AWS_SQS_ARCHIVE_URL", 
        f"https://sqs.{AWS_REGION_NAME}.amazonaws.com/<ACCOUNT_ID>/{iam_username}_archive"
    )

    # AWS Glacier Settings
    # Replaced specific vault name with a generic placeholder
    AWS_GLACIER_VAULT = os.environ.get("AWS_GLACIER_VAULT", "your-glacier-vault-name")

    # AWS SNS Topic
    # Replace <ACCOUNT_ID> with your 12-digit AWS Account ID
    AWS_SNS_JOB_ARCHIVE_TOPIC = os.environ.get(
        "AWS_SNS_JOB_ARCHIVE_TOPIC",
        f"arn:aws:sns:{AWS_REGION_NAME}:<ACCOUNT_ID>:{iam_username}_job_archive"
    )

    # SQS Polling Parameters
    AWS_SQS_MAX_MESSAGES = 1
    AWS_SQS_WAIT_TIME = 15


### EOF
