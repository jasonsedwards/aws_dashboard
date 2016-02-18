# -*- coding:utf-8 -*-

import boto.ec2
import boto.iam
from flask import Flask, Response
import logging
import os
import random
import re
import sys


# ---- Make a connection to each region.
DEBUG = 0
UNIVERSAL_REGION = 'universal'
EU_WEST_1 = 'eu-west-1'
US_EAST_1 = 'us-east-1'
connections = {}
connections[EU_WEST_1] = {
                          'ec2' : boto.ec2.connect_to_region(EU_WEST_1, debug=DEBUG),
                         }
connections[US_EAST_1] = {
                          'ec2' : boto.ec2.connect_to_region(US_EAST_1, debug=DEBUG),
                         }
connections[UNIVERSAL_REGION] = {
                          'iam' : boto.iam.connect_to_region(UNIVERSAL_REGION, debug=DEBUG),
                         }

app = Flask(__name__)


def exponential_backoff(conn, api_call, *args, **kwargs):
  num_retries = 6
  try_count = 1
  total_sleep = 0
  response = None

  while try_count <= num_retries:
    next_sleep = random.random() + (2 ** try_count)
    error = ""
    try:
      response = getattr(conn, api_call)(*args, **kwargs)
    except Exception:
      error = traceback.format_exc()
      if "Throttling" not in error:
        raise
    if "400" and "Throttling" in error:
      logging.error(
          """ACTION=EXPONENTIAL_BACKOFF, REASON="Performing exponential back off. Retry %s for api_call %s, sleeping for %s seconds" """
          % (try_count, api_call, next_sleep)
          )
      sleep(next_sleep)
      try_count += 1
      total_sleep += next_sleep
    else:
      return response
  logging.error(
      """ACTION=EXPONENTIAL_BACKOFF, STATUS=FAILED, REASON="Exponential back off failed. Retried %s times for API call %s, slept a total of %s seconds." """
      % (try_count, api_call, total_sleep)
      )
  return None


def get_boto_conn(service, region):
  """Return a boto connection object to the specified region and service"""
  if region not in [EU_WEST_1, US_EAST_1, UNIVERSAL_REGION]:
    logging.error(
        """ACTION=GET_BOTO_CONN, STATUS=FAILED, REASON="%s not a valid region" """
        % (region,)
        )
    return None
  if service not in ['ec2']:
    logging.error(
        """ACTION=GET_BOTO_CONN, STATUS=FAILED, REASON="%s not a valid service" """
        % (service,)
        )
    return None
  return connections[region][service]


# ---- Define logging options
class NullHandler(logging.Handler):
  def emit(self, record):
    pass

basename = os.path.basename(sys.argv[0])
basename = re.sub(r'^(.*)\.py', r'\1', basename)
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO, filename='/var/log/aws_dash/' + basename + '.log')

file_logger = logging.getLogger('file')
file_logger.propagate = False
file_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler('/var/log/aws_dash/' + basename + '.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
file_logger.addHandler(file_handler)

console_logger = logging.getLogger('console')
console_logger.propagate = False
console_logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(message)s'))
console_logger.addHandler(NullHandler())


# ---- Functions
def configure_logging(log_to_console=False):
  if log_to_console:
    console_logger.removeHandler(NullHandler())
    console_logger.addHandler(console_handler)
  return True


def log(level, file_string=None, console_string=None, exc_info=False):
  if file_string is not None:
    file_logger.log(getattr(logging, level.upper(), None), file_string, exc_info=exc_info)
  if console_string is not None:
    console_logger.log(getattr(logging, level.upper(), None), console_string)


def check_aws_account(aws_account_id, region=UNIVERSAL_REGION):
  account_id = None
  try:
    account_id = exponential_backoff(get_boto_conn('iam', region), "get_user")['get_user_response']['get_user_result']['user']['arn'].split(':')[4]
    logging.info(
        """ACTION=CHECK_AWS_ACCOUNT, YOUR_ACCOUNT_ID=%s, REQUIRED_ACCOUNT_ID=%s STATUS=OK"""
        % (aws_account_id, account_id)
        )
  except Exception as e:
    logging.error(
        """ACTION=CHECK_AWS_ACCOUNT, STATUS=FAILED, REASON="Your account ID %s Does not match the required account ID %s. %s" """
        % (aws_account_id, account_id, e)
        )
    print e
  if aws_account_id == account_id:
    return True
  return False


@app.route("/")
def outputDashboard():
  reservations = exponential_backoff(get_boto_conn('ec2', EU_WEST_1), "get_all_instances")
  def generate():
    for res in reservations:
      for inst in res.instances:
        if 'Name' in inst.tags:
          yield "%s (%s) [%s] <br />" % (inst.tags['Name'], inst.id, inst.state)
        else:
          yield "%s [%s] <br />" % (inst.id, inst.state)
  return Response(generate(), mimetype='text/html')

if __name__ == "__main__":
  app.run()    
