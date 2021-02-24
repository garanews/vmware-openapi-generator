# Copyright 2020 VMware, Inc.
# SPDX-License-Identifier: MIT

import requests
import json
import sys
import six
import re
from six.moves import http_client

TAG_SEPARATOR = '/'
CAMELCASE_SEPARATOR_LIST = [".", "_"]


def eprint(*args, **kwargs):
    print(args, file=sys.stderr, kwargs)


def get_json(url, verify=True):
    try:
        req = requests.get(url, verify=verify)
    except Exception as ex:
        eprint('Cannot Load %s - %s' % (url, req.content))
        eprint(ex)
        return None
    if not req.ok:
        eprint('Cannot Load %s - %s' % (url, req.content))
        return None
    if 'value' in req.json():
        return req.json()['value']
    return req.json()


def write_json_data_to_file(file_name, json_data):
    """
    Utility method used to write json file.
    """
    with open(file_name, 'w+') as outfile:
        json.dump(json_data, outfile, indent=4)


def load_description():
    """
    Loads description.properties into a dictionary.
    """
    desc = {
        'content': 'VMware vSphere\u00ae Content Library empowers vSphere Admins to effectively manage VM templates, '
                   'vApps, ISO images and scripts with ease.',
        'spbm': 'SPBM',
        'vapi': 'vAPI is an extensible API Platform for modelling and delivering APIs/SDKs/CLIs.',
        'vcenter': 'VMware vCenter Server provides a centralized platform for managing your VMware vSphere environments',
        'appliance': 'The vCenter Server Appliance is a preconfigured Linux-based virtual machine'
                     ' optimized for running vCenter Server and associated services.'}
    return desc


def get_str_camel_case(string, *delimiters):
    delimiter_regex = '\\' + '|\\'.join(delimiters)
    words = [word[:1].upper() + word[1:] for word in re.split(delimiter_regex, string)]
    return ''.join(words)


def is_filtered(metadata):
    if len(metadata) == 0:
        return False
    if 'TechPreview' in metadata:
        return False
    if 'Changing' in metadata or 'Proposed' in metadata:
        return True
    return False


def recursive_ref_update(dict_obj, old, updated):
    for k, v in six.iteritems(dict_obj):
        if type(v) is str and v.endswith(old):
            dict_obj[k] = v.replace(old, updated)
        if type(v) is list:
            for element in v:
                if type(element) is dict:
                    recursive_ref_update(element, old, updated)
        if type(v) is dict:
            recursive_ref_update(v, old, updated)


def combine_dicts_with_list_values(extended, added):
    for k, v in added.items():
        list_to_extend = extended.get(k, None)
        if list_to_extend is None:
            extended[k] = v
        else:
            list_to_extend.extend(v)
            extended[k] = list(set(list_to_extend))


def extract_path_parameters(params, url):
    """
    Return list of field_infos which are path variables, another list of
    field_infos which are not path parameters and the url that eventually
    changed due to mismatching param names.
    An example of a URL that changes:
    /vcenter/resource-pool/{resource-pool} to
    /vcenter/resource-pool/{resource_pool}
    """
    # Regex to look for {} placeholders with a group to match only the
    # parameter name
    re_path_param = re.compile('{(.+?)}')
    path_params = []
    other_params = list(params)
    new_url = url
    for path_param_name_match in re_path_param.finditer(url):
        path_param_placeholder = path_param_name_match.group(1)
        path_param_info = None
        for param in other_params:
            if is_param_path_variable(param, path_param_placeholder):
                path_param_info = param
                if param.name != path_param_placeholder:
                    new_url = new_url.replace(
                        path_param_name_match.group(), '{' + param.name + '}')
                break
        if path_param_info is None:
            eprint(
                '%s parameter from %s is not found among the operation\'s parameters' %
                (path_param_placeholder, url))
        else:
            path_params.append(path_param_info)
            other_params.remove(path_param_info)
    return path_params, other_params, new_url


def is_param_path_variable(param, path_param_placeholder):
    if param.name == path_param_placeholder:
        return True
    if 'PathVariable' not in param.metadata:
        return False
    return param.metadata['PathVariable'].elements['value'].string_value == path_param_placeholder


def build_path(
        service_name,
        method,
        path,
        documentation,
        parameters,
        operation_id,
        responses,
        consumes=None,
        produces=None):
    """
    builds swagger path object
    :param service_name: name of service. ex com.vmware.vcenter.VM
    :param method: type of method. ex put, post, get, patch
    :param path: relative path to an individual endpoint
    :param documentation: api documentation
    :param parameters: input parameters for the api
    :param responses: response of the api
    :param consumes: expected media type format of api input
    :param produces: expected media type format of api output
    :return: swagger path object.
    """
    path_obj = {}
    path_obj['tags'] = tags_from_service_name(service_name)
    if method is not None:
        path_obj['method'] = method
    if path is not None:
        path_obj['path'] = path
    if documentation is not None:
        path_obj['summary'] = documentation
    if parameters is not None:
        path_obj['parameters'] = parameters
    if responses is not None:
        path_obj['responses'] = responses

    # TODO - currently 'consumes' and 'produces are global and hardcoded;
    # Create a finer-grained approach, utilizing the checks below
    if consumes is not None:
        path_obj['consumes'] = consumes
    if produces is not None:
        path_obj['produces'] = produces

    if operation_id is not None:
        path_obj['operationId'] = operation_id
    return path_obj


