# views.py
#
# Copyright (C) 2025-2026 Aman Panigrahi
# University of Chicago
#
# Application logic for the GAS
#
##
__author__ = "Aman Panigrahi <amanpanigrahi2305@gmail.com>"

import uuid
import time
import json
from datetime import datetime

import boto3
from botocore.client import Config
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from flask import abort, flash, redirect, render_template, request, session, url_for

from app import app, db
from decorators import authenticated, is_premium
from urllib.parse import unquote

"""Start annotation request
Create the required AWS S3 policy document and render a form for
uploading an annotation input file using the policy document

Note: You are welcome to use this code instead of your own
but you can replace the code below with your own if you prefer.
"""


@app.route("/annotate", methods=["GET"])
@authenticated
def annotate():
    # Open a connection to the S3 service
    s3 = boto3.client(
        "s3",
        region_name=app.config["AWS_REGION_NAME"],
        config=Config(signature_version="s3v4"),
    )

    bucket_name = app.config["AWS_S3_INPUTS_BUCKET"]
    user_id = session["primary_identity"]

    # Generate unique ID to be used as S3 key (name)
    job_id = str(uuid.uuid4())
    key_name = (
        app.config["AWS_S3_KEY_PREFIX"]
        + user_id
        + "/"
        + job_id
        + "~${filename}"
    )

    # Create the redirect URL
    redirect_url = str(request.url) + "/job"

    # Define policy conditions
    encryption = app.config["AWS_S3_ENCRYPTION"]
    acl = app.config["AWS_S3_ACL"]
    fields = {
        "success_action_redirect": redirect_url,
        "x-amz-server-side-encryption": encryption,
        "acl": acl,
        "csrf_token": app.config["SECRET_KEY"],
    }
    conditions = [
        ["starts-with", "$success_action_redirect", redirect_url],
        {"x-amz-server-side-encryption": encryption},
        {"acl": acl},
        ["starts-with", "$csrf_token", ""],
    ]

    # Generate the presigned POST call
    try:
        presigned_post = s3.generate_presigned_post(
            Bucket=bucket_name,
            Key=key_name,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=app.config["AWS_SIGNED_REQUEST_EXPIRATION"],
        )
    except ClientError as e:
        app.logger.error(f"Unable to generate presigned URL for upload: {e}")
        return abort(500)

    # Render the upload form which will parse/submit the presigned POST
    return render_template(
        "annotate.html", s3_post=presigned_post, role=session["role"]
    )


"""Fires off an annotation job
Accepts the S3 redirect GET request, parses it to extract 
required info, saves a job item to the database, and then
publishes a notification for the annotator service.

Note: Update/replace the code below with your own from previous
homework assignments
"""


@app.route("/annotate/job", methods=["GET"])
@authenticated
def create_annotation_job_request():

    region = app.config["AWS_REGION_NAME"]

    # Parse redirect URL query parameters for S3 object info
    bucket_name = request.args.get("bucket")
    s3_key = request.args.get("key")

    if not bucket_name or not s3_key:
        return abort(400)

    #Reference:
    #Read about delimiter: https://stackoverflow.com/questions/3475251/split-a-string-by-a-delimiter-in-python
    #Read about negative indexing: https://www.geeksforgeeks.org/python/what-is-negative-indexing-in-python/
    s3_key_decoded = unquote(s3_key)
    try:
        filename_part = s3_key_decoded.split('/')[-1]
        job_id, input_file_name = filename_part.split('~')
    except Exception as e:
        app.logger.error(f"Failed to parse S3 key: {s3_key}")
        return abort(400)

    user_id = session.get('primary_identity')

    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])

    #Reference:
    # Read about .put_item: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/put_item.html
    # Read more about put_item: https://www.beabetterdev.com/2022/02/22/how-to-insert-into-a-dynamodb-table-with-boto3/
    data = {
        "job_id": job_id,
        "user_id": user_id,
        "input_file_name": input_file_name,
        "s3_inputs_bucket": bucket_name,
        "s3_key_input_file": s3_key,
        "submit_time": int(time.time()),
        "job_status": "PENDING"
    }

    try:
        table.put_item(Item=data)
    #Reference:
    #Took Reference to use client error: https://stackoverflow.com/questions/33068055/how-to-handle-errors-with-boto3
    except ClientError as e:
        app.logger.error(f"DynamoDB Error: {e.response['Error']['Message']}")
        return abort(500)

    sns = boto3.client('sns', region_name=region)
    # Reference:
    # Read about .publish : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns/client/publish.html
    # Took Syntax Reference: https://stackoverflow.com/questions/35071549/json-encoding-error-publishing-sns-message-with-boto-3
    # Read about json.dumps : https://www.geeksforgeeks.org/python/json-dumps-in-python/
    try:
        sns.publish(
            TopicArn=app.config["AWS_SNS_JOB_REQUEST_TOPIC"],
            Message=json.dumps(data)
        )
    except ClientError as e:
        app.logger.error(f"SNS Publish Error: {e.response['Error']['Message']}")
        return abort(500)

    return render_template("annotate_confirm.html", job_id=job_id)


