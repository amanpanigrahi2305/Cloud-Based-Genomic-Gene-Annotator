# annotator.py
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
import sys
import time
import subprocess
import shutil
from botocore.exceptions import ClientError

# Get configuration
from configparser import ConfigParser, ExtendedInterpolation

config = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
base_path = os.path.dirname(os.path.abspath(__file__))
config.read("annotator_config.ini")

region = config['aws']['AwsRegionName']
s3 = boto3.client('s3', region_name=region)
sqs = boto3.client('sqs', region_name=region)
# Reference:
# Read about dynamodb table: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/index.html
dynamodb = boto3.resource('dynamodb', region_name=region)
table = dynamodb.Table(config['gas']['AnnotationsTable'])


"""Reads request messages from SQS and runs AnnTools as a subprocess.

Move existing annotator code here
"""


def handle_requests_queue():
    try:
        # Reference:
        # Read about sqs.receive_message and syntax used : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/receive_message.html#
        response = sqs.receive_message(
            QueueUrl=config['sqs']['JobRequestsQueueUrl'],
            MaxNumberOfMessages=int(config['sqs']['MaxMessages']),
            WaitTimeSeconds=int(config['sqs']['WaitTime'])
        )
    # Reference:
    # Read about time.sleep syntax and how it works for deplay :https://www.digitalocean.com/community/tutorials/python-time-sleep
    except ClientError as e:
        print(f"CRITICAL ERROR: Failure to receive messages: {e}")
        time.sleep(5)
        return

    if 'Messages' not in response:
        return

    for message in response['Messages']:
        try:
            # Reference:
            # Read about parse SQS json message: https://stackoverflow.com/questions/58191688/how-to-parse-sqs-json-message-with-python
            sns_wrapper = json.loads(message['Body'])
            job_msg = json.loads(sns_wrapper['Message'])
            if not job_msg or not all(
                    [job_msg.get('job_id'),
                     job_msg.get('s3_inputs_bucket'),
                     job_msg.get('s3_key_input_file'),
                    job_msg.get('input_file_name')]):
                print(f"Malformed message or missing parameters. Deleting message.")
                try:
                    # Reference:
                    # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                    # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                    sqs.delete_message(
                        QueueUrl=config['sqs']['JobRequestsQueueUrl'],
                        ReceiptHandle=message['ReceiptHandle']
                    )
                    continue
                except ClientError as e:
                    print(f"ERROR: Failure to delete message {message['MessageId']}: {e}")
                    continue

            job_id = job_msg.get('job_id')
            bucket_name = job_msg.get('s3_inputs_bucket')
            s3_key = job_msg.get('s3_key_input_file')
            input_file_name = job_msg.get('input_file_name')

            # Reference:
            # Read about endswith() syntax: https://www.w3schools.com/python/ref_string_endswith.asp
            # Read about lower() syntax: https://www.geeksforgeeks.org/python/case-insensitive-string-comparison-in-python/
            if not input_file_name.lower().endswith('.vcf'):
                print(f"Skipping invalid file: {input_file_name}")
                try:
                    # Reference:
                    # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                    # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                    sqs.delete_message(
                        QueueUrl=config['sqs']['JobRequestsQueueUrl'],
                        ReceiptHandle=message['ReceiptHandle']
                    )
                    continue
                except ClientError as e:
                    print(f"ERROR: Failure to delete message: {e}")
                    continue

            data_dir = os.path.join(base_path, "jobs")
            job_dir = os.path.join(data_dir, job_id)

            try:
                os.makedirs(job_dir, exist_ok=True)
            # Reference:
            # Read about OSError: https://www.geeksforgeeks.org/python/handling-oserror-exception-in-python/
            except OSError as e:
                print(f"Failed to create job directory: {str(e)}")
                continue

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
                continue

            # Reference: Read about subprocess.popen: https://stackoverflow.com/questions/12605498/how-to-use-subprocess-popen-python
            # https://docs.python.org/3/library/subprocess.html
            try:
                subprocess.Popen(['python3', 'run.py', local_input_path, job_id])
                print(f"Successfully spawned job: {job_id}")
            except Exception as e:
                print(f"Failed to spawn annotation process: {str(e)}")
                continue

            try:
                # Reference:
                # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
                # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
                table.update_item(
                    Key={'job_id': job_id},
                    UpdateExpression="SET job_status = :r",
                    ConditionExpression="job_status = :p",
                    ExpressionAttributeValues={
                        ':r': 'RUNNING',
                        ':p': 'PENDING'
                    }
                )

            # Reference:
            # Read about error handling: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html#programming-with-python-error-handling
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                print(f"Conditional update failed: Job {job_id} is not in PENDING state.")
                try:
                    # Reference:
                    # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                    # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                    sqs.delete_message(QueueUrl=config['sqs']['JobRequestsQueueUrl'], ReceiptHandle=message['ReceiptHandle'])
                    continue
                except ClientError as e:
                    print(f"ERROR: Failure to delete message {message.get('MessageId')}: {e}")
                    continue

            try:
                # Reference:
                # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                sqs.delete_message(
                    QueueUrl=config['sqs']['JobRequestsQueueUrl'],
                    ReceiptHandle=message['ReceiptHandle']
                )
            except ClientError as e:
                print(f"ERROR: Failure to delete message {message['MessageId']}: {e}")

        except Exception as e:
            print(f"Error processing message: {str(e)}")
            continue

def main():
    print("Annotator worker started. Polling for messages...")
    while True:
        handle_requests_queue()


if __name__ == "__main__":
    main()

### EOF
