# config.py
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
#
# Set GAS web app configuration options based on environment
#
# ************************************************************************
#
# >>>>> MAKE CHANGES TO THIS FILE ONLY BELOW LINE 133 <<<<<<<
#
# ************************************************************************
##
__author__ = "Aman Panigrahi <amanpanigrahi2305@gmail.com>"

import boto3
import json
import os

from botocore.exceptions import ClientError

base_dir = os.path.abspath(os.path.dirname(__file__))

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
    GAS_LOG_LEVEL = os.environ.get("GAS_LOG_LEVEL", "INFO")
    GAS_LOG_FILE_PATH = os.environ.get("GAS_LOG_FILE_PATH", base_dir + "/log")
    GAS_LOG_FILE_NAME = os.environ.get("GAS_LOG_FILE_NAME", "gas.log")

    WSGI_SERVER = "werkzeug"
    CSRF_ENABLED = True

    # SSL Configuration - Replaced specific university domains with placeholders
    SSL_CERT_PATH = os.environ.get("SSL_CERT_PATH", "ssl/server.crt")
    SSL_KEY_PATH = os.environ.get("SSL_KEY_PATH", "ssl/server.key")

    AWS_PROFILE_NAME = os.environ.get("AWS_PROFILE_NAME", None)
    AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "us-east-1")

    # AWS Secrets Manager setup
    asm = boto3.client("secretsmanager", region_name=AWS_REGION_NAME)

    # 1. Retrieve Flask Secret Key
    try:
        asm_response = asm.get_secret_value(SecretId="gas/web_server")
        flask_secret = json.loads(asm_response["SecretString"])
        SECRET_KEY = flask_secret["flask_secret_key"]
    except Exception as e:
        SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-key-placeholder")

    # 2. Retrieve RDS Credentials
    try:
        asm_response = asm.get_secret_value(SecretId="rds/accounts_database")
        rds_secret = json.loads(asm_response["SecretString"])
        
        SQLALCHEMY_DATABASE_TABLE = os.environ.get("ACCOUNTS_DATABASE_TABLE", f"{iam_username}_accounts")
        SQLALCHEMY_DATABASE_URI = (
            f"postgresql://{rds_secret['username']}:{rds_secret['password']}"
            f"@{rds_secret['host']}:{rds_secret['port']}/{SQLALCHEMY_DATABASE_TABLE}"
        )
    except Exception as e:
        SQLALCHEMY_DATABASE_URI = "postgresql://user:pass@localhost/dbname"

    SQLALCHEMY_TRACK_MODIFICATIONS = True

    # 3. Retrieve Globus Auth Credentials
    try:
        asm_response = asm.get_secret_value(SecretId="globus/auth_client")
        globus_auth = json.loads(asm_response["SecretString"])
        GAS_CLIENT_ID = globus_auth["gas_client_id"]
        GAS_CLIENT_SECRET = globus_auth["gas_client_secret"]
    except Exception:
        GAS_CLIENT_ID = "<YOUR_GLOBUS_ID>"
        GAS_CLIENT_SECRET = "<YOUR_GLOBUS_SECRET>"

    GLOBUS_AUTH_LOGOUT_URI = "https://auth.globus.org/v2/web/logout"

    # --- Stripe Configuration (Sanitized) ---
    STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "<YOUR_STRIPE_PUBLIC_KEY>")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "<YOUR_STRIPE_SECRET_KEY>")
    STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "<YOUR_STRIPE_PRICE_ID>")

    AWS_SIGNED_REQUEST_EXPIRATION = 60

    # AWS S3 Parameters
    AWS_S3_INPUTS_BUCKET = os.environ.get("AWS_S3_INPUTS_BUCKET", "your-inputs-bucket")
    AWS_S3_RESULTS_BUCKET = os.environ.get("AWS_S3_RESULTS_BUCKET", "your-results-bucket")
    AWS_S3_KEY_PREFIX = f"{iam_username}/"
    AWS_S3_ACL = "private"
    AWS_S3_ENCRYPTION = "AES256"

    AWS_GLACIER_VAULT = os.environ.get("AWS_GLACIER_VAULT", "your-vault-name")

    # AWS SNS Topics (Replaced Account ID with <ACCOUNT_ID>)
    AWS_SNS_JOB_REQUEST_TOPIC = f"arn:aws:sns:{AWS_REGION_NAME}:<ACCOUNT_ID>:{iam_username}_job_requests"
    AWS_SNS_THAW_TOPIC = f"arn:aws:sns:{AWS_REGION_NAME}:<ACCOUNT_ID>:{iam_username}_job_thaw"

    # AWS SQS Queues
    AWS_SQS_REQUESTS_QUEUE_NAME = f"{iam_username}_job_requests"
    AWS_SQS_THAW_QUEUE_NAME = f"{iam_username}_job_thaw"

    # AWS DynamoDB
    AWS_DYNAMODB_ANNOTATIONS_TABLE = f"{iam_username}_annotations"

    # Email Settings
    MAIL_DEFAULT_SENDER = f"notifications@{iam_username}.com"

    FREE_USER_DATA_RETENTION = 300


class DevelopmentConfig(Config):
    DEBUG = True
    GAS_LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    DEBUG = False
    GAS_LOG_LEVEL = "INFO"
    SSL_CERT_PATH = (
        os.environ["SSL_CERT_PATH"]
        if ("SSL_CERT_PATH" in os.environ)
        else "/usr/local/src/ssl/ucmpcs.org.crt"
    )
    SSL_KEY_PATH = (
        os.environ["SSL_KEY_PATH"]
        if ("SSL_KEY_PATH" in os.environ)
        else "/usr/local/src/ssl/ucmpcs.org.key"
    )


### EOF