"""List all annotations for the user
"""


@app.route("/annotations", methods=["GET"])
@authenticated
def annotations_list():
    user_id = session.get('primary_identity')
    dynamodb = boto3.resource('dynamodb', region_name=app.config["AWS_REGION_NAME"])
    table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])

    try:
        #Reference:
        # Read about .query: https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/query.html
        # Took syntax reference for using query: https://www.fernandomc.com/posts/ten-examples-of-getting-data-from-dynamodb-with-python-and-boto3/
        response = table.query(
            IndexName='user_id_index',
            KeyConditionExpression=Key('user_id').eq(user_id)
        )
        items = response.get('Items', [])
    except ClientError as e:
        app.logger.error(f"DynamoDB Query Error: {e}")
        return abort(500)

    for item in items:
        if 'submit_time' in item:
            #Reference:
            # Took syntax reference for fromtimestamp: https://pandas.pydata.org/docs/reference/api/pandas.Timestamp.fromtimestamp.html
            dt = datetime.fromtimestamp(int(item['submit_time']))
            item['formatted_submit_time'] = dt.strftime('%Y-%m-%d @ %H:%M:%S')

    return render_template("annotations.html", annotations=items)


"""Display details of a specific annotation job
"""


@app.route("/annotations/<id>", methods=["GET"])
@authenticated
def annotation_details(id):
    s3_client = boto3.client(
        "s3",
        region_name=app.config["AWS_REGION_NAME"],
        config=Config(signature_version="s3v4"),
    )

    user_id = session.get('primary_identity')

    dynamodb = boto3.resource('dynamodb', region_name=app.config["AWS_REGION_NAME"])
    table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])

    try:
        #Reference:
        # Read and took syntax reference for .get_item: https://www.fernandomc.com/posts/ten-examples-of-getting-data-from-dynamodb-with-python-and-boto3/
        response = table.get_item(Key={'job_id': id})
    except ClientError as e:
        app.logger.error(f"DynamoDB GetItem Error: {e}")
        return abort(500)

    if 'Item' not in response:
        return abort(404)

    item = response['Item']

    if item.get('user_id') != user_id:
        app.logger.warning(f"Unauthorized access attempt by {user_id} for job {id}")
        return abort(403)

    if 'submit_time' in item:
        # Reference:
        # Took syntax reference for fromtimestamp: https://pandas.pydata.org/docs/reference/api/pandas.Timestamp.fromtimestamp.html
        item['f_submit_time'] = datetime.fromtimestamp(int(item['submit_time'])).strftime('%Y-%m-%d @ %H:%M:%S')

    if 'complete_time' in item:
        # Reference:
        # Took syntax reference for fromtimestamp: https://pandas.pydata.org/docs/reference/api/pandas.Timestamp.fromtimestamp.html
        item['f_complete_time'] = datetime.fromtimestamp(int(item['complete_time'])).strftime('%Y-%m-%d @ %H:%M:%S')

    try:
        #Reference:
        # Read and took syntax reference regarding .generate_presigned_url: https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html
        input_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': item['s3_inputs_bucket'], 'Key': item['s3_key_input_file']},
            ExpiresIn=300
        )
        item['input_file_url'] = input_url

        if item.get('job_status') == 'RESTORING':
            item['results_file_name'] = "File is being restored; please check back later"
            item['is_archived'] = True

        elif item.get('job_status') == 'COMPLETED':
            if 'results_file_archive_id' in item:
                item['is_archived'] = True
            else:
                # Reference:
                # Read and took syntax reference regarding .generate_presigned_url: https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html
                result_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': item['s3_results_bucket'], 'Key': item['s3_key_result_file']},
                    ExpiresIn=300
                )
                item['result_file_url'] = result_url
                item['is_archived'] = False
    except ClientError as e:
        app.logger.error(f"S3 URL Generation Error: {e}")

    return render_template("annotation.html", annotation=item)


"""Display the log file contents for an annotation job
"""


