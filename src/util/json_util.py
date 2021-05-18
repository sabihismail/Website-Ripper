import inspect
from enum import Enum
from typing import List, get_origin, get_args, Any

from src.util.generic import log, first_or_none, LogType

SAFE_PARAMETER_MAPPING = {
    'identifier': 'id',
    'obj_type': 'type'
}

PRIMITIVE_TYPES = [
    bool,
    int,
    float,
    str,
    type(None),
]


def json_parse(json, key, default=None, fatal=False):
    if key in json:
        return json[key]

    if fatal:
        log(f'Cannot find {key} in {json}.', log_type=LogType.ERROR)

    return default


def json_parse_enum(obj, json_val, class_type, fatal=False):
    val = json_parse(obj, json_val, default=None, fatal=fatal)

    if not val:
        return None

    val = str(val).upper()
    if val not in class_type.__dict__.keys():
        log(f'Invalid Enum: {val}, Keys: {class_type.__dict__.keys()}', log_type=LogType.ERROR)

    return class_type.__dict__[val]


def json_parse_class(json: dict, class_type: type):
    signature = inspect.signature(class_type.__init__)
    args = signature.parameters.keys()
    args = [arg for arg in args if arg != 'self']

    d = {}
    for arg in args:
        arg_type = signature.parameters[arg].annotation

        if arg in SAFE_PARAMETER_MAPPING:
            temp_arg = SAFE_PARAMETER_MAPPING[arg]
        else:
            temp_arg = arg

        if temp_arg not in json:
            continue

        if arg_type in PRIMITIVE_TYPES:
            generated_arg_obj = json[temp_arg]
        elif issubclass(arg_type, Enum):
            generated_arg_obj = json_parse_enum(json, temp_arg, arg_type, fatal=True)
        elif get_origin(arg_type) and get_origin(arg_type) == list:
            list_type = first_or_none(get_args(arg_type))

            if not list_type:
                log(f'List Type {arg_type} was None, origin: {get_origin(arg_type)}', log_type=LogType.ERROR)

            generated_arg_obj = json_parse_class_list(json[temp_arg], list_type, fatal=True)
        else:
            generated_arg_obj = json_parse_class(json[temp_arg], arg_type)

        d[arg] = generated_arg_obj

    obj = class_type(**d)

    return obj


def json_parse_class_list(json_array, class_type, key: str = '', default: Any = None, fatal: bool = False):
    if key:
        json_array = json_parse(json_array, key, default=default, fatal=fatal)

    lst: List[class_type] = []

    for obj in json_array:
        obj: class_type = json_parse_class(obj, class_type)
        lst.append(obj)

    return lst


def json_parse_class_list_with_items(json_array, class_type, key_mapping_val: str):
    lst: List[class_type] = []

    for key, value in json_array.items():
        value[key_mapping_val] = key

        obj: class_type = json_parse_class(value, class_type)
        lst.append(obj)

    return lst
