# annotator_webhook.py
#
# Modified to run as a web server that can be called by SNS to process jobs
# Run using: python annotator_webhook.py
#
# NOTE: This file lives on the AnnTools instance
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##
__author__ = "Aman Panigrahi"

import boto3
import json
import os
import subprocess
import shutil
import requests
from flask import Flask, jsonify, request
from botocore.exceptions import ClientError

app = Flask(__name__)
app.url_map.strict_slashes = False

# Get configuration and add to Flask app object
environment = "annotator_webhook_config.Config"
app.config.from_object(environment)

region = app.config['AWS_REGION_NAME']
s3 = boto3.client('s3', region_name=region)
# Reference:
# Read about dynamodb table: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/index.html
dynamodb = boto3.resource('dynamodb', region_name=region)
table = dynamodb.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])

@app.route("/", methods=["GET"])
def annotator_webhook():

    return ("Annotator webhook; POST job to /process-job-request"), 200


"""
Receives request from SNS; queries job queue and processes message.
Reads request messages from SQS and runs AnnTools as a subprocess.
Updates the annotations database with the status of the request.
"""


@app.route("/process-job-request", methods=["POST"])
def annotate():
    try:
        sns_msg = json.loads(request.data)
    # Reference:
    # Took syntax reference on how to catch multiple exception in one line: https://www.geeksforgeeks.org/python/multiple-exception-handling-in-python/
    # Read about ValueError and KeyError and there usage: https://www.geeksforgeeks.org/python/json-parsing-errors-in-python/
    except (ValueError, TypeError):
        return jsonify({"code": 400, "message": "Invalid JSON"}), 400

    # Reference:
    # Read about x-amz-sns-message-type : https://docs.aws.amazon.com/sns/latest/dg/http-header.html
    msg_type = request.headers.get('x-amz-sns-message-type')

    # Reference:
    # Read about SubscriptionConfirmation and SubscribeURL: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
    # Took .net syntax reference for SubscriptionConfirmation and SubscribeURL and convert it to python: https://stackoverflow.com/questions/15079829/example-sns-subscription-confirmation-using-aws-net-sdk
    if msg_type == 'SubscriptionConfirmation':
        subscribe_url = sns_msg.get('SubscribeURL')
        if subscribe_url:
            requests.get(subscribe_url)
            print("Successfully confirmed SNS subscription.")
            return jsonify({"code": 200, "message": "Subscription confirmed"}), 200

    if msg_type == 'Notification':
        try:
            job_msg = json.loads(sns_msg['Message'])

            if not job_msg or not all([
                job_msg.get('job_id'),
                job_msg.get('s3_inputs_bucket'),
                job_msg.get('s3_key_input_file'),
                job_msg.get('input_file_name')
            ]):
                print(f"Malformed message parameters. Attempting to delete message.")
                return jsonify({"code": 400, "message": "Malformed message"}), 400

            job_id = job_msg.get('job_id')
            bucket_name = job_msg.get('s3_inputs_bucket')
            s3_key = job_msg.get('s3_key_input_file')
            input_file_name = job_msg.get('input_file_name')

            # Reference:
            # Read about endswith() syntax: https://www.w3schools.com/python/ref_string_endswith.asp
            # Read about lower() syntax: https://www.geeksforgeeks.org/python/case-insensitive-string-comparison-in-python/
            if not input_file_name.lower().endswith('.vcf'):
                print(f"Skipping invalid file type: {input_file_name}")
                return jsonify({"code": 400, "message": "Invalid file type"}), 400

            job_dir = os.path.join(app.config['ANNOTATOR_JOBS_DIR'], job_id)
            try:
                os.makedirs(job_dir, exist_ok=True)
            # Reference:
            # Read about OSError: https://www.geeksforgeeks.org/python/handling-oserror-exception-in-python/
            except OSError as e:
                print(f"Failed to create job directory: {str(e)}")
                return jsonify({"code": 500, "message": "Directory creation failed"}), 500

            local_input_path = os.path.join(job_dir, input_file_name)

            try:
                # Reference:
                # Read about download_file: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/download_file.html
                s3.download_file(bucket_name, s3_key, local_input_path)
            # Reference:
            # Took Reference to use client error: https://stackoverflow.com/questions/33068055/how-to-handle-errors-with-boto3
            except ClientError as e:
                if os.path.exists(job_dir):
                    # Reference:
                    # Read about which remove syntax should be used : https://stackoverflow.com/questions/62244556/is-os-removeos-rmdir-better-then-shutil-rmtree
                    # More about shutil.rmtree: https://note.nkmk.me/en/python-os-remove-rmdir-removedirs-shutil-rmtree/
                    shutil.rmtree(job_dir)
                print(f"S3 Download Error: {e.response['Error']['Message']}")
                return jsonify({"code": 500, "message": "S3 download failed"}), 500

            # Reference: Read about subprocess.popen: https://stackoverflow.com/questions/12605498/how-to-use-subprocess-popen-python
            # https://docs.python.org/3/library/subprocess.html
            try:
                subprocess.Popen(['python3', 'run.py', local_input_path, job_id])
                print(f"Successfully spawned job: {job_id}")
            except Exception as e:
                print(f"Failed to spawn annotation process: {str(e)}")
                return jsonify({"code": 500, "message": "Subprocess spawn failed"}), 500

            try:
                # Reference:
                # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
                # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
                table.update_item(
                    Key={'job_id': job_id},
                    UpdateExpression="SET job_status = :r",
                    ConditionExpression="job_status = :p",
                    ExpressionAttributeValues={':r': 'RUNNING', ':p': 'PENDING'}
                )
            # Reference:
            # Read about error handling: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html#programming-with-python-error-handling
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                print(f"Conditional update failed: Job {job_id} is not in PENDING state.")
                return jsonify({"code": 409, "message": "Job status conflict"}), 409

        except Exception as e:
            print(f"Unexpected error in message processing logic: {str(e)}")
            return jsonify({"code": 500, "message": "Internal processing error"}), 500

    return (
        jsonify(
            {
                "code": 201,
                "message": "Annotation job request processed."
            }
        ),
        201,
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)

### EOF