@app.route("/annotations/<id>/log", methods=["GET"])
@authenticated
def annotation_log(id):
    s3_client = boto3.client(
        "s3",
        region_name=app.config["AWS_REGION_NAME"],
        config=Config(signature_version="s3v4"),
    )

    user_id = session.get('primary_identity')

    dynamodb = boto3.resource('dynamodb', region_name=app.config["AWS_REGION_NAME"])
    table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])

    # Reference:
    # Read and took syntax reference for .get_item: https://www.fernandomc.com/posts/ten-examples-of-getting-data-from-dynamodb-with-python-and-boto3/
    response = table.get_item(Key={'job_id': id})
    if 'Item' not in response:
        return abort(404)

    item = response['Item']

    if item.get('user_id') != user_id:
        return abort(403)

    try:
        #Reference:
        # Read about .get_object: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html
        # Took code reference: https://github.com/boto/boto3/blob/develop/boto3/examples/s3.rst
        log_obj = s3_client.get_object(
            Bucket=item['s3_results_bucket'],
            Key=item['s3_key_log_file']
        )
        #Reference:
        #Read about and took syntax reference to decode from the body: https://stackoverflow.com/questions/31976273/open-s3-object-as-a-string-with-boto3
        log_content = log_obj['Body'].read().decode('utf-8')
    except ClientError as e:
        app.logger.error(f"Failed to fetch log from S3: {e}")
        return abort(500)
    
    return render_template("view_log.html", job_id=id, log_content=log_content)


"""Subscription management handler
"""
import stripe
from auth import update_profile

# Reference:
# Syntax Reference: https://docs.stripe.com/api/authentication?lang=python
stripe.api_key = app.config.get('STRIPE_SECRET_KEY')


@app.route("/subscribe", methods=["GET", "POST"])
@authenticated
def subscribe():
    if request.method == "GET":
        # Reference:
        # Read about Flask sessions and syntax reference : https://www.geeksforgeeks.org/how-to-use-flask-session-in-python-flask/
        if session.get('role') == "premium_user":
            return redirect(url_for('profile'))

        return render_template("subscribe.html")

    elif request.method == "POST":
        stripe_token = request.form.get('stripe_token')
        if not stripe_token:
            flash("Missing payment token. Please try again.", "danger")
            return redirect(url_for('subscribe'))

        try:
            # Reference:
            # Read about and took syntax reference for creating a stripe customer: https://docs.stripe.com/api/customers/create?lang=python
            customer = stripe.Customer.create(
                card=stripe_token,
                email=session.get('email'),
                name=session.get('name')
            )
            # Reference:
            # Read about and took syntax reference for creating a stripe subscription in python: https://docs.stripe.com/api/subscriptions/create?lang=python
            stripe.Subscription.create(
                customer=customer.id,
                items=[{"price": app.config['STRIPE_PRICE_ID']}],
            )
        # Reference:
        # Read about stripe error and took reference on how to handle Stripe errors : https://docs.stripe.com/api/errors/handling?lang=python
        except stripe.error.StripeError as e:
            app.logger.error(f"Stripe error: {str(e)}")
            #Reference:
            # Read about Flashing With Categories: https://flask.palletsprojects.com/en/stable/patterns/flashing/#flashing-with-categories
            # Read about how to flash success and danger with different messages in flask :https://stackoverflow.com/questions/51273822/how-to-flash-success-and-danger-with-different-messages-in-flask/51274004
            # more reference for flask Message flashing :https://www.geeksforgeeks.org/python/flask-message-flashing/
            flash(f"Payment failed: {e.user_message if hasattr(e, 'user_message') else 'Please try again.'}", "danger")
            return redirect(url_for('subscribe'))

        try:
            update_profile(
                identity_id=session['primary_identity'],
                role="premium_user"
            )
            session['role'] = "premium_user"

        except Exception as e:
            app.logger.critical(f"DATABASE UPDATE FAILED FOR PREMIUM USER {session.get('email')}: {str(e)}")
            # Reference:
            # Read about Flashing With Categories: https://flask.palletsprojects.com/en/stable/patterns/flashing/#flashing-with-categories
            # Read about how to flash success and danger with different messages in flask :https://stackoverflow.com/questions/51273822/how-to-flash-success-and-danger-with-different-messages-in-flask/51274004
            # more reference for flask Message flashing :https://www.geeksforgeeks.org/python/flask-message-flashing/
            flash( "Your payment was successful, but there was a delay updating your profile. Please refresh in a moment.", "warning")
            return render_template("subscribe_confirm.html", stripe_customer_id=customer.id)

        user_id = session.get('primary_identity')
        sns = boto3.client('sns', region_name=app.config["AWS_REGION_NAME"])
        dynamodb = boto3.resource('dynamodb', region_name=app.config["AWS_REGION_NAME"])
        table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])

        try:
            # Reference:
            # Read about .query: https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/query.html
            # Took syntax reference for using query: https://www.fernandomc.com/posts/ten-examples-of-getting-data-from-dynamodb-with-python-and-boto3/
            # Read about FilterExpression: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.FilterExpression.html
            # Read about Boto3 DynamoDB Conditions (Attr().exists()): https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/dynamodb.html#boto3.dynamodb.conditions.Attr.exists
            response = table.query(
                IndexName='user_id_index',
                KeyConditionExpression=Key('user_id').eq(user_id),
                FilterExpression=boto3.dynamodb.conditions.Attr('results_file_archive_id').exists()
            )
            archived_items = response.get('Items', [])

        except ClientError as e:
            # Reference:
            # Read about parsing Boto3 ClientError responses: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/error-handling.html#parsing-error-responses
            app.logger.error(f"DynamoDB query failed during restoration trigger: {e.response['Error']['Message']}")
            archived_items = []

        for item in archived_items:
            thaw_msg = {
                "job_id": item['job_id'],
                "results_file_archive_id": item['results_file_archive_id'],
                "user_id": user_id,
                "s3_key_results": item.get('s3_key_result_file')
            }

            try:
                # Reference:
                # Read about .publish : https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns/client/publish.html
                # Took Syntax Reference: https://stackoverflow.com/questions/35071549/json-encoding-error-publishing-sns-message-with-boto-3
                # Read about json.dumps : https://www.geeksforgeeks.org/python/json-dumps-in-python/
                sns.publish(
                    TopicArn=app.config["AWS_SNS_THAW_TOPIC"],
                    Message=json.dumps(thaw_msg)
                )
            except ClientError as e:
                app.logger.error(f"SNS publish failed for thawing job {item['job_id']}: {e.response['Error']['Message']}")

        return render_template("subscribe_confirm.html", stripe_customer_id=customer.id)


