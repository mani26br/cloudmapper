"""
This library is a linter for AWS IAM policies.
"""
__version__ = "1.2.3"

import os
import json
import re

# On initialization, load the IAM data
iam_definition_path = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "iam_definition.json"
)
iam_definition = json.load(open(iam_definition_path, "r"))


def analyze_policy_string(policy_str, filepath=None):
    """Given a string reperesenting a policy, convert it to a Policy object with findings"""

    try:
        # TODO Need to write my own json parser so I can track line numbers. See https://stackoverflow.com/questions/7225056/python-json-decoding-library-which-can-associate-decoded-items-with-original-li
        policy_json = json.loads(policy_str)
    except ValueError as e:
        policy = Policy(None)
        policy.add_finding("json parsing error: {}".format(e), severity.MALFORMED)
        return policy

    policy = Policy(policy_json, filepath)
    policy.analyze()
    return policy


def is_arn_match(resource_type, arn_format, resource):
    """
    Match the arn_format specified in the docs, with the resource
    given in the IAM policy.  These can each be strings with globbing. For example, we
    want to match the following two strings:
    - arn:*:s3:::*/*
    - arn:aws:s3:::*personalize*
    
    That should return true because you could have "arn:aws:s3:::personalize/" which matches both.
    
    This problem is known as finding the intersection of two regexes.
    There is a library for this here https://github.com/qntm/greenery but it is far too slow,
    taking over two minutes for that example before I killed the process.
    The problem can be simplified because we only care about globbed strings, not full regexes,
    but there are no Python libraries, but here is one in Go: https://github.com/Pathgather/glob-intersection

    We can some cheat because after the first sections of the arn match, meaning until the 5th colon (with some
    rules there to allow empty or asterisk sections), we only need to match the ID part.
    So the above is simplified to "*/*" and "*personalize*".

    Let's look at some examples and if these should be marked as a match:
    "*/*" and "*personalize*" -> True
    "*", "mybucket" -> True
    "mybucket", "*" -> True
    "*/*", "mybucket" -> False
    "*/*", "mybucket*" -> True
    "*mybucket", "*myotherthing" -> False
    """
    if arn_format == "*" or resource == "*":
        return True

    if "bucket" in resource_type:
        # We have to do a special case here for S3 buckets
        if "/" in resource:
            return False


    arn_parts = arn_format.split(":")
    if len(arn_parts) < 6:
        raise Exception("Unexpected format for ARN: {}".format(arn_format))
    resource_parts = resource.split(":")
    if len(resource_parts) < 6:
        raise Exception("Unexpected format for resource: {}".format(resource))
    for position in range(0, 5):
        if arn_parts[position] == "*" or arn_parts[position] == "":
            continue
        elif resource_parts[position] == "*" or resource_parts[position] == "":
            continue
        elif arn_parts[position] == resource_parts[position]:
            continue
        else:
            return False

    arn_id = "".join(arn_parts[5:])
    resource_id = "".join(resource_parts[5:])

    # At this point we might have something like:
    # log-group:* for arn_id and
    # log-group:/aws/elasticbeanstalk* for resource_id

    # Look for exact match
    # Examples:
    # "mybucket", "mybucket" -> True
    # "*", "*" -> True
    if arn_id == resource_id:
        return True

    # Some of the arn_id's contain regexes of the form "[key]" so replace those with "*"
    arn_id = re.sub(r"\[.+?\]", "*", arn_id)

    # If neither contain an asterisk they can't match
    # Example:
    # "mybucket", "mybucketotherthing" -> False
    if "*" not in arn_id and "*" not in resource_id:
        return False

    # If either is an asterisk it matches
    # Examples:
    # "*", "mybucket" -> True
    # "mybucket", "*" -> True
    if arn_id == "*" or resource_id == "*":
        return True

    # We already checked if they are equal, so we know both aren't "", but if one is, and the other is not,
    # and the other is not "*" (which we just checked), then these do not match
    # Examples:
    # "", "mybucket" -> False
    if arn_id == "" or resource_id == "":
        return False

    # If one begins with an asterisk and the other ends with one, it should match
    # Examples:
    # "*/*" and "*personalize*" -> True
    if (arn_id[0] == "*" and resource_id[-1] == "*") or (
        arn_id[-1] == "*" and resource_id[0] == "*"
    ):
        return True

    # At this point, we are trying to check the following
    # "*/*", "mybucket" -> False
    # "*/*", "mybucket/abc" -> True
    # "mybucket*", "mybucketotherthing" -> True
    # "*mybucket", "*myotherthing" -> False

    # We are going to cheat and miss some possible situations, because writing something 
    # to do this correctly by generating a state machine seems much harder.

    # Check situation where it begins and ends with asterisks, such as "*/*"
    if arn_id[0] == "*" and arn_id[-1] == "*":
        if arn_id[1:-1] in resource_id:
            return True
    if resource_id[0] == "*" and resource_id[-1] == "*":
        if resource_id[1:-1] in arn_id:
            return True

    # Check where one ends with an asterisk
    if arn_id[-1] == "*":
        if resource_id[: len(arn_id) - 1] == arn_id[:-1]:
            return True
    if resource_id[-1] == "*":
        if arn_id[: len(resource_id) - 1] == resource_id[:-1]:
            return True

    return False


def get_resource_type_from_arn(arn):
    for service in iam_definition:
        for resource in service["resources"]:
            arn_format = re.sub(r"\$\{.*?\}", "*", resource["arn"])
            if is_arn_match(resource["resource"], arn, arn_format):
                print("{} - {}".format(service['service_name'], resource["resource"]))
