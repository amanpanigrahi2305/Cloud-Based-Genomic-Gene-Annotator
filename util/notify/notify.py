# notify.py
#
# Notify user of job completion via email
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##
__author__ = "Aman Panigrahi <amanpanigrahi2305@gmail.com>"

import boto3
import json
import os
import sys
import time

from botocore.exceptions import ClientError

# Import utility helpers
sys.path.insert(1, os.path.realpath(os.path.pardir))
import helpers

# Get configuration
from configparser import ConfigParser, ExtendedInterpolation

config = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
config.read("../util_config.ini")
config.read("notify_config.ini")

"""A12
Reads result messages from SQS and sends notification emails.
"""


def handle_results_queue(sqs):
    try:
        # Reference:
        # Read about sqs.receive_message and syntax used : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/receive_message.html#
        response = sqs.receive_message(
            QueueUrl=config['sqs']['JobResultsQueueUrl'],
            MaxNumberOfMessages=int(config['sqs']['MaxMessages']),
            WaitTimeSeconds=int(config['sqs']['WaitTime'])
        )
    except ClientError as e:
        print(f"Error receiving messages from SQS: {e}")
        return

    if 'Messages' not in response:
        print(f"ERROR: Messages not in response.")
        return

    if 'Messages' in response:
        for message in response['Messages']:
            try:
                try:
                    # Reference:
                    # Read about parse SQS json message: https://stackoverflow.com/questions/58191688/how-to-parse-sqs-json-message-with-python
                    sqs_body = json.loads(message['Body'])
                    job_data = json.loads(sqs_body['Message'])
                # Reference:
                # Took syntax reference on how to catch multiple exception in one line: https://www.geeksforgeeks.org/python/multiple-exception-handling-in-python/
                # Read about ValueError and KeyError and there usage: https://www.geeksforgeeks.org/python/json-parsing-errors-in-python/
                except (ValueError, KeyError) as e:
                    print(f"ERROR: Skipping malformed message. Parsing failed: {e}")
                    # Reference:
                    # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                    # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                    sqs.delete_message(QueueUrl=config['sqs']['JobResultsQueueUrl'],
                                       ReceiptHandle=message['ReceiptHandle'])
                    continue

                job_id = job_data.get('job_id')
                user_id = job_data.get('user_id')
                raw_time = job_data.get('complete_time')
                if not all([job_id, user_id, raw_time]):
                    print(f"ERROR: Message missing required fields. Job: {job_id}")
                    continue

                try:
                    user_profile = helpers.get_user_profile(id=user_id)
                    user_email = user_profile.get('email')
                except Exception as e:
                    print(f"RETRYING: Error for fetching user detail for user: {user_id}: {e}")
                    continue

                if user_email:
                    complete_time = time.strftime('%Y-%m-%d %H:%M', time.localtime(raw_time))
                    subject = f"Results available for job {job_id}"
                    link = f"{config['gas']['WebAppBaseUrl']}/annotations/{job_id}"
                    body = (
                        f"Your annotation job completed at {complete_time}.\n\n"
                        f" Click here to view job details and results:\n"
                        f"{link}"
                    )

                    try:
                        helpers.send_email_ses(
                            recipients=user_email,
                            subject=subject,
                            body=body
                        )
                        print(f"Successfully sent notification to {user_email} for job {job_id}")

                        try:
                            # Reference:
                            # Read about .delete_message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs/client/delete_message.html
                            # Took Syntax reference: https://stackoverflow.com/questions/54779716/receiving-and-deleting-messages-from-sqs-using-boto3
                            sqs.delete_message(
                                QueueUrl=config['sqs']['JobResultsQueueUrl'],
                                ReceiptHandle=message['ReceiptHandle']
                            )
                        except ClientError as delete_err:
                            print(f"ERROR: Email sent but failed to delete message: {delete_err}")

                    except ClientError as ses_err:
                        print(f"RETRYING: SES service error for job {job_id}: {ses_err.response['Error']['Message']}")
                    except Exception as email_err:
                        print(f"RETRYING: Unexpected error sending email for job {job_id}: {email_err}")

            except Exception as e:
                print(f"Failed to process message: {e}")
                continue


def main():
    region = config['aws']['AwsRegionName']
    sqs = boto3.client('sqs', region_name=region)
    print("Notification service is running and polling for results...")
    while True:
        handle_results_queue(sqs)

if __name__ == "__main__":
    main()

### EOF