"""DO NOT CHANGE CODE BELOW THIS LINE
*******************************************************************************
"""

"""Set premium_user role
"""


@app.route("/make-me-premium", methods=["GET"])
@authenticated
def make_me_premium():
    # Hacky way to set the user's role to a premium user; simplifies testing
    update_profile(identity_id=session["primary_identity"], role="premium_user")
    return redirect(url_for("profile"))


"""Reset subscription
"""


@app.route("/unsubscribe", methods=["GET"])
@authenticated
def unsubscribe():
    # Hacky way to reset the user's role to a free user; simplifies testing
    update_profile(identity_id=session["primary_identity"], role="free_user")
    return redirect(url_for("profile"))


"""Home page
"""


@app.route("/", methods=["GET"])
def home():
    return render_template("home.html"), 200


"""Login page; send user to Globus Auth
"""


@app.route("/login", methods=["GET"])
def login():
    app.logger.info(f"Login attempted from IP {request.remote_addr}")
    # If user requested a specific page, save it session for redirect after auth
    if request.args.get("next"):
        session["next"] = request.args.get("next")
    return redirect(url_for("authcallback"))


"""404 error handler
"""


@app.errorhandler(404)
def page_not_found(e):
    return (
        render_template(
            "error.html",
            title="Page not found",
            alert_level="warning",
            message="The page you tried to reach does not exist. \
      Please check the URL and try again.",
        ),
        404,
    )


"""403 error handler
"""


@app.errorhandler(403)
def forbidden(e):
    return (
        render_template(
            "error.html",
            title="Not authorized",
            alert_level="danger",
            message="You are not authorized to access this page. \
      If you think you deserve to be granted access, please contact the \
      supreme leader of the mutating genome revolutionary party.",
        ),
        403,
    )


"""405 error handler
"""


@app.errorhandler(405)
def not_allowed(e):
    return (
        render_template(
            "error.html",
            title="Not allowed",
            alert_level="warning",
            message="You attempted an operation that's not allowed; \
      get your act together, hacker!",
        ),
        405,
    )


"""500 error handler
"""


@app.errorhandler(500)
def internal_error(error):
    return (
        render_template(
            "error.html",
            title="Server error",
            alert_level="danger",
            message="The server encountered an error and could \
      not process your request.",
        ),
        500,
    )


"""CSRF error handler
"""


from flask_wtf.csrf import CSRFError


@app.errorhandler(CSRFError)
def csrf_error(error):
    return (
        render_template(
            "error.html",
            title="CSRF error",
            alert_level="danger",
            message=f"Cross-Site Request Forgery error detected: {error.description}",
        ),
        400,
    )


### EOF
