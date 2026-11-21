# ann_config.py
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
#
# Set GAS annotator configuration options
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

    # Base directory for the annotator application
    # Using os.path.expanduser("~") makes this work on any Linux/Mac user home
    ANNOTATOR_BASE_DIR = os.path.join(os.path.expanduser("~"), "gas/ann")
    ANNOTATOR_JOBS_DIR = f"{ANNOTATOR_BASE_DIR}/jobs"

    # AWS Region configuration
    AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "us-east-1")

    # AWS S3 upload parameters
    # Users can override these via environment variables
    AWS_S3_INPUTS_BUCKET = os.environ.get("AWS_S3_INPUTS_BUCKET", "your-input-bucket-name")
    AWS_S3_RESULTS_BUCKET = os.environ.get("AWS_S3_RESULTS_BUCKET", "your-results-bucket-name")

    # AWS SNS topics
    AWS_SNS_JOB_REQUEST_TOPIC = os.environ.get("AWS_SNS_JOB_REQUEST_TOPIC_ARN")
    AWS_SNS_JOB_RESULTS_TOPIC = os.environ.get("AWS_SNS_JOB_RESULTS_TOPIC_ARN")

    # AWS SQS queues
    AWS_SQS_WAIT_TIME = 20
    AWS_SQS_MAX_MESSAGES = 10
    AWS_SQS_JOB_REQUESTS_URL = os.environ.get("AWS_SQS_JOB_REQUESTS_URL")

    # AWS DynamoDB
    # Dynamically generates table name based on the username
    AWS_DYNAMODB_ANNOTATIONS_TABLE = f"{iam_username}_annotations"


### EOF