def remove_curly_braces(string_name):
    if '{' in string_name:
        string_name = string_name.replace('{', '')
    if '}' in string_name:
        string_name = string_name.replace('}', '')
    return string_name


def tags_from_service_name(service_name):
    """
    Generates the tags based on the service name.
    :param service_name: name of the service
    :return: a list of tags
    """
    return [TAG_SEPARATOR.join(service_name.split('.')[3:])]


def add_query_param(url, param):
    """
    Rudimentary support for adding a query parameter to a url.
    Does nothing if the parameter is already there.
    :param url: the input url
    :param param: the parameter to add (in the form of key=value)
    :return: url with added param, ?param or &param at the end
    """
    pre_param_symbol = '?'
    query_index = url.find('?')
    if query_index > -1:
        if query_index == len(url):
            pre_param_symbol = ''
        elif url[query_index + 1:].find(param) > -1:
            return url
        else:
            pre_param_symbol = '&'
    return url + pre_param_symbol + param


def add_basic_auth(path_obj):
    """Add basic auth security requirement to paths requiring it."""
    if path_obj['path'] == '/com/vmware/cis/session' and path_obj['method'] == 'post':
        path_obj['security'] = [{'basic_auth': []}]
    return path_obj


def extract_body_parameters(params):
    body_params = []
    other_params = []
    for param in params:
        if 'Body' in param.metadata or 'BodyField' in param.metadata:
            body_params.append(param)
        else:
            other_params.append(param)
    return body_params, other_params


def extract_query_parameters(params):
    query_params = []
    other_params = []
    for param in params:
        if 'Query' in param.metadata:
            query_params.append(param)
        else:
            other_params.append(param)
    return query_params, other_params


def metamodel_to_swagger_type_converter(input_type):
    """
    Converts API Metamodel type to their equivalent Swagger type.
    A tuple is returned. first value of tuple is main type.
    second value of tuple has 'format' information, if available.
    """
    input_type = input_type.lower()
    if input_type == 'date_time':
        return 'string', 'date-time'
    if input_type == 'secret':
        return 'string', 'password'
    if input_type == 'any_error':
        return 'string', None
    if input_type == 'opaque':
        return 'object', None
    if input_type == 'dynamic_structure':
        return 'object', None
    if input_type == 'uri':
        return 'string', 'uri'
    if input_type == 'id':
        return 'string', None
    if input_type == 'long':
        return 'integer', 'int64'
    if input_type == 'double':
        return 'number', 'double'
    if input_type == 'binary':
        return 'string', 'binary'
    return input_type, None


def is_type_builtin(type_):
    type_ = type_.lower()
    typeset = {
        'binary',
        'boolean',
        'datetime',
        'double',
        'dynamicstructure',
        'exception',
        'id',
        'long',
        'opaque',
        'secret',
        'string',
        'uri'}
    if type_ in typeset:
        return True
    return False


def create_req_body_from_params_list(path_obj):
    # create request body section inside path object from parameter list
    parameters = path_obj['parameters']
    if parameters:
        index = -1
        for i in range(len(parameters)):
            if '$ref' in parameters[i] and parameters[i]['$ref'].startswith('#/components/requestBodies/'):
                index = i
                break
        if index != -1:
            path_obj['requestBody'] = {'$ref': parameters[index]['$ref']}
            del parameters[index]


class HttpErrorMap:
    """
        Builds  error_map which maps vapi errors to http status codes.
    """

    def __init__(self, component_svc):
        self.component_svc = component_svc
        self.error_api_map = {}
        self.error_rest_map = {'com.vmware.vapi.std.errors.already_exists': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.already_in_desired_state': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.feature_in_use': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.internal_server_error': http_client.INTERNAL_SERVER_ERROR,
                               'com.vmware.vapi.std.errors.invalid_argument': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.invalid_element_configuration': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.invalid_element_type': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.invalid_request': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.not_found': http_client.NOT_FOUND,
                               'com.vmware.vapi.std.errors.operation_not_found': http_client.NOT_FOUND,
                               'com.vmware.vapi.std.errors.not_allowed_in_current_state': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.resource_busy': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.resource_in_use': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.resource_inaccessible': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.service_unavailable': http_client.SERVICE_UNAVAILABLE,
                               'com.vmware.vapi.std.errors.timed_out': http_client.GATEWAY_TIMEOUT,
                               'com.vmware.vapi.std.errors.unable_to_allocate_resource': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.unauthenticated': http_client.UNAUTHORIZED,
                               'com.vmware.vapi.std.errors.unauthorized': http_client.FORBIDDEN,
                               'com.vmware.vapi.std.errors.unexpected_input': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.unsupported': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.error': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.concurrent_change': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.canceled': http_client.BAD_REQUEST,
                               'com.vmware.vapi.std.errors.unverified_peer': http_client.BAD_REQUEST}

        structures = self.component_svc.get('com.vmware.vapi').info.packages['com.vmware.vapi.std.errors'].structures
        for structure in structures:
            try:
                if structures[structure].metadata['Response'] is not None:
                    code = structures[structure].metadata['Response'].elements['code'].string_value
                    self.error_api_map[structure] = int(code)
            except KeyError:
                print(structure + " :: is does not have an Error Code")
