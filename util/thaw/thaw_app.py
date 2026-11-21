# thaw_app.py
#
# Thaws upgraded (Premium) user data
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##
__author__ = "Aman Panigrahi"

import boto3
import json
import requests
import sys
import time

from botocore.exceptions import ClientError
from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# Get configuration and add to Flask app object
environment = "thaw_app_config.Config"
app.config.from_object(environment)

REGION = app.config.get("AWS_REGION_NAME")
glacier_client = boto3.client('glacier', region_name=REGION)
sqs = boto3.resource('sqs', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)

QUEUE_NAME = app.config.get("AWS_THAW_QUEUE_NAME")
VAULT_NAME = app.config.get("AWS_GLACIER_VAULT")
RESTORE_TOPIC_ARN = app.config.get("AWS_RESTORE_TOPIC")
TABLE_NAME = app.config.get("AWS_DYNAMODB_ANNOTATIONS_TABLE")

try:
    # Reference:
    # Read about SQS get_queue_by_name: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/service-resource/get_queue_by_name.html
    queue = sqs.get_queue_by_name(QueueName=QUEUE_NAME)
    print(f"Successfully connected to SQS Queue: {QUEUE_NAME}")
except ClientError as e:
    print(f"ERROR: Failed to connect to SQS queue {QUEUE_NAME}: {e}")
    sys.exit(1)

@app.route("/", methods=["GET"])
def home():
    return f"This is the Thaw utility: POST requests to /thaw."


@app.route("/thaw", methods=["POST"])
def thaw_premium_user_data():
    # Reference:
    # Read about JSONDecodeError and handling JSON errors: https://www.geeksforgeeks.org/json-parsing-errors-in-python/
    # Read about decoding request data in Flask: https://stackoverflow.com/questions/20001229/how-to-get-posted-json-in-flask
    try:
        msg = json.loads(request.data.decode('utf-8'))
    except json.JSONDecodeError:
        print("ERROR: Failed to decode JSON from SNS payload.")
        return "Invalid JSON", 400

    # Reference:
    # Read about x-amz-sns-message-type : https://docs.aws.amazon.com/sns/latest/dg/http-header.html
    msg_type = request.headers.get('x-amz-sns-message-type')

    # Reference:
    # Read about SubscriptionConfirmation and SubscribeURL: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
    # Took .net syntax reference for SubscriptionConfirmation and SubscribeURL and convert it to python: https://stackoverflow.com/questions/15079829/example-sns-subscription-confirmation-using-aws-net-sdk
    if msg_type == 'SubscriptionConfirmation':
        subscribe_url = msg.get('SubscribeURL')
        if subscribe_url:
            try:
                response = requests.get(subscribe_url)
                response.raise_for_status()
                print("Successfully confirmed SNS subscription for Thaw app!")
            except requests.exceptions.RequestException as e:
                print(f"ERROR: Failed to confirm subscription: {e}")
                return jsonify({"code": 500, "error": "Failed to confirm subscription"}), 500
        return jsonify({"code": 400, "error": "Missing SubscribeURL"}), 400

    elif msg_type == 'Notification':
        try:
            # Reference:
            # Read about .receive_messages and syntax used : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/receive_message.html#
            messages = queue.receive_messages(
                MaxNumberOfMessages=app.config.get("MAX_MESSAGES"),
                WaitTimeSeconds=app.config.get("WAIT_TIME")
            )

            if not messages:
                print("Queue is empty. No action taken.")
                return jsonify({"code": 200, "message": "Queue empty"}), 200

            for message in messages:
                try:
                    body = json.loads(message.body)
                    job_data = json.loads(body.get("Message", "{}"))

                    job_id = job_data.get('job_id')
                    user_id = job_data.get('user_id')
                    archive_id = job_data.get("results_file_archive_id")

                    if not all([job_id, user_id, archive_id]):
                        print("ERROR: SQS message missing required attributes. Deleting malformed message.")
                        message.delete()
                        continue

                    # Reference:
                    # Read about formatting Glacier jobParameters: https://docs.aws.amazon.com/amazonglacier/latest/dev/api-initiate-job-post.html
                    job_params = {
                        "Type": "archive-retrieval",
                        "ArchiveId": archive_id,
                        "SNSTopic": RESTORE_TOPIC_ARN,
                        "Description": json.dumps({
                            "job_id": job_id,
                            "user_id": user_id,
                            "s3_key_results": job_data.get('s3_key_results')
                        })
                    }

                    try:
                        # Reference:
                        # Read about Glacier initiate_job: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier/client/initiate_job.html
                        print(f"\n Attempting EXPEDITED retrieval for archive {archive_id} (job: {job_id})")
                        job_params["Tier"] = "Expedited"
                        glacier_client.initiate_job(
                            vaultName=VAULT_NAME,
                            jobParameters=job_params
                        )
                        print(f" SUCCESS: Expedited retrieval accepted for job: {job_id}")

                    except ClientError as e:
                        # Reference:
                        # Read about parsing Boto3 ClientError responses (e.response['Error']['Code']): https://boto3.amazonaws.com/v1/documentation/api/latest/guide/error-handling.html#parsing-error-responses
                        # Read about exceptions InsufficientCapacityException: https://docs.aws.amazon.com/botocore/latest/reference/services/glacier/client/exceptions/InsufficientCapacityException.html
                        if e.response['Error']['Code'] == 'InsufficientCapacityException':
                            print(f"\n WARNING: Expedited failed for {job_id} (Insufficient Capacity). Re-attempting via STANDARD retrieval.")
                            try:
                                # Reference:
                                # Read about Glacier initiate_job: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier/client/initiate_job.html
                                job_params["Tier"] = "Standard"
                                glacier_client.initiate_job(
                                    vaultName=VAULT_NAME,
                                    jobParameters=job_params
                                )
                                print(f" SUCCESS: Standard retrieval accepted for job: {job_id}")
                            except ClientError as fallback_e:
                                print(f" ERROR: Standard fallback failed for job {job_id}: {fallback_e}")
                                continue
                        else:
                            print(f" ERROR: Unexpected Glacier error for job {job_id}: {e}")
                            continue


                    table = dynamodb.Table(TABLE_NAME)
                    try:
                        # Reference:
                        # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
                        # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
                        table.update_item(
                            Key={'job_id': job_id},
                            UpdateExpression="SET job_status = :val",
                            ExpressionAttributeValues={':val': 'RESTORING'}
                        )
                        print(f" SUCCESS: Updated DynamoDB status to RESTORING for job: {job_id}")
                    except ClientError as e:
                        print(f" ERROR: DynamoDB Update Error for job {job_id}: {e.response['Error']['Message']}")

                    try:
                        # Reference:
                        # Read about SQS message delete: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/message/delete.html
                        message.delete()
                        print(f" SUCCESS: Removed message from SQS queue for job: {job_id}\n")
                    except ClientError as e:
                        print(f" ERROR: Failed to delete message from SQS: {e}\n")

                except Exception as e:
                    print(f" ERROR: Unexpected error processing individual message: {e}\n")

            return jsonify({"code": 200, "message": "Notification processed and SQS jobs initiated"}), 200

        except Exception as e:
            print(f" ERROR: SQS Polling Error: {e}\n")
            return jsonify({"code": 500, "error": str(e)}), 500

    else:
        print(f"WARNING: Received unknown SNS message type: {msg_type}")
        return jsonify({"code": 400, "error": "Unknown message type"}), 400


### EOF
