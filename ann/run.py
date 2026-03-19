# run.py
#
# Runs the AnnTools pipeline
#
# NOTE: This file lives on the AnnTools instance and
# replaces the default AnnTools run.py
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##
__author__ = "Aman Panigrahi <amanpanigrahi2305@gmail.com>"

import sys
import time
import driver
import os
import boto3
import shutil
import json
from botocore.exceptions import ClientError

# Get configuration
from configparser import ConfigParser, ExtendedInterpolation

config = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
config.read("annotator_config.ini")

"""A rudimentary timer for coarse-grained profiling
"""


class Timer(object):
    def __init__(self, verbose=True):
        self.verbose = verbose

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.secs = self.end - self.start
        if self.verbose:
            print(f"Approximate runtime: {self.secs:.2f} seconds")


def main():
    if len(sys.argv) < 3:
        print("A valid .vcf file and job_id must be provided as input to this program.")
        return

    input_file_name = sys.argv[1]
    job_id = sys.argv[2]
    region = config['aws']['AwsRegionName']
    results_bucket = config['s3']['ResultsBucketName']

    with Timer():
        driver.run(input_file_name, "vcf")

    s3 = boto3.client('s3', region_name=region)
    # Reference:
    # Read about dynamodb table: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/index.html
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(config['gas']['AnnotationsTable'])
    sfn_client = boto3.client('stepfunctions', region_name=region)

    try:
        response = table.get_item(Key={'job_id': job_id})
        if 'Item' not in response:
            print(f"ERROR: Job {job_id} not found in DynamoDB.")
            return
        user_id = response['Item'].get('user_id')
    except Exception as e:
        print(f"ERROR: Job {job_id} not found in DB: {e}")
        return

    base_filename = os.path.basename(input_file_name)
    result_file = input_file_name.replace('.vcf', '.annot.vcf')
    log_file = input_file_name + ".count.log"
    prefix = config['s3']['KeyPrefix']
    s3_key_result = f"{prefix}{user_id}/{job_id}~{base_filename.replace('.vcf', '.annot.vcf')}"
    s3_key_log = f"{prefix}{user_id}/{job_id}~{base_filename}.count.log"

    try:
        # Reference:
        # Read about s3.upload_file: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/upload_file.html
        if os.path.exists(result_file):
            s3.upload_file(result_file, results_bucket, s3_key_result)

        # Reference:
        # Read about s3.upload_file: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/upload_file.html
        if os.path.exists(log_file):
            s3.upload_file(log_file, results_bucket, s3_key_log)

        # Reference:
        # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
        # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
        completion_time = int(time.time())
        try:
            table.update_item(
                Key={'job_id': job_id},
                UpdateExpression="""SET 
                                s3_results_bucket = :rb, 
                                s3_key_result_file = :rf, 
                                s3_key_log_file = :lf, 
                                complete_time = :ct, 
                                job_status = :js""",
                ExpressionAttributeValues={
                    ':rb': results_bucket,
                    ':rf': s3_key_result,
                    ':lf': s3_key_log,
                    ':ct': completion_time,
                    ':js': 'COMPLETED'
                }
            )
            print(f"Successfully updated DynamoDB for job: {job_id}")
        except ClientError as e:
            print(f"CRITICAL ERROR: Failed to update DynamoDB for job {job_id}: {e.response['Error']['Message']}")
            return
        except Exception as e:
            print(f"CRITICAL ERROR: Unexpected error during DB update for {job_id}: {str(e)}")
            return


        try:
            sfn_input = {
                "job_id": job_id,
                "user_id": user_id,
                "results_file": s3_key_result,
                "results_bucket": results_bucket
            }

            #Reference:
            # Read about .start_execution: https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/start_execution.html
            # Too start_execution syntax reference: https://www.freekb.net/Article?id=5402
            sfn_client.start_execution(
                stateMachineArn=config.get('sfn', 'ArchiveDelayStateMachineArn'),
                input=json.dumps(sfn_input)
            )
            print(f"Archival timer (180s) started for job: {job_id}")
        except ClientError as e:
            print(f"Warning: Step Function failed to start: {e.response['Error']['Message']}")
        except Exception as e:
            print(f"Warning: Unexpected error starting Step Function: {str(e)}")

        try:
            sns_client = boto3.client('sns', region_name=region)
            message_data = {
                "job_id": job_id,
                "user_id": user_id,
                "complete_time": completion_time
            }
            # Reference:
            # Read about .publish : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns/client/publish.html
            # Read about json.dumps : https://www.geeksforgeeks.org/python/json-dumps-in-python/
            sns_client.publish(
                TopicArn=config['sns']['JobResultsTopicArn'],
                Message=json.dumps(message_data)
            )
            print(f"Notification published for job: {job_id}")
        except ClientError as e:
            print(f"Warning: Job completed but SNS notification failed: {e.response['Error']['Message']}")
        except Exception as sns_err:
            print(f"Warning: Unexpected error during SNS publish: {str(sns_err)}")

        job_dir = os.path.dirname(input_file_name)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
            print(f"Successfully processed and uploaded job: {job_id}")

    except ClientError as e:
        print(f"AWS Service Error: {e.response['Error']['Message']}")
    except OSError as e:
        print(f"Local File Error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    main()

### EOF
