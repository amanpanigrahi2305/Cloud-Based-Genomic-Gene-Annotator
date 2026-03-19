# archive_app.py
#
# Archive Free user data
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##
__author__ = "Aman Panigrahi <amanpanigrahi2305@gmail.com>"

import boto3
import json
import requests
import os
import sys
from flask import Flask, request, jsonify
sys.path.insert(1,os.path.realpath(os.path.pardir))
import helpers
from botocore.exceptions import ClientError

app = Flask(__name__)
app.url_map.strict_slashes = False


environment = "archive_app_config.Config"
app.config.from_object(environment)

region = app.config["AWS_REGION_NAME"]
s3 = boto3.client("s3", region_name=region)
sqs = boto3.resource("sqs", region_name=region)
# Reference:
# Read about dynamodb table: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/index.html
dynamodb = boto3.resource("dynamodb", region_name=region)
table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])
glacier = boto3.client("glacier", region_name=region)

try:
    queue = sqs.Queue(app.config["AWS_SQS_ARCHIVE_URL"])
except ClientError as e:
    app.logger.error(f"Failed to connect to SQS queue: {e}")
    sys.exit(1)



@app.route("/", methods=["GET"])
def home():
    return f"This is the Archive utility: POST requests to /archive."


@app.route("/archive", methods=["POST"])
def archive_free_user_data():
    try:
        sns_msg = json.loads(request.data)
    # Reference:
    # Took syntax reference on how to catch multiple exception in one line: https://www.geeksforgeeks.org/python/multiple-exception-handling-in-python/
    # Read about ValueError and KeyError and there usage: https://www.geeksforgeeks.org/python/json-parsing-errors-in-python/
    except (ValueError, TypeError) as e:
        print(f"Error: Invalid JSON received from SNS: {e}")
        return jsonify({"error": "Invalid JSON"}), 400

    # Reference:
    # Read about SubscriptionConfirmation and SubscribeURL: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
    # Took syntax reference for SubscriptionConfirmation and SubscribeURL and convert it to python: https://stackoverflow.com/questions/15079829/example-sns-subscription-confirmation-using-aws-net-sdk
    if sns_msg.get("Type") == "SubscriptionConfirmation":
        subscribe_url = sns_msg.get("SubscribeURL")
        if subscribe_url:
            try:
                requests.get(subscribe_url)
                print("SNS Subscription Confirmed.")
            except Exception as e:
                print(f"Failed to confirm subscription: {e}")
        return jsonify({"status": "confirmed"}), 200

    if sns_msg.get("Type") == "Notification":
        try:
            # Reference:
            # Read about .receive_messages and syntax used : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/receive_message.html#
            messages = queue.receive_messages(
                MaxNumberOfMessages=app.config["AWS_SQS_MAX_MESSAGES"],
                WaitTimeSeconds=app.config["AWS_SQS_WAIT_TIME"]
            )
        except ClientError as e:
            print(f"SQS Error receiving messages: {e.response['Error']['Message']}")
            return jsonify({"error": "SQS failure"}), 500

        for message in messages:
            job_id = "unknown"
            try:
                body = json.loads(message.body)
                payload = json.loads(body.get("Message"))

                job_id = payload.get("job_id")
                user_id = payload.get("user_id")
                s3_key = payload.get("results_file")
                results_bucket = payload.get("results_bucket")

                if not job_id or not user_id:
                    print(f"ERROR: Missing required fields in payload for job {job_id}")
                    message.delete()
                    continue

                try:
                    profile = helpers.get_user_profile(id=user_id)
                    role = profile.get("role")
                except Exception as e:
                    print(f"Error fetching profile for {user_id}: {e}")
                    continue

                if role == "free_user":
                    print(f"Job {job_id}: Archiving for Free user.")

                    # Reference:
                    # Read about .get_object: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html
                    # Took code reference: https://github.com/boto/boto3/blob/develop/boto3/examples/s3.rst
                    try:
                        res = s3.get_object(Bucket=results_bucket, Key=s3_key)
                    # Reference:
                    # Took Systax reference to catch S3 .NoSuchKey error: https://oneuptime.com/blog/post/2026-02-12-boto3-errors-and-exceptions/view
                    # Read about catching exceptions when using a resource client: https://docs.aws.amazon.com/boto3/latest/guide/error-handling.html:
                    except s3.exceptions.NoSuchKey:
                        print(f"Error: S3 file {s3_key} not found for job {job_id}.")
                        message.delete()
                        continue

                    #Reference:
                    # Read about upload_archive: https://docs.aws.amazon.com/boto3/latest/reference/services/glacier/client/upload_archive.html
                    try:
                        glacier_res = glacier.upload_archive(
                            vaultName=app.config["AWS_GLACIER_VAULT"],
                            body=res["Body"].read()
                        )
                        archive_id = glacier_res["archiveId"]
                    except ClientError as e:
                        print(f"Glacier upload failed for {job_id}: {e.response['Error']['Message']}")
                        continue

                    # Reference:
                    # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
                    # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
                    try:
                        table.update_item(
                            Key={"job_id": job_id},
                            UpdateExpression="SET results_file_archive_id = :aid",
                            ExpressionAttributeValues={":aid": archive_id}
                        )
                    except ClientError as e:
                        print(f"DB Update failed for {job_id}: {e.response['Error']['Message']}")
                        continue

                    #Reference:
                    # Read bout delete_object: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_object.html
                    # Took Syntax reference: https://github.com/boto/boto3/issues/2290
                    try:
                        s3.delete_object(Bucket=results_bucket, Key=s3_key)
                        print(f"Job {job_id}: Successfully archived to Glacier and deleted from S3.")
                    except ClientError as e:
                        print(f"Warning: Archive ID saved, but S3 deletion failed for {job_id}: {e.response['Error']['Message']}")

                else:
                    print(f"Job {job_id}: Premium user, skipping archival.")

                try:
                    message.delete()
                except ClientError as e:
                    print(f"Failed to delete message from SQS for job {job_id}: {e.response['Error']['Message']}")
                    sys.exit(1)
                except Exception as e:
                    app.logger.error(f"Unexpected error initializing SQS: {e}")
                    sys.exit(1)

            except ClientError as e:
                print(f"AWS ClientError processing job {job_id}: {e.response['Error']['Message']}")
            except Exception as e:
                print(f"Unexpected error processing job {job_id}: {e}")

    return jsonify({"status": "processed"}), 200

### EOF
