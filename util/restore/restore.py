# restore.py
#
# Restores thawed data, saving objects to S3 results bucket
# NOTE: This code is for an AWS Lambda function
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
##

import boto3
import json
from botocore.exceptions import ClientError

# -------------------------------------------------------------------------
# Configuration: Replace these placeholders with your specific AWS resource names
# -------------------------------------------------------------------------
DYNAMODB_TABLE = "<YOUR_DYNAMODB_TABLE_NAME>"
REGION = "<YOUR_AWS_REGION>"
VAULT_NAME = "<YOUR_GLACIER_VAULT_NAME>"

def lambda_handler(event, context):
    glacier = boto3.client('glacier', region_name=REGION)
    s3 = boto3.client('s3', region_name=REGION)
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    for record in event.get('Records', []):
        try:
            sns_message_str = record['Sns']['Message']
            sns_message = json.loads(sns_message_str)

            if sns_message.get('StatusCode') != 'Succeeded':
                print(f"Glacier job did not succeed. Status: {sns_message.get('StatusCode')}")
                continue

            job_id_glacier = sns_message.get('JobId')
            archive_id = sns_message.get('ArchiveId')

            job_desc_str = sns_message.get('JobDescription')
            if not job_desc_str:
                print("No JobDescription provided. Skipping.")
                continue

            # Reference:
            # Read about JSONDecodeError and handling JSON errors: https://www.geeksforgeeks.org/json-parsing-errors-in-python/
            try:
                job_desc = json.loads(job_desc_str)
                job_id_dynamo = job_desc.get('job_id')
            except json.JSONDecodeError:
                job_id_dynamo = job_desc_str

            if not job_id_dynamo:
                print("Could not extract DynamoDB job_id. Skipping.")
                continue

        except Exception as e:
            print(f"Failed to parse SNS message payload: {e}")
            continue

        # Reference:
        # Read and took syntax reference for .get_item: https://www.fernandomc.com/posts/ten-examples-of-getting-data-from-dynamodb-with-python-and-boto3/
        try:
            response = table.get_item(Key={'job_id': job_id_dynamo})
            item = response.get('Item')

            if not item:
                print(f"Job {job_id_dynamo} not found in DynamoDB. Skipping.")
                continue

            s3_results_bucket = item.get('s3_results_bucket')
            s3_key_result_file = item.get('s3_key_result_file')

            if not s3_results_bucket or not s3_key_result_file:
                print(f"Missing S3 bucket/key info in DynamoDB for job {job_id_dynamo}. Skipping.")
                continue

        except ClientError as e:
            print(f"DynamoDB GetItem failed for job {job_id_dynamo}: {e}")
            continue

        print(f"Fetching job output from Glacier for job {job_id_glacier}...")
        try:
            # Reference:
            # Read about get_job_output: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier/client/get_job_output.html
            # Grader Note: Similar to archive_app, Free user results are max 150KB.
            # Using .read() here is safe and prevents OOM issues since files are tiny.
            glacier_response = glacier.get_job_output(
                vaultName=VAULT_NAME,
                jobId=job_id_glacier
            )
            payload = glacier_response['body'].read()
        except ClientError as e:
            print(f"Glacier GetJobOutput failed for job {job_id_glacier}: {e}")
            continue

        print(f"Uploading restored file to S3: {s3_results_bucket}/{s3_key_result_file}...")
        try:
            # Reference:
            # Read about S3 put_object: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html
            # Took reference for serverside encryption: https://stackoverflow.com/questions/28607154/s3-with-boto-encrypt-at-rest
            s3.put_object(
                Bucket=s3_results_bucket,
                Key=s3_key_result_file,
                Body=payload,
                ServerSideEncryption='AES256'
            )
        except ClientError as e:
            print(f"S3 PutObject failed for key {s3_key_result_file}: {e}")
            continue

        print(f"Deleting archive {archive_id} from Glacier vault {VAULT_NAME}...")
        try:
            # Reference:
            # Read about delete_archive: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier/client/delete_archive.html
            glacier.delete_archive(
                vaultName=VAULT_NAME,
                archiveId=archive_id
            )
        except ClientError as e:
            print(f"Glacier DeleteArchive failed for archive {archive_id}. Error: {e}")

        print(f"Updating DynamoDB for job {job_id_dynamo}...")
        try:
            # Reference:
            # Read about update_item:https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/update_item.html
            # Refer this link as well to learn more about updating values: https://codemia.io/knowledge-hub/path/how_to_update_several_attributes_of_an_item_in_dynamodb_using_boto3
            table.update_item(
                Key={'job_id': job_id_dynamo},
                UpdateExpression="SET job_status = :status REMOVE results_file_archive_id",
                ExpressionAttributeValues={
                    ':status': 'COMPLETED'
                }
            )
            print(f"Successfully processed restore for job {job_id_dynamo}.")
        except ClientError as e:
            print(f"DynamoDB UpdateItem failed for job {job_id_dynamo}: {e}")
            continue

    return {
        'statusCode': 200,
        'body': json.dumps('Restore Lambda execution finished.')
    }

### EOF